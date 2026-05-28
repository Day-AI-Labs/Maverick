"""Q3 2026 batch 5: Android tool, iOS Simulator tool,
spend report tool, replay export."""
from __future__ import annotations

import json
import platform
from unittest.mock import MagicMock


# ---------- Android tool ----------

def test_android_requires_op():
    from maverick.tools.android import android
    assert "op is required" in android().fn({})


def test_android_missing_adb(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: None)
    from maverick.tools.android import android
    out = android().fn({"op": "devices"})
    assert "adb not found" in out


def test_android_devices_parses(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/adb")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(
            returncode=0,
            stdout="List of devices attached\nemulator-5554\tdevice product:sdk_gphone\n",
            stderr="",
        ),
    )
    from maverick.tools.android import android
    out = android().fn({"op": "devices"})
    assert "emulator-5554" in out


def test_android_no_devices(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/adb")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(
            returncode=0,
            stdout="List of devices attached\n",
            stderr="",
        ),
    )
    from maverick.tools.android import android
    out = android().fn({"op": "devices"})
    assert "no devices attached" in out


def test_android_tap_builds_input(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/adb")
    captured = {"cmd": None}

    def _run(cmd, *a, **k):
        captured["cmd"] = cmd
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", _run)
    from maverick.tools.android import android
    out = android().fn({"op": "tap", "x": 100, "y": 200, "device": "abc"})
    assert "tapped (100,200)" in out
    assert "shell" in captured["cmd"]
    assert "input" in captured["cmd"]
    assert "tap" in captured["cmd"]
    assert "abc" in captured["cmd"]


def test_android_screenshot_writes_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/adb")
    fake_png = b"\x89PNG\r\n\x1a\n" + b"x" * 200

    def _run(cmd, *a, **k):
        return MagicMock(returncode=0, stdout=fake_png, stderr=b"")

    monkeypatch.setattr("subprocess.run", _run)
    out_file = tmp_path / "shot.png"
    from maverick.tools.android import android
    out = android().fn({"op": "screenshot", "out_path": str(out_file)})
    assert "saved" in out
    assert out_file.read_bytes() == fake_png


def test_android_install_requires_apk():
    from maverick.tools.android import android
    out = android().fn({"op": "install"})
    # Without an apk path we should hit the validation message before
    # the adb shell out happens. Tolerate either "requires apk_path"
    # or the adb-missing fallback.
    assert "requires apk_path" in out or "adb not found" in out


# ---------- iOS Sim tool ----------

def test_ios_only_macos(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    from maverick.tools.ios_sim import ios_sim
    out = ios_sim().fn({"op": "list_devices"})
    assert "macOS" in out


def test_ios_missing_xcrun(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr("shutil.which", lambda b: None)
    from maverick.tools.ios_sim import ios_sim
    out = ios_sim().fn({"op": "list_devices"})
    assert "xcrun not found" in out


def test_ios_list_devices(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/xcrun")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: MagicMock(
            returncode=0,
            stdout="-- iOS 17.0 --\n  iPhone 15 (ABC-123) (Booted)\n",
            stderr="",
        ),
    )
    from maverick.tools.ios_sim import ios_sim
    out = ios_sim().fn({"op": "list_devices", "state": "booted"})
    assert "iPhone 15" in out


def test_ios_install_requires_app(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/xcrun")
    from maverick.tools.ios_sim import ios_sim
    out = ios_sim().fn({"op": "install", "device_id": "ABC"})
    assert "requires" in out and "app_path" in out


def test_ios_boot_calls_simctl(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr("shutil.which", lambda b: "/usr/bin/xcrun")
    captured = {"cmd": None}

    def _run(cmd, *a, **k):
        captured["cmd"] = cmd
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", _run)
    from maverick.tools.ios_sim import ios_sim
    out = ios_sim().fn({"op": "boot", "device_id": "ABC-123"})
    assert "booted ABC-123" in out
    assert "simctl" in captured["cmd"] and "boot" in captured["cmd"]


# ---------- Spend report tool ----------

class _FakeEp:
    def __init__(self, id, role, cost, finished_at):
        self.id = id
        self.role = role
        self.cost_dollars = cost
        self.finished_at = finished_at


def _patch_world(monkeypatch, episodes):
    class _W:
        def list_episodes(self, limit=200):
            return episodes[:limit]

    import maverick.world_model
    monkeypatch.setattr(maverick.world_model, "WorldModel", lambda: _W())


def test_spend_recent_empty(monkeypatch):
    _patch_world(monkeypatch, [])
    from maverick.tools.spend_report import spend_report
    out = spend_report().fn({"op": "recent"})
    assert "no episodes" in out


def test_spend_recent_renders(monkeypatch):
    import time as _time
    now = _time.time()
    eps = [
        _FakeEp(1, "orchestrator", 0.05, now - 60),
        _FakeEp(2, "proposer", 0.01, now - 30),
    ]
    _patch_world(monkeypatch, eps)
    from maverick.tools.spend_report import spend_report
    out = spend_report().fn({"op": "recent", "limit": 10})
    assert "orchestrator" in out and "proposer" in out
    assert "0.0500" in out


def test_spend_by_role_aggregates(monkeypatch):
    eps = [
        _FakeEp(1, "orchestrator", 0.05, 0),
        _FakeEp(2, "orchestrator", 0.03, 0),
        _FakeEp(3, "proposer", 0.01, 0),
    ]
    _patch_world(monkeypatch, eps)
    from maverick.tools.spend_report import spend_report
    out = spend_report().fn({"op": "by_role"})
    assert "orchestrator" in out
    assert "0.0800" in out  # 0.05 + 0.03
    assert "0.0100" in out


def test_spend_anomalies_flags_outliers(monkeypatch):
    eps = [
        _FakeEp(1, "p", 0.01, 0),
        _FakeEp(2, "p", 0.01, 0),
        _FakeEp(3, "p", 0.01, 0),
        _FakeEp(4, "p", 0.01, 0),
        _FakeEp(5, "p", 0.50, 0),  # 50× the median
    ]
    _patch_world(monkeypatch, eps)
    from maverick.tools.spend_report import spend_report
    out = spend_report().fn({"op": "anomalies"})
    assert "median" in out
    assert "$0.5000" in out or "0.5000" in out


def test_spend_total_renders(monkeypatch):
    import time as _time
    now = _time.time()
    eps = [
        _FakeEp(1, "p", 1.0, now - 30),       # in last hour
        _FakeEp(2, "p", 2.0, now - 7200),     # in last 24h
        _FakeEp(3, "p", 3.0, now - 86400 * 5),  # older
    ]
    _patch_world(monkeypatch, eps)
    from maverick.tools.spend_report import spend_report
    out = spend_report().fn({"op": "total"})
    assert "lifetime:" in out and "6.0000" in out
    assert "last 24h:" in out and "3.0000" in out
    assert "last 1h:" in out and "1.0000" in out


# ---------- Replay export ----------

def _seed_audit(dir_path, goal_id, events):
    dir_path.mkdir(parents=True, exist_ok=True)
    f = dir_path / "2026-05-28.ndjson"
    with open(f, "w", encoding="utf-8") as out:
        for ev in events:
            line = dict(ev)
            line.setdefault("goal_id", goal_id)
            out.write(json.dumps(line) + "\n")
    return f


def test_replay_export_html(tmp_path, monkeypatch):
    audit = tmp_path / "audit"
    _seed_audit(audit, 42, [
        {"kind": "goal_start", "ts": 1700000000, "title": "do thing"},
        {"kind": "tool_call", "ts": 1700000010, "tool": "shell", "args": "ls"},
        {"kind": "goal_end", "ts": 1700000020, "status": "done"},
        # An event from a different goal should be excluded.
        {"kind": "goal_start", "ts": 1700000030, "goal_id": 99, "title": "other"},
    ])
    import maverick.replay_export as rex
    monkeypatch.setattr(rex, "_AUDIT_DIR", audit)
    out_file = tmp_path / "replay.html"
    n = rex.export_html(42, out_file)
    assert n == 3
    html = out_file.read_text(encoding="utf-8")
    assert "goal 42" in html
    assert "3 event" in html
    assert "tool_call" in html
    assert "other" not in html


def test_replay_export_json(tmp_path, monkeypatch):
    audit = tmp_path / "audit"
    _seed_audit(audit, 7, [
        {"kind": "goal_start", "ts": 0},
        {"kind": "tool_call", "ts": 1, "tool": "shell"},
    ])
    import maverick.replay_export as rex
    monkeypatch.setattr(rex, "_AUDIT_DIR", audit)
    out_file = tmp_path / "replay.json"
    n = rex.export_json(7, out_file)
    assert n == 2
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["goal_id"] == 7
    assert len(data["events"]) == 2


def test_replay_export_empty_goal(tmp_path, monkeypatch):
    audit = tmp_path / "audit"
    audit.mkdir()
    import maverick.replay_export as rex
    monkeypatch.setattr(rex, "_AUDIT_DIR", audit)
    out_file = tmp_path / "replay.html"
    n = rex.export_html(123, out_file)
    assert n == 0
    assert "No events recorded" in out_file.read_text(encoding="utf-8")


# ---------- registration smoke ----------

def test_new_tools_register(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    assert "android" in names
    assert "ios_sim" in names
    assert "spend_report" in names
