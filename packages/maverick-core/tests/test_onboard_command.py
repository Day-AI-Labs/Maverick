"""`maverick onboard`: the one-command path from nothing to a finished
first goal, run in-terminal so the user sees the swarm work.

Driven with click's CliRunner and a stubbed kernel so no real LLM call or
network is needed.
"""
from __future__ import annotations

from click.testing import CliRunner

from maverick.cli import main


def test_onboard_is_registered():
    assert "onboard" in main.commands


def _stub_kernel(monkeypatch, captured):
    """Patch maverick.cli._kernel to a stub whose run_goal_sync records the
    goal and returns a canned result — no LLM, no network."""
    class _StubSandbox:
        workdir = "."

    class _StubLLM:
        def __init__(self, model=None):
            captured["model"] = model

    class _StubKernel:
        DEFAULT_MODEL = "anthropic:claude-haiku-4-5"

        def LLM(self, model=None):
            return _StubLLM(model=model)

        def build_sandbox(self, workdir=None, backend=None):
            return _StubSandbox()

        def run_goal_sync(self, llm, world, bud, goal_id, sandbox=None, max_depth=3):
            captured["ran"] = True
            captured["goal_id"] = goal_id
            return "DONE.\n\nTuesday haiku here."

    monkeypatch.setattr("maverick.cli._kernel", lambda: _StubKernel())


def test_onboard_runs_goal_when_key_present(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("MAVERICK_NO_PROGRESS", "1")  # no poller thread in test
    _stub_kernel(monkeypatch, captured)

    runner = CliRunner()
    result = runner.invoke(
        main, ["--db", str(tmp_path / "w.db"), "onboard", "My first goal"],
    )
    assert result.exit_code == 0, result.output
    assert captured.get("ran") is True
    # The result and the next-steps nudge are shown.
    assert "Tuesday haiku here." in result.output
    assert "That's the swarm." in result.output
    assert "maverick dashboard" in result.output


def test_onboard_defaults_to_demo_goal(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("MAVERICK_NO_PROGRESS", "1")
    _stub_kernel(monkeypatch, captured)

    runner = CliRunner()
    result = runner.invoke(main, ["--db", str(tmp_path / "w.db"), "onboard"])
    assert result.exit_code == 0, result.output
    # The demo goal title is shown when none is given.
    assert "haiku about Tuesday" in result.output


def test_onboard_runs_wizard_when_no_key_and_no_config(tmp_path, monkeypatch):
    # No provider key, no config -> should invoke the wizard. Stub the
    # wizard so we don't launch an interactive prompt; make it "fail" so the
    # command exits before trying to run a goal.
    for var in (
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY", "XAI_API_KEY", "MOONSHOT_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    # Point config_path at a non-existent file under tmp.
    monkeypatch.setattr("maverick.config.config_path",
                        lambda: tmp_path / "nope.toml")

    called = {"wizard": False}

    def fake_run(**kw):
        called["wizard"] = True
        return 1  # non-zero: user aborted setup

    import sys
    import types
    fake_mod = types.ModuleType("maverick_installer.wizard")
    fake_mod.run = fake_run
    pkg = types.ModuleType("maverick_installer")
    pkg.wizard = fake_mod
    monkeypatch.setitem(sys.modules, "maverick_installer", pkg)
    monkeypatch.setitem(sys.modules, "maverick_installer.wizard", fake_mod)

    runner = CliRunner()
    result = runner.invoke(main, ["--db", str(tmp_path / "w.db"), "onboard"])
    assert called["wizard"] is True
    # Wizard returned non-zero -> onboard exits without running a goal.
    assert result.exit_code == 1
