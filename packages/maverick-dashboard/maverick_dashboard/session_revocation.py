"""Per-principal session/bearer revocation epoch.

A leaked ``mvk_session`` cookie or a still-valid OIDC bearer is otherwise good
until its natural expiry (<=12h), with no way for an admin to force-invalidate
it -- and a SCIM-deprovisioned user keeps a live dashboard session. This keeps a
per-principal **revocation epoch** (a UTC timestamp): any credential whose
issued-at (``iat``) predates a principal's epoch is rejected. Bumping the epoch
-- "log out everywhere" or a SCIM deprovision -- invalidates every credential
that principal holds at once, across processes.

Store: ``<maverick_home>/session-revocations.json`` (0600 via atomic_write_text),
mirroring the rbac roster's load-modify-save under a cross-process lock.
"""
from __future__ import annotations

import json
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

from maverick.file_lock import atomic_write_text, cross_process_lock
from maverick.paths import maverick_home

_LOCK = threading.Lock()


def _path() -> Path:
    return maverick_home() / "session-revocations.json"


@contextmanager
def _locked():
    with ExitStack() as stack:
        stack.enter_context(_LOCK)
        stack.enter_context(cross_process_lock(_path()))
        yield


def _load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def revoke_principal(principal: str, *, at: float | None = None) -> None:
    """Invalidate every credential issued to ``principal`` before now.

    Monotonic: an epoch never moves backwards, so a stale concurrent write can't
    un-revoke. A blank principal is a no-op."""
    p = (principal or "").strip()
    if not p:
        return
    ts = time.time() if at is None else float(at)
    with _locked():
        data = _load()
        data[p] = max(float(data.get(p, 0.0) or 0.0), ts)
        atomic_write_text(_path(), json.dumps(data, indent=2, sort_keys=True))


def revocation_epoch(principal: str) -> float:
    """The earliest issued-at a credential for ``principal`` may carry; 0 = never
    revoked."""
    return float(_load().get((principal or "").strip(), 0.0) or 0.0)


def is_revoked(principal: str, issued_at: float | None) -> bool:
    """True when a credential's ``issued_at`` predates the principal's revocation
    epoch. A credential carrying no ``iat`` under an active epoch is treated as
    revoked -- it can't prove it post-dates the revocation."""
    floor = revocation_epoch(principal)
    if floor <= 0:
        return False
    if issued_at is None:
        return True
    try:
        return float(issued_at) < floor
    except (TypeError, ValueError):
        return True


__all__ = ["revoke_principal", "revocation_epoch", "is_revoked"]
