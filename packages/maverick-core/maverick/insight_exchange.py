"""Federated insight exchange: signed, shield-scanned learning between peers.

Swarm federation lets peers delegate WORK; this lets them share LESSONS.
``export_insights`` bundles the local consolidated dream insights and signs
the bundle with this instance's Ed25519 key (the audit-signing keypair, so
one identity covers both); ``import_insights`` verifies a bundle against the
operator's explicit trust anchors, Shield-scans and redacts every insight,
and merges through the same dedup/cap gate local dreaming uses.

Poisoning posture — deliberately stricter than skill installs:

* Imports are **fail-closed**: an unsigned bundle, an unknown key, or a bad
  signature is rejected outright. There is no TOFU path; the trust anchors
  (``[dreaming] trusted_insight_pubkeys``) must be configured by the
  operator out of band.
* Only the consolidated insight TEXT crosses the boundary — never raw
  trajectories, reflexions, goals, or user content — and each text is
  secret-redacted, Shield-scanned, length-capped, and tagged with the
  peer's key id so recalled context shows its provenance.
* Transport is the operator's problem on purpose (a file they move or
  serve); this module never opens a network connection.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from .dreaming import DreamInsight, append_insights, load_insights

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_MAX_TEXT = 400


def _canonical_bytes(ts: float, insights: list[dict]) -> bytes:
    return json.dumps(
        {"schema_version": SCHEMA_VERSION, "ts": ts, "insights": insights},
        sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")


def trusted_pubkeys() -> list[str]:
    """Operator-configured peer trust anchors (hex Ed25519 public keys)."""
    try:
        from .config import load_config
        raw = (load_config().get("dreaming", {}) or {}).get(
            "trusted_insight_pubkeys", [])
        return [str(k).strip() for k in raw if str(k).strip()]
    except Exception:  # pragma: no cover -- config never blocks
        return []


def export_insights(
    out_path: Path | str, *, path: Path | str | None = None,
    max_insights: int = 50, now: float | None = None,
) -> Path:
    """Write a signed insight bundle for a peer. Raises without crypto —
    an unsigned export would be unimportable everywhere by design."""
    from .audit.signing import _have_crypto, _load_or_create_keypair
    if not _have_crypto():
        raise RuntimeError(
            "insight export requires 'cryptography' (install "
            "'maverick-agent[audit-signing]'): bundles are always signed."
        )
    from cryptography.hazmat.primitives.asymmetric import ed25519
    insights = load_insights(path) if path is not None else load_insights()
    rows = [i.to_dict() for i in insights[-max(1, max_insights):]]
    ts = now if now is not None else time.time()
    priv, pub, key_id = _load_or_create_keypair()
    sig = ed25519.Ed25519PrivateKey.from_private_bytes(priv).sign(
        _canonical_bytes(ts, rows),
    )
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "ts": ts,
        "peer_key": pub.hex(),
        "peer_key_id": key_id,
        "insights": rows,
        "sig": sig.hex(),
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, indent=2, default=str), encoding="utf-8")
    return out


def _sanitize(text: str, *, shield: Any | None) -> str | None:
    """Redact + Shield-scan one peer insight text; None = drop it."""
    safe = str(text or "")[:_MAX_TEXT]
    try:
        from .safety.secret_detector import redact as _redact
        safe, _ = _redact(safe)
    except Exception:  # pragma: no cover
        pass
    if shield is not None:
        try:
            verdict = shield.scan_input(safe)
            if not getattr(verdict, "allowed", True):
                return None
        except Exception:  # pragma: no cover -- fail toward keeping the gate
            return None
    return safe if safe.strip() else None


def import_insights(
    bundle_path: Path | str, *, trusted: list[str] | None = None,
    path: Path | str | None = None, shield: Any | None = None,
    max_insights: int = 100,
) -> tuple[int, str]:
    """Verify + merge a peer bundle. Returns ``(imported, reason)``.

    Fail-closed: no trust anchors, an untrusted key, or a bad signature
    imports nothing. Merging goes through ``append_insights`` so peer
    lessons obey the same dedup and capacity rules as local dreams.
    """
    trusted = trusted if trusted is not None else trusted_pubkeys()
    if not trusted:
        return 0, ("no trust anchors: configure [dreaming] "
                   "trusted_insight_pubkeys with the peer's public key")
    try:
        bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return 0, f"unreadable bundle: {e}"
    peer_key = str(bundle.get("peer_key", "") or "")
    sig = str(bundle.get("sig", "") or "")
    rows = bundle.get("insights")
    try:
        ts = float(bundle.get("ts", 0.0))
    except (TypeError, ValueError):
        return 0, "malformed bundle: bad ts"
    if not peer_key or not sig or not isinstance(rows, list):
        return 0, "malformed bundle: missing peer_key/sig/insights"
    if peer_key not in trusted:
        return 0, f"untrusted peer key {peer_key[:16]!r}: refusing to import"
    from .audit.signing import _have_crypto, verify_ed25519
    if not _have_crypto():
        return 0, "cryptography not installed: cannot verify the bundle"
    if not verify_ed25519(peer_key, sig, _canonical_bytes(ts, rows)):
        return 0, "signature verification FAILED: bundle rejected"

    key_id = str(bundle.get("peer_key_id", "") or peer_key[:8])
    incoming: list[DreamInsight] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = _sanitize(row.get("text", ""), shield=shield)
        if text is None:
            continue
        try:
            evidence = max(1, int(row.get("evidence", 1) or 1))
            row_ts = float(row.get("ts", ts) or ts)
        except (TypeError, ValueError):
            continue
        incoming.append(DreamInsight(
            ts=row_ts,
            kind=str(row.get("kind", "failure_pattern"))[:40],
            # Peer department names are theirs, not ours: imported lessons
            # land in the shared pool, provenance-tagged, recalled by
            # similarity like any promoted insight.
            domain=None,
            text=f"(peer {key_id}) {text}",
            evidence=evidence,
        ))
    if not incoming:
        return 0, "bundle verified but contained no importable insights"
    kwargs: dict = {"max_insights": max_insights}
    if path is not None:
        kwargs["path"] = path
    written = append_insights(incoming, **kwargs)
    return written, "ok"


__all__ = [
    "SCHEMA_VERSION",
    "trusted_pubkeys",
    "export_insights",
    "import_insights",
]
