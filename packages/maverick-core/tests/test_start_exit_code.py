"""`maverick start` must exit nonzero when the run did not complete.

User-testing finding: start exited 0 for EVERY outcome -- a run paused awaiting
a user answer, stopped by a budget/time cap, or refused by an input guard
looked identical to a clean success by exit code, so scripts and CI could not
tell them apart. start now exits 2 when the kernel marks the goal ``blocked``;
a genuinely completed (``done``) goal still exits 0.
"""
from __future__ import annotations

import types

from click.testing import CliRunner


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("MAVERICK_CONFIG", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    # A present (not necessarily valid) key passes start's provider preflight;
    # the fake kernel never makes a real call.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
    from maverick import killswitch as ks
    ks._last_file_check_ts = 0.0
    ks.clear()


def _fake_kernel(final_status: str, message: str):
    """A kernel stand-in whose run marks the goal ``final_status`` and returns
    ``message`` -- no real LLM/provider needed to exercise start's exit code."""
    ns = types.SimpleNamespace()
    ns.DEFAULT_MODEL = "claude-opus-4-8"  # anthropic SDK is installed -> preflight passes
    ns.LLM = lambda model=None: object()
    ns.build_sandbox = lambda **kw: object()

    def run_goal_sync(llm, world, bud, goal_id, **kw):
        world.set_goal_status(goal_id, final_status, result=message)
        return message

    ns.run_goal_sync = run_goal_sync
    return ns


def test_start_exits_2_when_goal_is_blocked(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    import maverick.cli as cli_mod
    monkeypatch.setattr(
        cli_mod, "_kernel",
        lambda: _fake_kernel("blocked", "Paused: waiting for you to answer 1 question."),
    )
    res = CliRunner().invoke(cli_mod.main, ["start", "QQASK plan a trip", "--sandbox", "local"])
    assert res.exit_code == 2, res.output
    assert "Paused" in res.output


def test_start_exits_0_when_goal_is_done(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    import maverick.cli as cli_mod
    monkeypatch.setattr(
        cli_mod, "_kernel",
        lambda: _fake_kernel("done", "FINAL: task complete."),
    )
    res = CliRunner().invoke(cli_mod.main, ["start", "say hi", "--sandbox", "local"])
    assert res.exit_code == 0, res.output
    assert "FINAL" in res.output
