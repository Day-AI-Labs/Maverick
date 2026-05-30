"""Council round-2: consumer-mode flow + first-screen picker."""
from __future__ import annotations

from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover -- Py 3.10 CI matrix
    import tomli as tomllib  # type: ignore[no-redef]


# ---------- pick_mode ----------

def test_pick_mode_default_is_consumer(monkeypatch):
    from maverick_installer import wizard
    captured = {}
    def fake_select(message, choices, default=None):
        captured["default"] = default
        return default
    monkeypatch.setattr(wizard, "_q_select", fake_select)
    mode = wizard.pick_mode()
    assert mode == "consumer"
    assert captured["default"].startswith("consumer")


def test_pick_mode_advanced_selectable(monkeypatch):
    from maverick_installer import wizard
    monkeypatch.setattr(wizard, "_q_select",
                        lambda *a, **kw: "advanced - let me configure everything")
    assert wizard.pick_mode() == "advanced"


# ---------- run_consumer happy path ----------

def _stub_wizard_io(monkeypatch, tmp_path: Path, key: str = "sk-ant-test"):
    """Wire all the IO primitives the consumer flow touches."""
    from maverick_installer import wizard

    answers = iter([
        # user_name
        "Alex",
        # workdir
        str(tmp_path / "workspace"),
    ])
    # Each _q_text call pops the next answer.
    monkeypatch.setattr(wizard, "_q_text", lambda *a, **kw: next(answers))
    monkeypatch.setattr(wizard, "_q_secret", lambda *a, **kw: key)
    monkeypatch.setattr(wizard, "_q_confirm", lambda *a, **kw: True)
    monkeypatch.setattr(wizard, "_q_select", lambda *a, **kw: "$5")

    # Fix the config dir + skip the real preflight (uses console output).
    monkeypatch.setattr(wizard, "CONFIG_DIR", tmp_path / ".maverick")
    monkeypatch.setattr(wizard, "CONFIG_FILE", tmp_path / ".maverick" / "config.toml")
    monkeypatch.setattr(wizard, "ENV_FILE", tmp_path / ".maverick" / ".env")
    monkeypatch.setattr(
        wizard, "VALIDATION_CACHE_PATH",
        tmp_path / ".maverick" / "validation-cache.json",
    )
    monkeypatch.setattr(wizard, "PARTIAL_STATE_PATH",
                        tmp_path / ".maverick" / "wizard-partial.json")
    monkeypatch.setattr(wizard, "preflight", lambda: True)
    # Pretend Docker is unavailable so the test is hermetic.
    monkeypatch.setattr(wizard, "_docker_available", lambda: False)
    # Stub the validator so we don't hit Anthropic.
    monkeypatch.setattr(
        wizard, "_validate_anthropic_key", lambda k: (True, "validated"),
    )
    return wizard


def test_run_consumer_writes_safe_defaults(monkeypatch, tmp_path: Path):
    wizard = _stub_wizard_io(monkeypatch, tmp_path)
    rc = wizard.run_consumer()
    assert rc == 0

    config = tomllib.loads((tmp_path / ".maverick" / "config.toml").read_text())
    # Safe defaults per the safety seat.
    assert config["safety"]["profile"] == "strict"
    assert config["safety"]["block_threshold"] == "medium"
    assert config["sandbox"]["backend"] == "local"          # no docker
    assert "computer" in config["security"]["denied_tools"]
    assert "browser" in config["security"]["denied_tools"]
    assert "shell" in config["security"]["denied_tools"]
    assert "write_file" in config["security"]["denied_tools"]
    assert config["retention"]["audit_days"] == 30
    assert config["rate_limits"]["web_search"] == "5/60"
    assert config["persona"]["user_name"] == "Alex"
    assert config["budget"]["max_dollars"] == 5.0
    assert config["capabilities"]["web_search"] is True
    # No channels, no MCP, no plugins.
    assert "channels" not in config
    assert "mcp_servers" not in config
    assert "plugins" not in config

    # API key landed in .env at chmod 600.
    env = (tmp_path / ".maverick" / ".env").read_text()
    assert "ANTHROPIC_API_KEY=sk-ant-test" in env
    import os
    import stat
    mode = stat.S_IMODE((tmp_path / ".maverick" / ".env").stat().st_mode)
    if os.name != "nt":  # NTFS reports 0o666 regardless of the chmod
        assert mode == 0o600


