"""Login-time OIDC subject directory: bridge IdP identifiers to the OIDC ``sub``.

A dashboard session is keyed by the exact OIDC ``sub`` seen at login. SCIM
deprovision revokes by the IdP's SCIM attributes (``externalId`` / ``userName``
/ ``email`` / ``id``) -- but some IdPs (notably Entra/Azure AD with a
*pairwise/per-app* subject) issue a ``sub`` that equals none of those, so the
deprovision could not reach the live session. This directory closes that gap: at
every successful login it records, for the user's stable IdP identifiers, the
``sub`` actually minted into the session. SCIM deprovision then looks the
``sub`` up by those same identifiers and revokes it.

Design (matches the revocation store's discipline):

* **Privacy.** Lookup keys are ``sha256(normalized identifier)`` -- raw
  emails/usernames never touch disk. The stored value is the opaque ``sub``
  (itself the revocation key, not PII) plus a last-seen timestamp.
* **Durable + concurrent-safe.** ``<maverick_home>/oidc-subjects.json`` (0600),
  written atomically under a cross-process lock, like ``session_revocation``.
* **Bounded.** LRU-pruned to ``_MAX_ENTRIES`` by last-seen, so a long-lived
  multi-tenant deployment cannot grow the file without bound.
* **Never on the hot path of correctness.** Recording failures are swallowed
  (a missed mapping only weakens deprovision reach, never blocks a login); the
  direct-identifier revoke in ``scim`` remains the first line.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Iterable
from contextlib import ExitStack, contextmanager
from pathlib import Path

from maverick.file_lock import atomic_write_text, cross_process_lock
from maverick.paths import maverick_home

# Cap on stored identifier->sub entries. Beyond it the oldest (by last-seen) are
# pruned, so the file stays bounded for a long-lived deployment.
_MAX_ENTRIES = 50_000

_LOCK = threading.Lock()


def _path() -> Path:
    return maverick_home() / "oidc-subjects.json"


@contextmanager
def _locked():
    with ExitStack() as stack:
        stack.enter_context(_LOCK)
        stack.enter_context(cross_process_lock(_path()))
        yield


def _norm(identifier: str) -> str:
    """Case/space-normalize an identifier so ``Alice@X.com`` and ``alice@x.com``
    (and the same userName with stray whitespace) hash to one key."""
    return (identifier or "").strip().casefold()


def _key(identifier: str) -> str:
    return hashlib.sha256(_norm(identifier).encode("utf-8")).hexdigest()


def _load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        # A damaged directory only weakens deprovision reach (the direct-id
        # revoke still fires); treat as empty rather than blocking login/SCIM.
        return {}


def _prune(data: dict) -> dict:
    if len(data) <= _MAX_ENTRIES:
        return data
    # Keep the most-recently-seen _MAX_ENTRIES by timestamp.
    kept = sorted(data.items(), key=lambda kv: kv[1].get("ts", 0.0), reverse=True)
    return dict(kept[:_MAX_ENTRIES])


def record_login(sub: str, identifiers: Iterable[str], *, at: float | None = None) -> None:
    """Record that ``sub`` was seen at login for each of ``identifiers`` (e.g.
    the OIDC ``email`` / ``preferred_username`` / ``oid`` claims). Blank
    identifiers and a blank ``sub`` are skipped. Best-effort: never raises into
    the login path."""
    s = (sub or "").strip()
    keys = {_key(i) for i in identifiers if (i or "").strip()}
    if not s or not keys:
        return
    ts = time.time() if at is None else float(at)
    try:
        with _locked():
            data = _load()
            for k in keys:
                data[k] = {"sub": s, "ts": ts}
            atomic_write_text(_path(), json.dumps(_prune(data), sort_keys=True))
    except Exception:  # pragma: no cover -- recording never blocks login
        return


def subs_for(identifiers: Iterable[str]) -> set[str]:
    """Every ``sub`` recorded at login under any of ``identifiers``. Used by SCIM
    deprovision to reach a session whose ``sub`` is in no SCIM attribute."""
    data = _load()
    out: set[str] = set()
    for i in identifiers:
        if not (i or "").strip():
            continue
        entry = data.get(_key(i))
        if isinstance(entry, dict) and entry.get("sub"):
            out.add(str(entry["sub"]))
    return out


def forget(identifiers: Iterable[str]) -> None:
    """Drop the directory entries for ``identifiers`` (e.g. after a hard SCIM
    delete). Best-effort; a re-login re-records them."""
    keys = {_key(i) for i in identifiers if (i or "").strip()}
    if not keys:
        return
    try:
        with _locked():
            data = _load()
            if any(k in data for k in keys):
                for k in keys:
                    data.pop(k, None)
                atomic_write_text(_path(), json.dumps(data, sort_keys=True))
    except Exception:  # pragma: no cover -- pruning never blocks SCIM
        return


__all__ = ["record_login", "subs_for", "forget"]
