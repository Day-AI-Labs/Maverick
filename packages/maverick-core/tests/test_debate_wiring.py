"""`maverick debate QUESTION` — a CLI entry point for the debate primitive.

run_debate (two LLM debaters argue, a judge picks a winner) existed and was
tested but had no way to invoke it. The command builds a proponent + skeptic
from the configured LLM, runs the debate, and prints the judged verdict.
"""
from __future__ import annotations

import types

from click.testing import CliRunner


def test_debate_command_registered():
    from maverick.cli import main
    assert "debate" in main.commands


def test_debate_command_prints_verdict(monkeypatch):
    # The commands now preflight providers (round-3 fix); the LLM is
    # still mocked -- a dummy key just satisfies the gate.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    import maverick.debate as debate_mod
    from maverick import cli as cli_mod
    from maverick.debate import DebateResult, DebateTurn

    class _FakeLLM:
        def __init__(self, model=None):
            self.model = model

        def complete(self, **kw):  # never reached -- run_debate is stubbed
            raise AssertionError("run_debate is stubbed; complete must not run")

    monkeypatch.setattr(
        cli_mod, "_kernel",
        lambda: types.SimpleNamespace(LLM=_FakeLLM, DEFAULT_MODEL="fake"),
    )

    captured: dict = {}

    def _fake_run_debate(question, participants, *, judge_complete, rounds=2, budget=None, **kw):
        captured["question"] = question
        captured["names"] = [p.name for p in participants]
        captured["rounds"] = rounds
        return DebateResult(
            transcript=[
                DebateTurn(speaker="Proponent", text="ship: it is ready"),
                DebateTurn(speaker="Skeptic", text="wait: tests are flaky"),
            ],
            winner="Skeptic",
            judge_reason="flaky tests outweigh readiness",
            key_argument="flaky tests",
            rounds_completed=rounds,
            total_dollars=0.0123,
        )

    monkeypatch.setattr(debate_mod, "run_debate", _fake_run_debate)

    res = CliRunner().invoke(
        cli_mod.main, ["debate", "Should we ship today?", "--rounds", "1"],
    )
    assert res.exit_code == 0, res.output
    assert captured["question"] == "Should we ship today?"
    assert captured["names"] == ["Proponent", "Skeptic"]   # two sides built
    assert captured["rounds"] == 1
    assert "Winner: Skeptic" in res.output
    assert "ship: it is ready" in res.output
    assert "wait: tests are flaky" in res.output
    assert "$0.0123" in res.output
