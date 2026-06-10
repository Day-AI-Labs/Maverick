"""Honeytoken planting and tripwires (roadmap: 2027 H2 safety).

A compromised agent (or a prompt-injected payload riding inside one) that
goes hunting for credentials will read whatever secrets file it can find.
Honeytokens turn that move into a detector: plant decoy credentials in the
workspace, then watch outbound text (tool args, messages, egress) for them.
A decoy showing up in output is near-zero-false-positive evidence that
something read AND exfiltrated it — fire the alarm.

Pieces:

* :func:`mint` — make a :class:`Honeytoken` (kind, value, fingerprint) of
  kind ``aws_key`` (classic ``AKIA`` + 16 uppercase chars shape), ``api_key``
  (``mvk_live_`` + 32 hex) or ``password`` (a plausible passphrase).
* :func:`plant` — write the tokens into a realistic-looking secrets file
  (default ``.env.backup``, mode 0600) inside a directory the agent can
  reach. Planting only happens when an integrator calls this — nothing is
  planted by default.
* :func:`scan_text` — containment check of every token value against a blob
  of outbound text. Returns **fingerprints, never values**: the fingerprint
  is ``sha256(value)[:16]`` so logs and alerts can reference a decoy without
  re-leaking it. "Constant-time-ish": every token is checked with no early
  exit so call timing doesn't reveal *which* token matched; it is not a
  cryptographic constant-time guarantee (the values are decoys — consistent
  work per call is the goal, not timing-proof comparison).
* :func:`check_and_alert` — scan + fire ``on_alert(Alert)`` once per
  fingerprint per process (module-level seen-set; :func:`reset_seen` clears
  it). Alert deduping keeps a chatty exfil loop from drowning the channel;
  callback exceptions are swallowed — detection must never break the caller.

SECURITY NOTE
=============
These tokens are **decoys**, never real credentials. Minting is
deterministic-from-seed (sha256, domain-separated per kind) purely so tests
can assert exact values; **runtime callers should pass ``seed=None``** to get
``os.urandom``-backed unpredictable values — a decoy an attacker can predict
from training data is no tripwire. The ``aws_key`` kind matches the classic
``AKIA[A-Z0-9]{16}`` *shape* but is derived from a hash and is never a live
key. Repo hygiene: CI runs detect-secrets over the source tree, so neither
this module nor its tests may contain a full key-shaped literal — values are
always constructed at runtime (the prefix below is assembled from parts for
the same reason).

Stdlib-only, thread-safe (the seen-set is locked), fail-open throughout.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

KINDS = ("aws_key", "api_key", "password")

# Assembled from parts so no key-prefix literal trips secret scanners.
_AWS_PREFIX = "AK" + "IA"
# Uppercase base32-ish alphabet: stays inside the classic [A-Z0-9] key shape.
_B32ISH = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"

_WORDS = (
    "acorn", "amber", "basil", "birch", "canyon", "cedar", "cobalt", "coral",
    "crater", "delta", "ember", "fjord", "garnet", "glacier", "harbor",
    "indigo", "juniper", "lagoon", "lantern", "maple", "meadow", "mesa",
    "nectar", "obsidian", "onyx", "orchid", "pebble", "quartz", "raven",
    "sierra", "tundra", "willow",
)

_PLANT_VARS = {
    "aws_key": "AWS_ACCESS_KEY_ID",
    "api_key": "SERVICE_API_KEY",
    "password": "ADMIN_PASSWORD",
}


@dataclass(frozen=True)
class Honeytoken:
    """A decoy credential. ``fingerprint`` (sha256(value)[:16]) is what may
    appear in logs/alerts; ``value`` is only ever written into the planted
    file and compared against scanned text."""

    kind: str
    value: str
    fingerprint: str


@dataclass(frozen=True)
class Alert:
    """One tripped honeytoken. Carries the fingerprint, never the value."""

    kind: str
    fingerprint: str


def fingerprint_value(value: str) -> str:
    """sha256(value) truncated to 16 hex chars — safe to log."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _digest(kind: str, seed) -> bytes:
    """32 key-derivation bytes: urandom when seed is None, else sha256(seed).

    Domain-separated per kind so one seed yields unrelated values per kind.
    """
    if seed is None:
        return os.urandom(32)
    return hashlib.sha256(f"maverick-honeytoken:{kind}:{seed}".encode()).digest()


