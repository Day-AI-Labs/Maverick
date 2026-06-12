"""Capability revocation list (roadmap: 2028 H2 safety).

A :class:`maverick.capability.Capability` is valid until it *expires*. But a
grant sometimes has to be killed **now** — a leaked key, an agent gone rogue,
a contractor offboarded mid-run — without waiting for the TTL. This is the
revocation list: a small, persisted set of revoked principals that the tool
chokepoint consults, so a revoked principal's *next* tool call is denied even
though its signed capability is otherwise still valid.

"Propagation" is two things:

* **to running agents** — the registry is re-read whenever its file changes
  (mtime check), so an operator running ``maverick capability revoke`` in
  another process reaches agents already mid-run, not just new spawns;
* **down the delegation tree** — :meth:`revoke_subtree` walks the
  parent→child principal graph (the same delegation graph the capability
  layer already tracks) and revokes a principal *and every descendant it
  spawned*, so attenuated children can't outlive a revoked parent.

Fail-open, like the rest of the (opt-in) capability layer: an unreadable
registry logs a warning and denies nothing — a corrupt file must not brick
every agent. Operators who need a hard stop use the killswitch (fail-closed).
Only consulted when capability enforcement is on (otherwise there is no
principal to revoke against).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Revocation:
    principal: str
    revoked_at: float
    reason: str = ""


class RevocationRegistry:
    """A persisted ``principal -> Revocation`` set, re-read on file change."""

    def __init__(self, path: Path | None = None):
        self._explicit_path = Path(path) if path is not None else None
        self._cache: dict[str, Revocation] = {}
        self._mtime: float | None = None
        self._loaded = False
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        if self._explicit_path is not None:
            return self._explicit_path
        from .paths import data_dir
        return data_dir("capability_revocations.json")

    # -- read path (hot) --------------------------------------------------

    def _current_mtime(self) -> float | None:
        try:
            p = self.path
            return p.stat().st_mtime if p.exists() else None
        except OSError:
            return None

    def _load_if_changed(self) -> None:
        mtime = self._current_mtime()
        if self._loaded and mtime == self._mtime:
            return
        self._cache = self._read()
        self._mtime = mtime
        self._loaded = True

    def _read(self) -> dict[str, Revocation]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        out: dict[str, Revocation] = {}
        for pr, d in (raw or {}).items():
            if isinstance(pr, str) and isinstance(d, dict):
                out[pr] = Revocation(pr, float(d.get("revoked_at", 0.0)),
                                     str(d.get("reason", "")))
        return out

    def is_revoked(self, principal: str) -> bool:
        if not principal:
            return False
        with self._lock:
            self._load_if_changed()
            return principal in self._cache

    def revoked(self) -> dict[str, Revocation]:
        with self._lock:
            self._load_if_changed()
            return dict(self._cache)

    # -- write path (operator actions) ------------------------------------

    def _write(self, data: dict[str, Revocation]) -> None:
        p = self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {pr: {"revoked_at": r.revoked_at, "reason": r.reason}
                   for pr, r in data.items()}
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, p)
        self._cache = dict(data)
        self._mtime = self._current_mtime()
        self._loaded = True

    def revoke(self, principal: str, *, reason: str = "",
               now: float | None = None) -> Revocation:
        ts = float(now if now is not None else time.time())
        with self._lock:
            self._load_if_changed()
            data = dict(self._cache)
            rev = Revocation(principal, ts, reason)
            data[principal] = rev
            self._write(data)
            return rev

    def unrevoke(self, principal: str) -> bool:
        with self._lock:
            self._load_if_changed()
            if principal not in self._cache:
                return False
            data = dict(self._cache)
            data.pop(principal, None)
            self._write(data)
            return True

    def revoke_subtree(self, principal: str, edges: dict[str, object], *,
                       reason: str = "", now: float | None = None) -> list[str]:
        """Revoke ``principal`` and every descendant reachable via ``edges``
        (``parent -> iterable[child]``). Cycle-safe; one atomic write."""
        order = _bfs(principal, edges)
        ts = float(now if now is not None else time.time())
        with self._lock:
            self._load_if_changed()
            data = dict(self._cache)
            for pr in order:
                data[pr] = Revocation(pr, ts, reason)
            self._write(data)
        return order


def _bfs(root: str, edges: dict[str, object]) -> list[str]:
    seen: set[str] = set()
    order: list[str] = []
    stack = [root]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        order.append(cur)
        for child in (edges.get(cur) or []):
            if child not in seen:
                stack.append(child)
    return order


_shared: RevocationRegistry | None = None
_shared_lock = threading.Lock()


def shared() -> RevocationRegistry:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = RevocationRegistry()
        return _shared


def reset_shared() -> None:
    global _shared
    with _shared_lock:
        _shared = None


def is_revoked(principal: str) -> bool:
    """Fail-open convenience over the process-shared registry."""
    try:
        return shared().is_revoked(principal)
    except Exception:  # pragma: no cover -- revocation never bricks a run
        log.debug("revocation check failed for %r; allowing", principal, exc_info=True)
        return False


def revoked_principal(principals: Iterable[str] | str) -> str | None:
    """Return the first revoked principal in ``principals``, fail-open.

    Authorization callers pass the effective capability principal plus its
    ancestor lineage. This makes a parent revocation kill already-spawned
    descendants without depending on an in-memory delegation graph.
    """
    if isinstance(principals, str):
        principals = (principals,)
    try:
        reg = shared()
        for principal in principals:
            if reg.is_revoked(principal):
                return principal
    except Exception:  # pragma: no cover -- revocation never bricks a run
        log.debug("revocation lineage check failed; allowing", exc_info=True)
    return None


__all__ = ["Revocation", "RevocationRegistry", "shared", "reset_shared",
           "is_revoked", "revoked_principal"]
