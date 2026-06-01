"""Regression tests for bug-hunt wave-4 fixes."""
from __future__ import annotations

import subprocess


def _docker_ok(args, **kwargs):
    if args[:2] == ["docker", "version"]:
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")
    return subprocess.CompletedProcess(args, 0, stdout="done", stderr="")


class TestSandboxHardening:
    def test_devcontainer_drops_caps_and_privilege_escalation(self, monkeypatch, tmp_path):
        from maverick.sandbox.devcontainer import DevcontainerBackend, DevcontainerSpec
        captured = []

        def fake_run(args, **kwargs):
            captured.append(args)
            return _docker_ok(args, **kwargs)

        monkeypatch.setattr(subprocess, "run", fake_run)
        backend = DevcontainerBackend(
            project_dir=tmp_path,
            spec_override=DevcontainerSpec(image="python:3.12-slim"),
        )
        backend.exec("echo hi")
        run_args = next(a for a in captured if a[:2] == ["docker", "run"])
        assert "--cap-drop" in run_args and "ALL" in run_args
        assert "no-new-privileges" in run_args

    def test_firecracker_docker_fallback_drops_caps(self, monkeypatch, tmp_path):
        from maverick.sandbox import firecracker
        monkeypatch.setattr(firecracker.shutil, "which",
                            lambda _x: "/usr/bin/firecracker")
        captured = []

        def fake_run(args, **kwargs):
            captured.append(args)
            return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        backend = firecracker.FirecrackerBackend(workdir=tmp_path, provider="local")
        backend._docker_fallback("echo hi")
        run_args = next(a for a in captured if a[:2] == ["docker", "run"])
        assert "--cap-drop" in run_args and "ALL" in run_args
        assert "no-new-privileges" in run_args


class TestCalendarAllDayEvent:
    def test_find_slot_survives_all_day_event(self, monkeypatch):
        # An all-day event yields a datetime.date; the old hasattr() check left
        # it un-normalized and the slot walk crashed with a date/datetime
        # comparison TypeError (out of _find_slot). It must now normalize the
        # date and return a real slot, not raise / report ERROR.
        import datetime as _dt

        from maverick.tools import calendar_tool

        class _DT:
            def __init__(self, v):
                self.dt = v

        class _FakeEvent:
            # all-day event: dtstart is a date, no dtend.
            icalendar_component = {"dtstart": _DT(_dt.date(2030, 1, 1))}

        class _FakeCal:
            def search(self, *a, **k):
                return [_FakeEvent()]

        monkeypatch.setattr(calendar_tool, "_get_caldav_calendar",
                            lambda: _FakeCal())
        out = calendar_tool._find_slot({"duration_minutes": 30, "search_days": 1})
        assert isinstance(out, str)
        assert not out.startswith("ERROR")
