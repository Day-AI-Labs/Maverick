"""Multi-monitor computer-use (roadmap: 2028 H1 capabilities).

The computer tool assumes one display: screenshots grab ``sct.monitors[1]``
and clicks clamp to the primary's size. With several displays the OS exposes
ONE virtual desktop whose origin is the primary's top-left — a monitor placed
left of (or above) the primary has NEGATIVE global coordinates, and naive
clamping to ``(0, 0, w, h)`` makes half the desktop unreachable.

This models that virtual desktop:

- :func:`list_monitors` enumerates displays via mss (lazy import, same
  ``[computer-use]`` extra and error message as the computer tool);
- :class:`VirtualDesktop` is the pure geometry: union ``bounds`` (negative
  origins included), ``monitor_at(x, y)``, ``to_global(monitor_id, x, y)`` /
  ``to_local(x, y)`` conversions, and ``capture_monitor()`` — which monitor a
  screenshot should grab;
- :func:`pinned_monitor` reads the operator pin: ``MAVERICK_COMPUTER_MONITOR``
  or ``[computer_use] monitor = N`` in config.toml.

Monitor ids are 1-based and match mss's ``sct.monitors`` indices, so id 1 is
the primary and a pin of N means "mss monitor N". Only :func:`list_monitors`
touches mss; everything else takes plain :class:`Monitor` values, so tests
inject fakes and never need a display.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Monitor:
    """One display's bounds in global (virtual-desktop) pixels."""

    id: int
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def contains(self, x: int, y: int) -> bool:
        """True when the global point is on this monitor (right/bottom exclusive)."""
        return self.left <= x < self.right and self.top <= y < self.bottom

    def to_mss(self) -> dict[str, int]:
        """The region dict ``mss.grab()`` expects for this monitor."""
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


def list_monitors() -> list[Monitor]:
    """Enumerate displays via mss. Raises an actionable ImportError without it."""
    try:
        import mss
    except ImportError as e:
        raise ImportError(
            "mss not installed. Run: pip install 'maverick-agent[computer-use]'"
        ) from e
    with mss.mss() as sct:
        raw = sct.monitors
        # mss index 0 is the all-monitors bounding box; 1.. are the real
        # displays. A degenerate backend may only report the virtual entry.
        entries = raw[1:] if len(raw) > 1 else raw
        return [
            Monitor(
                id=i,
                left=int(m["left"]),
                top=int(m["top"]),
                width=int(m["width"]),
                height=int(m["height"]),
            )
            for i, m in enumerate(entries, start=1)
        ]


def pinned_monitor() -> int | None:
    """The operator's monitor pin, or ``None`` (use the primary).

    ``MAVERICK_COMPUTER_MONITOR`` wins over ``[computer_use] monitor = N`` in
    config.toml. Anything that isn't a positive integer reads as "no pin".
    """
    raw: object = os.environ.get("MAVERICK_COMPUTER_MONITOR", "").strip()
    if not raw:
        try:
            from .config import load_config

            raw = (load_config().get("computer_use") or {}).get("monitor")
        except Exception:  # pragma: no cover -- config must never block
            raw = None
    try:
        n = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


class VirtualDesktop:
    """Pure geometry over a set of monitors (the OS's one virtual desktop)."""

    def __init__(self, monitors: Sequence[Monitor] | None = None):
        self.monitors = list(monitors) if monitors is not None else list_monitors()
        if not self.monitors:
            raise ValueError("no monitors")
        self._by_id = {m.id: m for m in self.monitors}

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """Union bounding box ``(left, top, width, height)`` — left/top may be negative."""
        left = min(m.left for m in self.monitors)
        top = min(m.top for m in self.monitors)
        right = max(m.right for m in self.monitors)
        bottom = max(m.bottom for m in self.monitors)
        return (left, top, right - left, bottom - top)

    def monitor_at(self, x: int, y: int) -> Monitor | None:
        """The monitor showing the global point, or ``None`` (a gap in the layout)."""
        for m in self.monitors:
            if m.contains(x, y):
                return m
        return None

    def to_global(self, monitor_id: int, x: int, y: int) -> tuple[int, int]:
        """Monitor-local pixel -> global virtual-desktop pixel."""
        m = self._by_id.get(monitor_id)
        if m is None:
            raise KeyError(f"unknown monitor id {monitor_id}; have {sorted(self._by_id)}")
        if not (0 <= x < m.width and 0 <= y < m.height):
            raise ValueError(
                f"local ({x}, {y}) is outside monitor {monitor_id} ({m.width}x{m.height})"
            )
        return (m.left + x, m.top + y)

    def to_local(self, x: int, y: int) -> tuple[int, int, int]:
        """Global pixel -> ``(monitor_id, local_x, local_y)``."""
        m = self.monitor_at(x, y)
        if m is None:
            raise ValueError(f"global ({x}, {y}) is not on any monitor")
        return (m.id, x - m.left, y - m.top)

    def capture_monitor(self, pinned: int | None = None) -> Monitor:
        """Which monitor a screenshot should grab.

        The pin (explicit arg, else :func:`pinned_monitor`) wins when it names
        a real monitor; an invalid pin logs a warning and falls back to the
        primary (lowest id) rather than failing the capture.
        """
        if pinned is None:
            pinned = pinned_monitor()
        if pinned is not None:
            m = self._by_id.get(pinned)
            if m is not None:
                return m
            log.warning(
                "pinned monitor %d not found (have %s); using primary",
                pinned, sorted(self._by_id),
            )
        return min(self.monitors, key=lambda m: m.id)


__all__ = ["Monitor", "VirtualDesktop", "list_monitors", "pinned_monitor"]
