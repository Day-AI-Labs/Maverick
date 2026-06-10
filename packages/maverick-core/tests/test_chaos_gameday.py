"""Chaos game-day drill: scenarios hold against the real retry layer."""
from __future__ import annotations

from maverick.chaos_gameday import (
    SCENARIOS,
    main,
    run_gameday,
    scenario_chaos_off_is_clean,
    scenario_hard_outage_fails_fast,
    scenario_tool_flake_absorbed,
)


def test_control_scenario_clean():
    r = scenario_chaos_off_is_clean()
    assert r.holds, r.detail


def test_tool_flake_absorbed_by_retries():
    r = scenario_tool_flake_absorbed()
    assert r.holds, r.detail


def test_hard_outage_bounded():
    r = scenario_hard_outage_fails_fast()
    assert r.holds, r.detail


def test_full_gameday_passes_and_main_exit_codes(capsys):
    report = run_gameday()
    assert report.ok, [r.detail for r in report.results if not r.holds]
    assert len(report.results) == len(SCENARIOS)
    assert main() == 0
    out = capsys.readouterr().out
    assert "game day: PASS" in out and out.count("[PASS]") == len(SCENARIOS)


def test_crashed_scenario_is_failed_drill(monkeypatch):
    import maverick.chaos_gameday as gd

    def boom():
        raise RuntimeError("scenario infra broke")

    monkeypatch.setattr(gd, "SCENARIOS", (boom,))
    report = gd.run_gameday()
    assert not report.ok and "crashed" in report.results[0].detail
