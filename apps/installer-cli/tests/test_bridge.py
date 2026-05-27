from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from maverick_installer import bridge


def _run_bridge_with_answers(monkeypatch, answers: list[str]) -> tuple[list[dict], dict]:
    sent: list[dict] = []
    written: dict = {}
    it = iter(answers)

    monkeypatch.setattr(bridge, "_recv", lambda: next(it))
    monkeypatch.setattr(bridge, "_send", lambda step: sent.append(step))

    def _capture_write_config(*args):
        written["deployment"] = args[0]
        written["sandbox"] = args[6]

    monkeypatch.setattr(bridge, "write_config", _capture_write_config)
    bridge.run()
    return sent, written


def test_bridge_sets_docker_sandbox_when_docker_deployment_selected(monkeypatch):
    _, written = _run_bridge_with_answers(
        monkeypatch,
        ["", "docker (local container)", "Anthropic", "", "", "balanced"],
    )

    assert written["deployment"] == "docker"
    assert written["sandbox"]["backend"] == "docker"


def test_bridge_keeps_local_sandbox_for_non_docker_deployments(monkeypatch):
    _, written = _run_bridge_with_answers(
        monkeypatch,
        ["", "desktop (this computer)", "Anthropic", "", "", "balanced"],
    )

    assert written["deployment"] == "desktop"
    assert written["sandbox"]["backend"] == "local"
