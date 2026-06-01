"""Q3 2026 batch 3: devcontainer sandbox, chaos harness,
notify + diagnose tools."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

# ---------- devcontainer sandbox ----------

def _stub_subprocess_ok(monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda args, *a, **k: MagicMock(returncode=0, stdout=b"", stderr=b""),
    )


def test_devcontainer_strip_jsonc():
    from maverick.sandbox.devcontainer import _strip_jsonc
    text = """
{
  // a line comment
  "image": "python:3.12", /* block comment */
  "runArgs": ["--cap-add=NET_ADMIN",],
}
"""
    cleaned = _strip_jsonc(text)
    data = json.loads(cleaned)
    assert data["image"] == "python:3.12"
    assert data["runArgs"] == ["--cap-add=NET_ADMIN"]


def test_devcontainer_requires_spec(tmp_path, monkeypatch):
    _stub_subprocess_ok(monkeypatch)
    from maverick.sandbox.devcontainer import DevcontainerBackend
    try:
        DevcontainerBackend(project_dir=tmp_path)
    except RuntimeError as e:
        assert "devcontainer.json" in str(e)
        return
    raise AssertionError("expected RuntimeError")


def test_devcontainer_rejects_build_only_spec(tmp_path, monkeypatch):
    _stub_subprocess_ok(monkeypatch)
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer" / "devcontainer.json").write_text(
        json.dumps({"dockerFile": "Dockerfile"}),
    )
    from maverick.sandbox.devcontainer import DevcontainerBackend
    try:
        DevcontainerBackend(project_dir=tmp_path)
    except RuntimeError as e:
        assert "image" in str(e) and "dockerFile" in str(e)
        return
    raise AssertionError("expected RuntimeError")


def test_devcontainer_parses_image(tmp_path, monkeypatch):
    _stub_subprocess_ok(monkeypatch)
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer" / "devcontainer.json").write_text(
        json.dumps({
            "image": "mcr.microsoft.com/devcontainers/python:3.12",
            "remoteUser": "vscode",
            "workspaceFolder": "/workspaces/myrepo",
            "containerEnv": {"FOO": "bar"},
        }),
    )
    from maverick.sandbox.devcontainer import DevcontainerBackend
    backend = DevcontainerBackend(project_dir=tmp_path)
    assert backend.spec.image.endswith(":3.12")
    assert backend.spec.remote_user == "vscode"
    assert backend.spec.workspace_folder == "/workspaces/myrepo"
    assert backend.spec.container_env == {"FOO": "bar"}




def test_devcontainer_rejects_run_args(tmp_path, monkeypatch):
    _stub_subprocess_ok(monkeypatch)
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer" / "devcontainer.json").write_text(
        json.dumps({"image": "alpine", "runArgs": ["--privileged"]}),
    )
    from maverick.sandbox.devcontainer import DevcontainerBackend
    try:
        DevcontainerBackend(project_dir=tmp_path)
    except RuntimeError as e:
        assert "runArgs" in str(e)
        return
    raise AssertionError("expected RuntimeError")

def test_devcontainer_exec_builds_docker_run(tmp_path, monkeypatch):
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer" / "devcontainer.json").write_text(
        json.dumps({
            "image": "alpine", "remoteUser": "node",
            "containerEnv": {"NODE_ENV": "test"},
        }),
    )

    captured = {"args": None}

    def _fake_run(args, *a, **k):
        if args[:2] == ["docker", "version"]:
            return MagicMock(returncode=0, stdout=b"", stderr=b"")
        captured["args"] = args
        return MagicMock(returncode=0, stdout="ran\n", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)
    from maverick.sandbox.devcontainer import DevcontainerBackend
    backend = DevcontainerBackend(project_dir=tmp_path)
    result = backend.exec("echo hi")
    assert result.ok
    args = captured["args"]
    assert "--user" in args and "node" in args
    assert "-e" in args and any("NODE_ENV=test" in s for s in args)
    assert "alpine" in args


def test_build_sandbox_constructs_devcontainer(monkeypatch, tmp_path):
    _stub_subprocess_ok(monkeypatch)
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer" / "devcontainer.json").write_text(
        json.dumps({"image": "alpine"}),
    )
    import maverick.config as cfg

    def _fake_cfg():
        return {"sandbox": {
            "backend": "devcontainer",
            "project_dir": str(tmp_path),
            "timeout": 30,
        }}

    monkeypatch.setattr(cfg, "load_config", _fake_cfg)
    monkeypatch.setattr(cfg, "get_sandbox", lambda: _fake_cfg()["sandbox"])
    from maverick.sandbox import build_sandbox
    sb = build_sandbox()
    assert sb.__class__.__name__ == "DevcontainerBackend"


# ---------- chaos harness ----------

def test_chaos_disabled_is_noop():
    from maverick.chaos import ChaosController, maybe_fail
    c = ChaosController()
    c.disable()
    # No exception, no state change.
    maybe_fail("sandbox_exec")
    maybe_fail("tool_dispatch")


def test_chaos_active_block_injects_then_restores():
    from maverick.chaos import ChaosController, ChaosInjected
    c = ChaosController()
    c.disable()
    seen_fail = False
    with c.active(sandbox_exec_fail_pct=100, seed=42):
        try:
            from maverick.chaos import maybe_fail
            maybe_fail("sandbox_exec")
        except ChaosInjected:
            seen_fail = True
    assert seen_fail
    # Restored — should not fail outside the block.
    from maverick.chaos import maybe_fail
    maybe_fail("sandbox_exec")


def test_chaos_state_is_deterministic_with_seed():
    from maverick.chaos import ChaosController, ChaosInjected, maybe_fail
    c = ChaosController()
    c.set(active=True, seed=42, sandbox_exec_fail_pct=50)
    results = []
    for _ in range(20):
        try:
            maybe_fail("sandbox_exec")
            results.append(False)
        except ChaosInjected:
            results.append(True)
    # Replay with the same seed -> same outcomes.
    c.set(active=True, seed=42, sandbox_exec_fail_pct=50)
    results2 = []
    for _ in range(20):
        try:
            maybe_fail("sandbox_exec")
            results2.append(False)
        except ChaosInjected:
            results2.append(True)
    c.disable()
    assert results == results2


def test_chaos_unknown_stage_is_ignored():
    from maverick.chaos import ChaosController, maybe_fail
    c = ChaosController()
    c.set(active=True, sandbox_exec_fail_pct=100)
    # An unknown stage never fails.
    maybe_fail("nonexistent_stage")
    c.disable()


def test_chaos_env_parses_rates(monkeypatch):
    monkeypatch.setenv("MAVERICK_CHAOS", "sandbox:30,tool:10,llm:5")
    monkeypatch.setenv("MAVERICK_CHAOS_SEED", "7")
    # Clear the singleton so the env is re-read.
    import maverick.chaos as chaos_mod
    chaos_mod._singleton = None
    try:
        c = chaos_mod.get()
        assert c.state.active is True
        assert c.state.rates == {
            "sandbox_exec": 30, "tool_dispatch": 10,
            "llm_call": 5, "http_fetch": 0,
        }
    finally:
        c.disable()
        chaos_mod._singleton = None


def test_chaos_propagates_through_local_sandbox(tmp_path):
    """LocalBackend.exec honors the chaos dial."""
    from maverick.chaos import ChaosController, ChaosInjected
    from maverick.sandbox.local import LocalBackend
    backend = LocalBackend(workdir=tmp_path, timeout=2.0)
    c = ChaosController()
    with c.active(sandbox_exec_fail_pct=100, seed=1):
        try:
            backend.exec("true")
        except ChaosInjected:
            return
    raise AssertionError("expected ChaosInjected")


def test_chaos_propagates_through_tool_dispatcher():
    import asyncio

    from maverick.chaos import ChaosController
    from maverick.tools import Tool, ToolRegistry

    reg = ToolRegistry()
    reg.register(Tool(
        name="echo",
        description="echo",
        input_schema={"type": "object", "properties": {}},
        fn=lambda args: "ok",
    ))
    c = ChaosController()
    with c.active(tool_dispatch_fail_pct=100, seed=1):
        result = asyncio.run(reg.run("echo", {}))
    # ToolRegistry.run catches its own exceptions and returns
    # "ERROR: ...". Chaos goes through the same path.
    assert "ERROR" in result
    assert "ChaosInjected" in result or "chaos" in result


# ---------- notify tool ----------

def test_notify_requires_title():
    from maverick.tools.notify import notify_tool
    out = notify_tool().fn({"body": "msg"})
    assert "requires title" in out


def test_notify_sanitizes_priority(monkeypatch):
    # notify() returns an int (backends fired) and takes a title kwarg.
    captured = {"prio": None, "title": None}

    def fake_notify(body, *, title="Maverick", priority="default",
                    category="agent", **_):
        captured["prio"] = priority
        captured["title"] = title
        return 1

    monkeypatch.setattr("maverick.notifications.notify", fake_notify)
    from maverick.tools.notify import notify_tool
    out = notify_tool().fn({"title": "hi", "priority": "BOGUS"})
    assert "sent" in out
    assert captured["prio"] == "default"
    # Title is forwarded as a distinct field, not jammed into the body.
    assert captured["title"] == "hi"


def test_notify_no_backend_configured(monkeypatch):
    # notify() returns 0 when no backend fires.
    monkeypatch.setattr(
        "maverick.notifications.notify",
        lambda *a, **k: 0,
    )
    from maverick.tools.notify import notify_tool
    out = notify_tool().fn({"title": "hello"})
    assert "no notification backend" in out


def test_notify_reports_count(monkeypatch):
    # notify() returns an int count of backends fired; the tool must format
    # that int, not call len() on it (which raised TypeError -> every
    # successful send was reported to the agent as an error).
    monkeypatch.setattr(
        "maverick.notifications.notify",
        lambda *a, **k: 2,
    )
    from maverick.tools.notify import notify_tool
    out = notify_tool().fn({"title": "hello", "body": "body"})
    assert "sent (2 backends)" in out


def test_notify_urgent_maps_to_max(monkeypatch):
    # The tool exposes "urgent"; notify() backends use "max".
    captured = {}
    monkeypatch.setattr(
        "maverick.notifications.notify",
        lambda body, *, title="Maverick", priority="default", **k:
        captured.__setitem__("prio", priority) or 1,
    )
    from maverick.tools.notify import notify_tool
    notify_tool().fn({"title": "x", "priority": "urgent"})
    assert captured["prio"] == "max"


# ---------- diagnose tool ----------

def test_diagnose_runs(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k1")
    monkeypatch.setenv("OPENAI_API_KEY", "k2")
    for k in ("DEEPSEEK_API_KEY", "MOONSHOT_API_KEY",
              "XAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    from maverick.tools.diagnose import diagnose
    out = diagnose().fn({})
    assert "Maverick self-diagnose" in out
    assert "python" in out
    assert "anthropic" in out
    assert "openai" in out
    assert "sandbox backend" in out


def test_diagnose_flags_missing_keys(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
              "MOONSHOT_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    from maverick.tools.diagnose import diagnose
    out = diagnose().fn({})
    assert "no provider keys set" in out


# ---------- registration smoke ----------

def test_notify_and_diagnose_register(tmp_path):
    from maverick.sandbox.local import LocalBackend
    from maverick.tools import base_registry

    class _W:
        def open_questions(self, gid):
            return []

    reg = base_registry(_W(), LocalBackend(workdir=tmp_path))
    names = {t.name for t in reg.all()}
    assert "notify" in names
    assert "diagnose" in names
