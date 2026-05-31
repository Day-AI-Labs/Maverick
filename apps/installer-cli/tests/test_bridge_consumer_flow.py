"""Desktop installer sidecar (bridge.py) drives the 4-question consumer
flow and writes the SAME config the CLI's run_consumer produces.

The bridge speaks a line-delimited JSON protocol over stdin/stdout.
These tests drive it in-process by monkeypatching _recv/_send so we
don't need a real subprocess.
"""
from __future__ import annotations

try:
    import tomllib  # 3.11+
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


def _drive(monkeypatch, tmp_path, answers, *, key="sk-ant-test"):
    """Run bridge.run() feeding `answers` in order; capture emitted steps."""
    from maverick_installer import bridge, wizard

    monkeypatch.setattr(wizard, "CONFIG_DIR", tmp_path / ".maverick")
    monkeypatch.setattr(wizard, "CONFIG_FILE", tmp_path / ".maverick" / "config.toml")
    monkeypatch.setattr(wizard, "ENV_FILE", tmp_path / ".maverick" / ".env")
    monkeypatch.setattr(wizard, "_docker_available", lambda: False)

    sent = []
    recv_iter = iter(answers)

    monkeypatch.setattr(bridge, "_send", lambda step: sent.append(step))
    monkeypatch.setattr(bridge, "_recv", lambda: next(recv_iter, ""))
    bridge.run()
    return sent


def test_bridge_asks_four_questions_in_order(monkeypatch, tmp_path):
    sent = _drive(monkeypatch, tmp_path, [
        "",            # initial invoke (no answer)
        "Alex",        # name
        "sk-ant-xyz",  # api key
        str(tmp_path / "ws"),  # workdir
        "$5",          # budget
    ])
    ids = [s["id"] for s in sent]
    # name → api_key → workdir → budget → __done__
    assert ids == ["name", "api_key", "workdir", "budget", "__done__"]
    # No jargon questions (no "deployment", "providers", "channels", "safety").
    for forbidden in ("deployment", "providers", "channels", "safety"):
        assert forbidden not in ids


def test_bridge_writes_consumer_safe_defaults(monkeypatch, tmp_path):
    _drive(monkeypatch, tmp_path, [
        "", "Alex", "sk-ant-xyz", str(tmp_path / "ws"), "$5",
    ])
    config = tomllib.loads((tmp_path / ".maverick" / "config.toml").read_text())
    # Identical safe defaults to the CLI consumer flow.
    assert config["safety"]["profile"] == "strict"
    assert config["sandbox"]["backend"] == "local"
    assert "computer" in config["security"]["denied_tools"]
    assert "browser" in config["security"]["denied_tools"]
    assert config["retention"]["audit_days"] == 30
    assert config["persona"]["user_name"] == "Alex"
    assert config["budget"]["max_dollars"] == 5.0
    # No channels / mcp / plugins.
    assert "channels" not in config
    assert "mcp_servers" not in config


def test_bridge_api_key_written_to_env(monkeypatch, tmp_path):
    _drive(monkeypatch, tmp_path, [
        "", "Sam", "sk-ant-secret", str(tmp_path / "ws"), "$1",
    ])
    env = (tmp_path / ".maverick" / ".env").read_text()
    assert "ANTHROPIC_API_KEY=sk-ant-secret" in env
    config = tomllib.loads((tmp_path / ".maverick" / "config.toml").read_text())
    assert config["budget"]["max_dollars"] == 1.0


def test_bridge_blank_key_skips_env(monkeypatch, tmp_path):
    sent = _drive(monkeypatch, tmp_path, [
        "", "Sam", "", str(tmp_path / "ws"), "$20",
    ])
    # No .env file when no key.
    assert not (tmp_path / ".maverick" / ".env").exists()
    # Done message acknowledges the skip.
    done = next(s for s in sent if s["id"] == "__done__")
    assert "Add an API key later" in done["question"]


def test_bridge_budget_fallback_on_garbage(monkeypatch, tmp_path):
    _drive(monkeypatch, tmp_path, [
        "", "Sam", "sk-ant-x", str(tmp_path / "ws"), "not-a-number",
    ])
    config = tomllib.loads((tmp_path / ".maverick" / "config.toml").read_text())
    assert config["budget"]["max_dollars"] == 5.0  # fallback


def test_bridge_default_workdir_when_blank(monkeypatch, tmp_path):
    _drive(monkeypatch, tmp_path, [
        "", "Sam", "sk-ant-x", "", "$5",
    ])
    config = tomllib.loads((tmp_path / ".maverick" / "config.toml").read_text())
    # Falls back to ~/Documents/Maverick.
    assert config["sandbox"]["workdir"].endswith("Maverick")


def test_bridge_steps_carry_kind_for_ui(monkeypatch, tmp_path):
    """The Svelte UI needs `kind` to render text vs secret vs choice."""
    sent = _drive(monkeypatch, tmp_path, [
        "", "Alex", "sk-ant-x", str(tmp_path / "ws"), "$5",
    ])
    by_id = {s["id"]: s for s in sent}
    assert by_id["name"]["kind"] == "text"
    assert by_id["api_key"]["kind"] == "secret"
    assert by_id["workdir"]["kind"] == "text"
    assert by_id["budget"]["kind"] == "choice"