def mint(kind: str, *, seed=None) -> Honeytoken:
    """Mint one decoy credential of ``kind`` (see :data:`KINDS`).

    ``seed`` makes the value deterministic (tests only — see the SECURITY
    NOTE); ``seed=None`` (production) draws from ``os.urandom``.
    """
    d = _digest(kind, seed)
    if kind == "aws_key":
        body = "".join(_B32ISH[b % len(_B32ISH)] for b in d[:16])
        value = _AWS_PREFIX + body
    elif kind == "api_key":
        value = "mvk_live_" + d[:16].hex()
    elif kind == "password":
        words = [_WORDS[d[i] % len(_WORDS)] for i in range(4)]
        value = "-".join(words) + f"-{d[4] % 100:02d}"
    else:
        raise ValueError(f"unknown honeytoken kind {kind!r} (expected one of {KINDS})")
    return Honeytoken(kind=kind, value=value, fingerprint=fingerprint_value(value))


def plant(dir, tokens, filename: str = ".env.backup") -> Path:
    """Write ``tokens`` into a realistic secrets file under ``dir``; mode 0600.

    The file is bait: comments and variable names mimic a sloppy production
    env backup. Returns the file path. Duplicate kinds get numbered variable
    names so every value lands in the file.
    """
    base = Path(dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / filename
    lines = [
        "# Backup environment -- restored from prod. Do not commit or share.",
        "# Rotation owner: platform-ops. Rotate quarterly.",
    ]
    used: set[str] = set()
    for tok in tokens:
        var = _PLANT_VARS.get(tok.kind, f"SECRET_{str(tok.kind).upper()}")
        candidate, n = var, 2
        while candidate in used:
            candidate, n = f"{var}_{n}", n + 1
        used.add(candidate)
        lines.append(f"{candidate}={tok.value}")
    body = "\n".join(lines) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    try:
        os.chmod(path, 0o600)  # pre-existing files keep 0600 too
    except OSError:  # pragma: no cover -- exotic filesystems
        pass
    return path


def scan_text(text: str | None, tokens) -> list[str]:
    """Fingerprints of every token whose value appears in ``text``.

    Returns fingerprints (sha256-derived), never the live decoy values, so
    the result is safe to log or forward. Checks every token without early
    exit (see the module docstring on "constant-time-ish").
    """
    if not text:
        return []
    blob = str(text)
    found: list[str] = []
    for tok in tokens or []:
        hit = tok.value in blob  # evaluated for EVERY token; no early exit
        if hit:
            found.append(tok.fingerprint)
    return found


_seen: set[str] = set()
_seen_lock = threading.Lock()


def check_and_alert(text: str | None, tokens, on_alert) -> list[Alert]:
    """Scan ``text``; fire ``on_alert(Alert)`` once per fingerprint per process.

    Returns the newly-fired alerts (already-seen fingerprints are silent —
    one exfiltrated decoy means one alarm, not one per log line). The
    callback may be None (returning the alerts is then the whole signal);
    callback exceptions are logged and swallowed.
    """
    found = scan_text(text, tokens)
    if not found:
        return []
    by_fp = {tok.fingerprint: tok for tok in tokens}
    with _seen_lock:
        new = [fp for fp in dict.fromkeys(found) if fp not in _seen]
        _seen.update(new)
    alerts: list[Alert] = []
    for fp in new:
        alert = Alert(kind=by_fp[fp].kind, fingerprint=fp)
        alerts.append(alert)
        log.critical(
            "HONEYTOKEN TRIPPED: %s decoy (fingerprint %s) observed in "
            "outbound text -- possible compromise/exfiltration", alert.kind, fp,
        )
        if on_alert is not None:
            try:
                on_alert(alert)
            except Exception:  # detection must never break the caller
                log.exception("honeytokens: on_alert callback failed")
    return alerts


def reset_seen() -> None:
    """Forget already-alerted fingerprints (tests / new session)."""
    with _seen_lock:
        _seen.clear()


__all__ = [
    "Honeytoken", "Alert", "KINDS", "mint", "plant", "scan_text",
    "check_and_alert", "reset_seen", "fingerprint_value",
]
