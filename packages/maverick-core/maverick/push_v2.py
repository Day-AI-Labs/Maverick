"""Mobile push v2 — device registry + per-device routing (roadmap: 2027 H1 UX).

v1 (``notifications.notify``) fires the configured backends globally. v2 adds
what multi-device life actually needs, layered ON TOP (v1 unchanged):

* a **device registry** — each device registers a name, a backend + its
  routing detail (an ntfy topic, a Pushover device name), a minimum priority,
  and optional **quiet hours**;
* **routing** — ``push(body, priority=...)`` fans out to the devices whose
  floor the priority clears and whose quiet hours don't apply — except that
  ``urgent`` ALWAYS breaks through quiet hours (the page-me semantics);
* **delivery ledger** — each fan-out is recorded (device, ok/failed) so
  "did my phone actually get that?" is answerable (``deliveries()``).

The actual send goes through the existing ``notifications.notify`` with the
device's backend (injected in tests). Registry + ledger live in
``data_dir("push_devices.json")`` / ``push_deliveries.json`` (0600, bounded).
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

_PRIORITY_RANK = {"low": 0, "default": 1, "high": 2, "urgent": 3, "max": 3}
_LEDGER_CAP = 500


@dataclass(frozen=True)
class Device:
    name: str
    backend: str                  # ntfy | pushover | discord | slack
    min_priority: str = "default"
    quiet_hours: tuple[int, int] | None = None   # (start_hour, end_hour) local

    def accepts(self, priority: str, *, hour: int) -> bool:
        rank = _PRIORITY_RANK.get(priority, 1)
        if rank < _PRIORITY_RANK.get(self.min_priority, 1):
            return False
        if self.quiet_hours and rank < _PRIORITY_RANK["urgent"]:
            start, end = self.quiet_hours
            in_quiet = (start <= hour < end) if start <= end else (
                hour >= start or hour < end)
            if in_quiet:
                return False
        return True


class PushRegistry:
    def __init__(self, path: Path | None = None,
                 ledger_path: Path | None = None):
        if path is None:
            from .paths import data_dir
            path = data_dir("push_devices.json")
        if ledger_path is None:
            from .paths import data_dir
            ledger_path = data_dir("push_deliveries.json")
        self._path = Path(path)
        self._ledger_path = Path(ledger_path)
        # Serializes a read-modify-write of either file in-process; the
        # cross_process_lock in _locked() extends it across processes (the
        # dashboard registers devices while a run's push() fan-out appends to the
        # delivery ledger -- separate processes).
        self._lock = threading.Lock()

    def _locked(self, path: Path):
        from contextlib import ExitStack

        from .file_lock import cross_process_lock
        stack = ExitStack()
        stack.enter_context(self._lock)
        stack.enter_context(cross_process_lock(path))
        return stack

    # -- registry -------------------------------------------------------------

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self._write(self._path, data)

    @staticmethod
    def _write(path: Path, data) -> None:
        # Unique temp + os.replace (0600): a fixed ".tmp" collides between two
        # concurrent writers to the same file (one os.replace moves it out from
        # under the other, dropping a write).
        from .file_lock import atomic_write_text
        atomic_write_text(path, json.dumps(data))

    def register(self, device: Device) -> None:
        # Whole load-modify-save under the lock so two concurrent registers
        # can't both load the same registry and have the second drop the first.
        with self._locked(self._path):
            data = self._load()
            data[device.name] = {
                "backend": device.backend,
                "min_priority": device.min_priority,
                "quiet_hours": list(device.quiet_hours) if device.quiet_hours else None,
            }
            self._save(data)

    def unregister(self, name: str) -> bool:
        with self._locked(self._path):
            data = self._load()
            if name not in data:
                return False
            del data[name]
            self._save(data)
        return True

    def devices(self) -> list[Device]:
        out = []
        for name, d in sorted(self._load().items()):
            qh = d.get("quiet_hours")
            out.append(Device(
                name=name, backend=str(d.get("backend", "ntfy")),
                min_priority=str(d.get("min_priority", "default")),
                quiet_hours=tuple(qh) if qh else None,
            ))
        return out

    # -- routing ----------------------------------------------------------------

    def push(self, body: str, *, title: str = "Maverick",
             priority: str = "default", hour: int | None = None,
             send=None, now: float | None = None) -> list[dict]:
        """Fan out to eligible devices; record + return per-device outcomes.

        ``send(backend, body, title, priority) -> int`` defaults to the real
        ``notifications.notify`` (injected in tests). ``hour`` defaults to the
        local hour (quiet-hours evaluation).
        """
        if send is None:
            def send(backend, body, title, priority):  # pragma: no cover -- real path
                from .notifications import notify
                return notify(body, title=title, priority=priority,
                              backends=[backend])
        if hour is None:
            hour = time.localtime().tm_hour
        ts = float(now if now is not None else time.time())
        outcomes: list[dict] = []
        for device in self.devices():
            if not device.accepts(priority, hour=hour):
                continue
            try:
                fired = send(device.backend, body, title, priority)
                ok = bool(fired)
            except Exception:
                ok = False
            outcomes.append({"device": device.name, "backend": device.backend,
                             "ok": ok, "priority": priority, "t": ts})
        if outcomes:
            self._append_ledger(outcomes)
        return outcomes

    # -- delivery ledger -----------------------------------------------------------

    def _append_ledger(self, rows: list[dict]) -> None:
        # Whole read-append-write under the lock so two concurrent push()
        # fan-outs don't both load the ledger and lose one's delivery rows.
        with self._locked(self._ledger_path):
            ledger = self.deliveries()
            ledger.extend(rows)
            self._write(self._ledger_path, ledger[-_LEDGER_CAP:])

    def deliveries(self, *, device: str | None = None) -> list[dict]:
        try:
            rows = json.loads(self._ledger_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if device:
            rows = [r for r in rows if r.get("device") == device]
        return rows


__all__ = ["Device", "PushRegistry"]
