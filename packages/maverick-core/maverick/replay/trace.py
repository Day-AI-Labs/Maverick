"""Replayable trace format: an append-only JSONL event log you can replay.

Records ordered run events (tool calls, LLM turns, decisions) to a JSONL file so
a run can be reconstructed deterministically offline for debugging or a
regression replay. One JSON object per line — ``{seq, t, kind, ...fields}`` —
which makes the file ``tail``-able, ``grep``-able, and resilient: the reader
tolerates a partial/corrupt trailing line (the common case when a process is
killed mid-write). Dependency-free.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class TraceWriter:
    """Append events to a JSONL trace. Each ``record`` is one line, flushed."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Traces mirror blackboard posts, which may contain private run data.
        # Do not let the process umask create group/world-readable artifacts.
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        self._seq = 0
        fd = os.open(self.path, flags, 0o600)
        try:
            os.chmod(self.path, 0o600)
            self._fh = os.fdopen(fd, "a", encoding="utf-8")
        except Exception:
            os.close(fd)
            raise

    def record(self, kind: str, **fields: Any) -> int:
        """Write one ordered event; returns its sequence number."""
        self._seq += 1
        event = {"seq": self._seq, "t": round(time.time(), 6), "kind": kind}
        for k, v in fields.items():
            event[k] = _safe(v)
        self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._fh.flush()
        return self._seq

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:  # pragma: no cover
            pass

    def __enter__(self) -> TraceWriter:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _safe(v: Any) -> Any:
    """Coerce a value to something JSON-serialisable (best effort)."""
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    if isinstance(v, dict):
        return {str(k): _safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_safe(x) for x in v]
    return str(v)


def read_trace(path: str | Path) -> list[dict]:
    """Parse a trace file into a list of events.

    Skips blank lines and a single malformed trailing line (a half-written
    record from a killed process); a malformed line in the *middle* is also
    skipped, so one corrupt event never aborts the whole replay.
    """
    p = Path(path)
    if not p.exists():
        return []
    events: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events


def replay(path: str | Path, handlers: dict[str, Callable[[dict], Any]]) -> int:
    """Dispatch each event to ``handlers[kind]`` in sequence order.

    Returns the number of events dispatched. Events whose ``kind`` has no handler
    are skipped; a ``"*"`` handler, if present, catches everything else.
    """
    events = sorted(read_trace(path), key=lambda e: e.get("seq", 0))
    n = 0
    for ev in events:
        handler = handlers.get(ev.get("kind", "")) or handlers.get("*")
        if handler is not None:
            handler(ev)
            n += 1
    return n


__all__ = ["TraceWriter", "read_trace", "replay"]
