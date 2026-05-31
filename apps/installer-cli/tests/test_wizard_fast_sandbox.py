"""`maverick init --fast` must not write a docker config it can't run.

run_fast() used to hardcode the docker sandbox even on a host with no Docker
daemon, so the very next `maverick start` blew up with "Docker not available"
on a backend the user never chose. It now mirrors write_consumer_config:
docker when the daemon is up, else local.
"""
from __future__ import annotations

from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


def _stub_fast(monkeypatch, tmp_path: Path, *, docker: bool):
    from maverick_installer import wizard

    monkeypatch.setattr(wizard, "CONFIG_DIR", tmp_path / ".maverick")
    monkeypatch.setattr(wizard, "CONFIG_FILE", tmp_path / ".maverick" / "config.toml")
    monkeypatch.setattr(wizard, "ENV_FILE", tmp_path / ".maverick" / ".env")
    monkeypatch.setattr(wizard, "preflight", lambda: True)
    monkeypatch.setattr(wizard, "welcome", lambda: None)
    monkeypatch.setattr(wizard, "smoke_test", lambda: None)
    monkeypatch.setattr(wizard, "_docker_available", lambda: docker)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return wizard


def _backend(tmp_path: Path) -> str:
    cfg = tomllib.loads((tmp_path / ".maverick" / "config.toml").read_text())
    return cfg["sandbox"]["backend"]


def test_fast_setup_falls_back_to_local_when_docker_down(monkeypatch, tmp_path):
    wizard = _stub_fast(monkeypatch, tmp_path, docker=False)
    assert wizard.run_fast() == 0
    assert _backend(tmp_path) == "local"


def test_fast_setup_uses_docker_when_daemon_up(monkeypatch, tmp_path):
    wizard = _stub_fast(monkeypatch, tmp_path, docker=True)
    assert wizard.run_fast() == 0
    assert _backend(tmp_path) == "docker"
