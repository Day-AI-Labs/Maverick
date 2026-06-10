"""Dashboard UX store: pins, saved views, trace annotations (roadmap 2027-H1 UX).

Three small per-deployment UX features share one persistence problem — tiny
per-principal records that must survive restarts but don't belong in the
world model's run data:

  * **pinned watch list** — goals a user pinned to the top of the dashboard;
  * **saved dashboard views** — named filter/query-param sets;
  * **annotated traces** — human notes attached to replay-trace steps
    (``goal_id`` + ``seq``), so a reviewer can mark "this is where it went
    wrong" and the next person sees it.

One JSON document under ``data_dir("dashboard", "ux_store.json")`` — tenant-
aware via :func:`maverick.paths.data_dir`, atomic replace on write, owner-only
permissions, thread-safe, bounded (caps below) so it can't grow unbounded.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

MAX_PINS = 200          # per principal
MAX_VIEWS = 50          # per principal
MAX_ANNOTATIONS = 1000  # per goal
_ANON = "_anon"          # principal key when auth is off


def _principal_key(principal: str | None) -> str:
    p = (principal or "").strip()
    return p or _ANON


class UxStore:
    def __init__(self, path: Path | None = None):
        if path is None:
            from .paths import data_dir
            path = data_dir("dashboard") / "ux_store.json"
        self.path = Path(path)
        self._lock = threading.Lock()

    # -- persistence ------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"pins": {}, "views": {}, "annotations": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # -- pinned watch list --------------------------------------------------

    def pin(self, principal: str | None, goal_id: int) -> list[int]:
        key = _principal_key(principal)
        with self._lock:
            data = self._load()
            pins = [int(g) for g in data["pins"].get(key, [])]
            gid = int(goal_id)
            if gid in pins:
                pins.remove(gid)
            pins.insert(0, gid)            # most-recently-pinned first
            data["pins"][key] = pins[:MAX_PINS]
            self._save(data)
            return data["pins"][key]

    def unpin(self, principal: str | None, goal_id: int) -> list[int]:
        key = _principal_key(principal)
        with self._lock:
            data = self._load()
            pins = [int(g) for g in data["pins"].get(key, []) if int(g) != int(goal_id)]
            data["pins"][key] = pins
            self._save(data)
            return pins

    def pins(self, principal: str | None) -> list[int]:
        with self._lock:
            return [int(g) for g in self._load()["pins"].get(_principal_key(principal), [])]

    # -- saved dashboard views ----------------------------------------------

    def save_view(self, principal: str | None, name: str, params: dict[str, str]) -> None:
        name = str(name).strip()
        if not name or len(name) > 80:
            raise ValueError("view name must be 1-80 chars")
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        clean = {str(k)[:64]: str(v)[:256] for k, v in params.items()}
        key = _principal_key(principal)
        with self._lock:
            data = self._load()
            views = data["views"].setdefault(key, {})
            if name not in views and len(views) >= MAX_VIEWS:
                raise ValueError(f"too many saved views (max {MAX_VIEWS})")
            views[name] = {"params": clean, "saved_at": time.time()}
            self._save(data)

    def views(self, principal: str | None) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._load()["views"].get(_principal_key(principal), {}))

    def delete_view(self, principal: str | None, name: str) -> bool:
        key = _principal_key(principal)
        with self._lock:
            data = self._load()
            views = data["views"].get(key, {})
            existed = views.pop(str(name).strip(), None) is not None
            if existed:
                self._save(data)
            return existed

    # -- trace annotations ----------------------------------------------------

    def annotate(self, goal_id: int, seq: int, note: str, *, author: str | None = None) -> dict:
        note = str(note).strip()
        if not note or len(note) > 2000:
            raise ValueError("note must be 1-2000 chars")
        entry = {
            "seq": int(seq),
            "note": note,
            "author": _principal_key(author),
            "at": time.time(),
        }
        gid = str(int(goal_id))
        with self._lock:
            data = self._load()
            notes = data["annotations"].setdefault(gid, [])
            if len(notes) >= MAX_ANNOTATIONS:
                raise ValueError(f"too many annotations on goal {goal_id} (max {MAX_ANNOTATIONS})")
            notes.append(entry)
            self._save(data)
            return entry

    def annotations(self, goal_id: int) -> list[dict]:
        with self._lock:
            notes = self._load()["annotations"].get(str(int(goal_id)), [])
            return sorted(notes, key=lambda n: (n.get("seq", 0), n.get("at", 0)))


_shared: UxStore | None = None
_shared_lock = threading.Lock()


def shared() -> UxStore:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = UxStore()
        return _shared


def reset_shared() -> None:
    """Tests / tenant switch."""
    global _shared
    with _shared_lock:
        _shared = None


__all__ = ["UxStore", "shared", "reset_shared", "MAX_PINS", "MAX_VIEWS",
           "MAX_ANNOTATIONS"]