def test_run_consumer_skip_key_succeeds(monkeypatch, tmp_path: Path):
    """Empty key → wizard saves config without secrets, no crash."""
    wizard = _stub_wizard_io(monkeypatch, tmp_path, key="")
    rc = wizard.run_consumer()
    assert rc == 0
    assert (tmp_path / ".maverick" / "config.toml").exists()
    # No .env created when no keys.
    assert not (tmp_path / ".maverick" / ".env").exists()


def test_run_consumer_docker_default_when_available(monkeypatch, tmp_path: Path):
    wizard = _stub_wizard_io(monkeypatch, tmp_path)
    monkeypatch.setattr(wizard, "_docker_available", lambda: True)
    wizard.run_consumer()
    config = tomllib.loads((tmp_path / ".maverick" / "config.toml").read_text())
    assert config["sandbox"]["backend"] == "docker"


def test_run_consumer_docker_mode_keeps_host_mutation_tools_enabled(monkeypatch, tmp_path: Path):
    wizard = _stub_wizard_io(monkeypatch, tmp_path)
    monkeypatch.setattr(wizard, "_docker_available", lambda: True)
    wizard.run_consumer()
    config = tomllib.loads((tmp_path / ".maverick" / "config.toml").read_text())
    denied = config["security"]["denied_tools"]
    assert "computer" in denied
    assert "browser" in denied
    assert "shell" not in denied
    assert "write_file" not in denied


def test_run_consumer_demo_command_uses_haiku(monkeypatch, tmp_path: Path, capsys):
    """Council perf seat: first-goal demo must route to Haiku for sub-2s TTFT."""
    wizard = _stub_wizard_io(monkeypatch, tmp_path)
    wizard.run_consumer()
    out = capsys.readouterr().out
    # The closing panel prints the demo command.
    assert "claude-haiku-4-5" in out
    assert "haiku about Tuesday" in out  # the curated demo prompt


def test_run_consumer_creates_workdir(monkeypatch, tmp_path: Path):
    wizard = _stub_wizard_io(monkeypatch, tmp_path)
    wizard.run_consumer()
    assert (tmp_path / "workspace").exists()


def test_run_consumer_install_failure_renders_branded_panel(monkeypatch, tmp_path: Path, capsys):
    wizard = _stub_wizard_io(monkeypatch, tmp_path)
    def _boom(*a, **kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr(wizard, "write_config", _boom)
    rc = wizard.run_consumer()
    assert rc == 1
    out = capsys.readouterr().out
    assert "Setup hit a problem" in out
    assert "disk full" in out


# ---------- run() forks on mode ----------

def test_run_consumer_routed_via_pick_mode(monkeypatch, tmp_path: Path):
    """Non-resume run() asks for mode and forks to run_consumer() on default."""
    wizard = _stub_wizard_io(monkeypatch, tmp_path)
    monkeypatch.setattr(wizard, "pick_mode", lambda: "consumer")
    monkeypatch.setattr(wizard, "welcome", lambda: None)
    rc = wizard.run(fast=False, resume=False)
    assert rc == 0
    assert (tmp_path / ".maverick" / "config.toml").exists()


def test_run_resume_skips_mode_picker(monkeypatch, tmp_path: Path):
    """--resume implies an in-progress advanced flow; don't re-pick mode."""
    from maverick_installer import wizard
    called = {"pick_mode": False, "run_consumer": False}
    monkeypatch.setattr(wizard, "pick_mode", lambda: (called.__setitem__("pick_mode", True) or "consumer"))
    monkeypatch.setattr(wizard, "run_consumer", lambda: (called.__setitem__("run_consumer", True) or 0))
    monkeypatch.setattr(wizard, "welcome", lambda: None)
    monkeypatch.setattr(wizard, "preflight", lambda: False)  # short-circuit
    wizard.run(fast=False, resume=True)
    assert called["pick_mode"] is False
    assert called["run_consumer"] is False
