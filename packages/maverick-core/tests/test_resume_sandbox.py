"""`maverick resume` must accept a --sandbox override.

User-testing finding: resume honored only the [sandbox] config backend and had
no --sandbox flag, so an operator who ran `start --sandbox docker` silently
resumed on the config default (often local) -- running shell on the host after
they believed they were in Docker isolation.
"""
from __future__ import annotations

import types

from click.testing import CliRunner


def test_resume_passes_sandbox_override_to_build_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
    monkeypatch.delenv("MAVERICK_CONFIG", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)

    # A resumable goal in the same isolated world the CLI opens.
    from maverick.workspace import Workspace
    from maverick.world_model import WorldModel
    w = WorldModel(Workspace.current().db_path)
    gid = w.create_goal("resumable", "")
    w.set_goal_status(gid, "blocked")
    w.close()

    captured: dict = {}
    import maverick.cli as cli_mod

    def fake_kernel():
        ns = types.SimpleNamespace()
        ns.DEFAULT_MODEL = "claude-opus-4-8"
        ns.LLM = lambda model=None: object()

        def build_sandbox(backend=None, **kw):
            captured["backend"] = backend
            return object()

        ns.build_sandbox = build_sandbox
        ns.run_goal_sync = lambda *a, **k: "FINAL: resumed."
        return ns

    monkeypatch.setattr(cli_mod, "_kernel", fake_kernel)
    res = CliRunner().invoke(
        cli_mod.main, ["resume", "--goal-id", str(gid), "--sandbox", "docker"]
    )
    assert res.exit_code == 0, res.output
    # The operator's choice reached build_sandbox instead of the config default.
    assert captured.get("backend") == "docker"


def test_resume_without_sandbox_flag_uses_config_default(tmp_path, monkeypatch):
    monkeypatch.setenv("MAVERICK_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
    monkeypatch.delenv("MAVERICK_CONFIG", raising=False)
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)

    from maverick.workspace import Workspace
    from maverick.world_model import WorldModel
    w = WorldModel(Workspace.current().db_path)
    gid = w.create_goal("resumable", "")
    w.set_goal_status(gid, "blocked")
    w.close()

    captured: dict = {}
    import maverick.cli as cli_mod

    def fake_kernel():
        ns = types.SimpleNamespace()
        ns.DEFAULT_MODEL = "claude-opus-4-8"
        ns.LLM = lambda model=None: object()

        def build_sandbox(backend=None, **kw):
            captured["backend"] = backend
            return object()

        ns.build_sandbox = build_sandbox
        ns.run_goal_sync = lambda *a, **k: "FINAL: resumed."
        return ns

    monkeypatch.setattr(cli_mod, "_kernel", fake_kernel)
    res = CliRunner().invoke(cli_mod.main, ["resume", "--goal-id", str(gid)])
    assert res.exit_code == 0, res.output
    # No override -> None, which build_sandbox resolves to the [sandbox] config.
    assert captured.get("backend") is None
