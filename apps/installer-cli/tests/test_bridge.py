"""Bridge sandbox-selection contract (post council round-2 rewrite).

The desktop sidecar no longer asks the user about deployment target or
sandbox backend (those were jargon the council flagged). It always
configures a desktop install and auto-detects Docker — local if the
daemon isn't up. These tests pin that behaviour. The full 4-question
flow is covered in test_bridge_consumer_flow.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import tomllib  # 3.11+
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from maverick_installer import bridge, wizard


def _run(monkeypatch, tmp_path, answers):
    monkeypatch.setattr(wizard, "CONFIG_DIR", tmp_path / ".maverick")
    monkeypatch.setattr(wizard, "CONFIG_FILE", tmp_path / ".maverick" / "config.toml")
    monkeypatch.setattr(wizard, "ENV_FILE", tmp_path / ".maverick" / ".env")
    it = iter(answers)
    monkeypatch.setattr(bridge, "_recv", lambda: next(it, ""))
    monkeypatch.setattr(bridge, "_send", lambda step: None)
    bridge.run()
    return tomllib.loads((tmp_path / ".maverick" / "config.toml").read_text())


_ANSWERS = ["", "Alex", "sk-ant-x", "", "$5"]  # name, key, workdir(blank), budget


def test_bridge_uses_docker_when_daemon_available(monkeypatch, tmp_path):
    monkeypatch.setattr(wizard, "_docker_available", lambda: True)
    config = _run(monkeypatch, tmp_path, _ANSWERS)
    assert config["sandbox"]["backend"] == "docker"


def test_bridge_falls_back_to_local_without_docker(monkeypatch, tmp_path):
    monkeypatch.setattr(wizard, "_docker_available", lambda: False)
    config = _run(monkeypatch, tmp_path, _ANSWERS)
    assert config["sandbox"]["backend"] == "local"


def test_bridge_never_asks_about_deployment_or_sandbox(monkeypatch, tmp_path):
    """Regression guard: the jargon questions stay gone."""
    monkeypatch.setattr(wizard, "_docker_available", lambda: False)
    sent = []
    it = iter(_ANSWERS)
    monkeypatch.setattr(wizard, "CONFIG_DIR", tmp_path / ".maverick")
    monkeypatch.setattr(wizard, "CONFIG_FILE", tmp_path / ".maverick" / "config.toml")
    monkeypatch.setattr(wizard, "ENV_FILE", tmp_path / ".maverick" / ".env")
    monkeypatch.setattr(bridge, "_recv", lambda: next(it, ""))
    monkeypatch.setattr(bridge, "_send", lambda step: sent.append(step))
    bridge.run()
    questions = " ".join(s["question"].lower() for s in sent)
    assert "deployment" not in questions
    assert "vps" not in questions
    assert "docker" not in questions
    assert "sandbox" not in questions
