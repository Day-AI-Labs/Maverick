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
import os
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
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover
            pass

    def register(self, device: Device) -> None:
        data = self._load()
        data[device.name] = {
            "backend": device.backend,
            "min_priority": device.min_priority,
            "quiet_hours": list(device.quiet_hours) if device.quiet_hours else None,
        }
        self._save(data)

    def unregister(self, name: str) -> bool:
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
