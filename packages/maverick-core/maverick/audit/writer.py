"""Audit log writer. Append-only NDJSON with daily rotation.

The writer is fail-safe: any exception writing the audit log is logged
to the regular Python logger and swallowed. The agent kernel must never
crash because of an audit-path bug.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .events import AuditEvent, EventKind

log = logging.getLogger(__name__)


DEFAULT_AUDIT_DIR = Path.home() / ".maverick" / "audit"


class AuditLog:
    """Append-only NDJSON sink with per-day rotation.

    Single writer instance per process. Thread-safe.
    """

    def __init__(self, audit_dir: Path = DEFAULT_AUDIT_DIR):
        self.audit_dir = audit_dir
        self._lock = threading.Lock()
        self._current_path: Optional[Path] = None
        self._current_day: Optional[str] = None

    def _path_for(self, day_str: str) -> Path:
        return self.audit_dir / f"{day_str}.ndjson"

    def _ensure_dir(self) -> bool:
        try:
            self.audit_dir.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.audit_dir, 0o700)
            except OSError:
                pass
            return True
        except OSError as e:
            log.warning("audit: cannot create dir %s: %s", self.audit_dir, e)
            return False

    def _rotate_if_needed(self) -> Path | None:
        day_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._current_day == day_str and self._current_path is not None:
            return self._current_path
        if not self._ensure_dir():
            return None
        path = self._path_for(day_str)
        # Create the file with chmod 600 if it doesn't exist.
        if not path.exists():
            try:
                path.touch()
                os.chmod(path, 0o600)
            except OSError as e:
                log.warning("audit: cannot create %s: %s", path, e)
                return None
        self._current_path = path
        self._current_day = day_str
        return path

    def record(self, event: AuditEvent) -> bool:
        """Write one event. Returns True on success."""
        with self._lock:
            path = self._rotate_if_needed()
            if path is None:
                return False
            try:
                line = json.dumps(event.to_dict(), default=str) + "\n"
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
                return True
            except (OSError, TypeError, ValueError) as e:
                log.warning("audit: write failed: %s", e)
                return False

    def tail(self, n: int = 50, day: Optional[str] = None) -> list[dict[str, Any]]:
        """Return the last ``n`` events from ``day`` (default today)."""
        if day is None:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self._path_for(day)
        if not path.exists():
            return []
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in lines[-n:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def grep(self, pattern: str, day: Optional[str] = None) -> list[dict[str, Any]]:
        """Crude regex grep over the day's events."""
        import re
        rx = re.compile(pattern)
        if day is None:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self._path_for(day)
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if rx.search(line):
                        try:
                            out.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            return []
        return out


_default: Optional[AuditLog] = None
_default_lock = threading.Lock()


def default_audit_log() -> AuditLog:
    """Singleton AuditLog at ``~/.maverick/audit/``."""
    global _default
    with _default_lock:
        if _default is None:
            _default = AuditLog()
        return _default


def record(
    kind: str,
    *,
    agent: str = "system",
    goal_id: Optional[int] = None,
    **payload: Any,
) -> bool:
    """Module-level shortcut for the default audit log."""
    event = AuditEvent(
        ts=time.time(),
        kind=kind,
        agent=agent,
        goal_id=goal_id,
        payload=payload,
    )
    return default_audit_log().record(event)


__all__ = [
    "AuditLog",
    "DEFAULT_AUDIT_DIR",
    "default_audit_log",
    "record",
    "EventKind",
]
