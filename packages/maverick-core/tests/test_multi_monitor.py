"""Multi-monitor computer-use: virtual-desktop geometry over a faked mss
(ROADMAP 2028 H1). Offline; no display needed."""
from __future__ import annotations

import sys
import types

import pytest
from maverick.multi_monitor import Monitor, VirtualDesktop, list_monitors, pinned_monitor

# Primary 1920x1080 at the origin; a 1280x1024 display LEFT of it (negative x)
# whose top sits 200px above the primary's.
PRIMARY = Monitor(id=1, left=0, top=0, width=1920, height=1080)
LEFT = Monitor(id=2, left=-1280, top=-200, width=1280, height=1024)


def _install_fake_mss(monkeypatch, monitors):
    class _Sct:
        def __init__(self):
            self.monitors = monitors

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    mod = types.ModuleType("mss")
    mod.mss = _Sct
    monkeypatch.setitem(sys.modules, "mss", mod)


def test_list_monitors_via_fake_mss(monkeypatch):
    _install_fake_mss(monkeypatch, [
        {"left": -1280, "top": -200, "width": 3200, "height": 1280},  # [0] virtual
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": -1280, "top": -200, "width": 1280, "height": 1024},
    ])
    assert list_monitors() == [PRIMARY, LEFT]


def test_list_monitors_single_virtual_entry(monkeypatch):
    _install_fake_mss(monkeypatch, [{"left": 0, "top": 0, "width": 800, "height": 600}])
    assert list_monitors() == [Monitor(id=1, left=0, top=0, width=800, height=600)]


def test_list_monitors_missing_mss_actionable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "mss", None)
    with pytest.raises(ImportError, match=r"maverick-agent\[computer-use\]"):
        list_monitors()


def test_monitor_bounds_and_contains():
    assert LEFT.right == 0 and LEFT.bottom == 824
    assert LEFT.contains(-1280, -200)       # top-left inclusive
    assert LEFT.contains(-1, 823)
    assert not LEFT.contains(0, 0)          # right edge exclusive (primary's)
    assert not LEFT.contains(-1280, 824)    # bottom edge exclusive
    assert LEFT.to_mss() == {"left": -1280, "top": -200, "width": 1280, "height": 1024}


def test_virtual_desktop_bounds_include_negative_origin():
    desk = VirtualDesktop([PRIMARY, LEFT])
    assert desk.bounds == (-1280, -200, 3200, 1280)


def test_virtual_desktop_rejects_empty():
    with pytest.raises(ValueError):
        VirtualDesktop([])


def test_monitor_at_resolves_points_and_gaps():
    desk = VirtualDesktop([PRIMARY, LEFT])
    assert desk.monitor_at(960, 540) is PRIMARY
    assert desk.monitor_at(-640, 300) is LEFT
    assert desk.monitor_at(-640, 900) is None   # below the left display: a gap
    assert desk.monitor_at(5000, 540) is None


def test_to_global_from_each_monitor():
    desk = VirtualDesktop([PRIMARY, LEFT])
    assert desk.to_global(1, 10, 20) == (10, 20)
    assert desk.to_global(2, 10, 20) == (-1270, -180)


def test_to_global_validates_id_and_bounds():
    desk = VirtualDesktop([PRIMARY, LEFT])
    with pytest.raises(KeyError):
        desk.to_global(9, 0, 0)
    with pytest.raises(ValueError):
        desk.to_global(2, 1280, 0)  # local x == width: off-monitor
    with pytest.raises(ValueError):
        desk.to_global(1, -1, 0)


def test_to_local_roundtrip_and_outside():
    desk = VirtualDesktop([PRIMARY, LEFT])
    assert desk.to_local(-1270, -180) == (2, 10, 20)
    gx, gy = desk.to_global(2, 999, 500)
    assert desk.to_local(gx, gy) == (2, 999, 500)
    with pytest.raises(ValueError):
        desk.to_local(-5000, 0)


def test_capture_monitor_defaults_to_primary(monkeypatch):
    monkeypatch.delenv("MAVERICK_COMPUTER_MONITOR", raising=False)
    monkeypatch.setenv("MAVERICK_CONFIG", "/nonexistent/config.toml")
    desk = VirtualDesktop([LEFT, PRIMARY])  # order must not matter
    assert desk.capture_monitor() is PRIMARY


def test_capture_monitor_env_pin(monkeypatch):
    monkeypatch.setenv("MAVERICK_COMPUTER_MONITOR", "2")
    desk = VirtualDesktop([PRIMARY, LEFT])
    assert desk.capture_monitor() is LEFT


def test_capture_monitor_config_pin(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[computer_use]\nmonitor = 2\n", encoding="utf-8")
    monkeypatch.delenv("MAVERICK_COMPUTER_MONITOR", raising=False)
    monkeypatch.setenv("MAVERICK_CONFIG", str(cfg))
    assert pinned_monitor() == 2
    assert VirtualDesktop([PRIMARY, LEFT]).capture_monitor() is LEFT


def test_capture_monitor_invalid_pin_falls_back(caplog):
    desk = VirtualDesktop([PRIMARY, LEFT])
    with caplog.at_level("WARNING"):
        assert desk.capture_monitor(pinned=9) is PRIMARY
    assert "pinned monitor 9" in caplog.text


def test_pinned_monitor_ignores_garbage(monkeypatch):
    monkeypatch.setenv("MAVERICK_COMPUTER_MONITOR", "not-a-number")
    assert pinned_monitor() is None
    monkeypatch.setenv("MAVERICK_COMPUTER_MONITOR", "0")
    assert pinned_monitor() is None
    monkeypatch.setenv("MAVERICK_COMPUTER_MONITOR", "")
    monkeypatch.setenv("MAVERICK_CONFIG", "/nonexistent/config.toml")
    assert pinned_monitor() is None
