"""`maverick start` preflight UX: refuse early, leave no residue, exit honestly.

Platform-test findings, round 2 fixes:
  - A halted `maverick start` printed the refusal but exited 0, so scripts
    could not tell "ran" from "refused"; it also created a goal row first.
    Now: killswitch is checked before goal creation -> exit 3, no row.
  - A missing provider SDK (e.g. the openai package for vllm:/ollama:
    routed roles) surfaced AFTER the goal row existed, orphaning a failed
    goal per attempt. Now: SDK availability is preflighted before goal
    creation -> exit 2, no row, same actionable message.
  - Unknown model ids on self-hosted providers (ollama:/vllm:/tgi:/
    openai_compatible:) billed at the Sonnet fallback rate, accruing
    phantom spend for free local models. Now priced at $0.
"""
from __future__ import annotations

from click.testing import CliRunner
from maverick.budget import Budget


def _goal_count(home) -> int:
    import sqlite3
    db = home / ".maverick" / "world.db"
    if not db.exists():
        return 0
    return sqlite3.connect(db).execute("select count(*) from goals").fetchone()[0]


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("MAVERICK_CONFIG", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
    # Bust the killswitch's 1s stat-throttle so each test sees ITS home's
    # HALT state, not the previous test's cached answer (established
    # pattern, see test_q1_2026.py).
    from maverick import killswitch as ks
    ks._last_file_check_ts = 0.0
    ks.clear()


def test_halted_start_exits_3_and_creates_no_goal(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    halt = tmp_path / ".maverick" / "HALT"
    halt.parent.mkdir(parents=True, exist_ok=True)
    halt.write_text("operator\n", encoding="utf-8")

    from maverick.cli import main
    res = CliRunner().invoke(main, ["start", "blocked goal"])

    assert res.exit_code == 3, res.output
    assert "unhalt" in res.output
    assert _goal_count(tmp_path) == 0


def test_missing_sdk_exits_2_and_creates_no_goal(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    import maverick.providers as providers
    monkeypatch.setattr(
        providers, "missing_sdks",
        lambda specs: ["openai SDK not installed. Run: pip install 'maverick-agent[openai]'"],
    )

    from maverick.cli import main
    res = CliRunner().invoke(main, ["start", "sdk-less goal"])

    assert res.exit_code == 2, res.output
    assert "openai SDK not installed" in res.output
    assert _goal_count(tmp_path) == 0


def test_missing_sdks_helper_detects_absent_module(monkeypatch):
    import importlib.util

    from maverick import providers

    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *a, **k):
        if name == "openai":
            return None
        return real_find_spec(name, *a, **k)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    msgs = providers.missing_sdks(["vllm:stub-1", "claude-opus-4-8"])
    assert any("openai" in m for m in msgs)
    # anthropic SDK is installed -> no complaint about it
    assert not any("anthropic" in m.lower() for m in msgs)


def test_missing_sdks_helper_quiet_when_all_present():
    from maverick import providers
    assert providers.missing_sdks(["claude-opus-4-8"]) == []


def test_unknown_local_models_priced_zero():
    for spec in ("ollama:my-local-llm", "vllm:stub-1", "tgi:custom",
                 "openai_compatible:proxy-model"):
        b = Budget(max_dollars=1.0)
        b.record_tokens(1000, 1000, model=spec)
        assert b.dollars == 0.0, (spec, b.dollars)


def test_unknown_hosted_model_keeps_sonnet_fallback():
    b = Budget(max_dollars=10.0)
    b.record_tokens(1_000_000, 0, model="mystery-model")
    assert b.dollars > 0


def test_known_model_via_local_prefix_still_priced():
    # A REAL priced id behind a local prefix keeps its table rate
    # (prefix-stripping match has priority over the local-zero rule).
    b = Budget(max_dollars=10.0)
    b.record_tokens(1_000_000, 0, model="ollama:deepseek-chat")
    assert b.dollars > 0
