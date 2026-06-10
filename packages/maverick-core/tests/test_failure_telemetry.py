"""Failure-mode telemetry: classify, opt-in record, summarize, CLI."""
from __future__ import annotations

import json

from click.testing import CliRunner
from maverick import failure_telemetry as ft
from maverick.budget import BudgetExceeded
from maverick.cli import main


def test_classify_exception():
    assert ft.classify_exception(BudgetExceeded("over")) == "budget"
    assert ft.classify_exception(TimeoutError("timed out")) == "timeout"
    assert ft.classify_exception(ConnectionError("network down")) == "network"
    assert ft.classify_exception(RuntimeError("401 unauthorized: bad api key")) == "auth"
    assert ft.classify_exception(RuntimeError("shield blocked it")) == "shield"
    assert ft.classify_exception(ValueError("something else")) == "error"


def test_record_is_noop_when_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("MAVERICK_FAILURE_TELEMETRY", raising=False)
    monkeypatch.setattr("maverick.config.load_config", lambda: {})
    p = tmp_path / "f.jsonl"
    assert ft.record("budget", path=p) is False
    assert not p.exists()


def test_record_and_summarize_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_FAILURE_TELEMETRY", "1")
    p = tmp_path / "f.jsonl"
    assert ft.record("budget", goal_id=1, detail="cap hit", path=p) is True
    ft.record("budget", path=p)
    ft.record("auth", path=p)
    ft.record("bogus_mode", path=p)  # normalizes to "error"
    s = ft.summarize(path=p)
    assert s["total"] == 4
    assert s["by_mode"]["budget"] == 2
    assert s["by_mode"]["auth"] == 1
    assert s["by_mode"]["error"] == 1
    assert oct(p.stat().st_mode)[-3:] == "600"


def test_record_failure_from_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_FAILURE_TELEMETRY", "1")
    p = tmp_path / "f.jsonl"
    ft.record_failure(TimeoutError("slow"), goal_id=7, path=p)
    rec = json.loads(p.read_text().strip())
    assert rec["mode"] == "timeout" and rec["goal_id"] == 7 and "slow" in rec["detail"]


def test_record_failure_from_mode_string(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_FAILURE_TELEMETRY", "1")
    p = tmp_path / "f.jsonl"
    ft.record_failure("shield", goal_id=3, detail="blocked", path=p)
    assert json.loads(p.read_text().strip())["mode"] == "shield"


def test_summarize_missing_and_malformed(tmp_path):
    assert ft.summarize(path=tmp_path / "absent.jsonl") == {"total": 0, "by_mode": {}}
    p = tmp_path / "f.jsonl"
    p.write_text('{"mode": "budget"}\nnot json\n\n{"mode": "auth"}\n')
    s = ft.summarize(path=p)
    assert s["total"] == 2  # the malformed line is skipped


def test_cli_failures_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MAVERICK_FAILURE_TELEMETRY", raising=False)
    monkeypatch.setattr("maverick.config.load_config", lambda: {})
    res = CliRunner().invoke(main, ["failures"])
    assert res.exit_code == 0
    assert "no recorded failures" in res.output and "telemetry is off" in res.output


def test_cli_failures_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MAVERICK_FAILURE_TELEMETRY", "1")
    from maverick.failure_telemetry import record
    record("budget")
    record("budget")
    record("auth")
    res = CliRunner().invoke(main, ["failures"])
    assert res.exit_code == 0
    assert "Failure modes (3 recorded)" in res.output
    assert "budget" in res.output
