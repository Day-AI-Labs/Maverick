"""The Cognitive Data Engine crank: one run_once pass triages, mines guardrails,
updates the registry, and reports the recoverable lift -- end to end.
"""
from __future__ import annotations

from maverick import data_engine_runner as der
from maverick import negative_knowledge as nk
from maverick.trajectory_store import TrajectoryStep


def _ep(eid, domain, tool, outcome):
    return [
        TrajectoryStep(ts=1.0, goal_id=1, episode_id=eid, step=0, role="coder",
                       tool=tool, domain=domain),
        TrajectoryStep(ts=1.0, goal_id=1, episode_id=eid, step=1, role="coder",
                       tool="log", domain=domain, is_final=True, outcome=outcome),
    ]


def _corpus():
    steps, eid = [], 0
    for domain in ("fin", "ops"):
        for _ in range(12):
            eid += 1
            steps += _ep(eid, domain, "X", 0.3)   # X causally harmful
        for _ in range(12):
            eid += 1
            steps += _ep(eid, domain, "read", 0.8)
    return steps


def test_run_once_turns_the_crank(tmp_path):
    reg = nk.GuardrailRegistry(path=tmp_path / "g.json")
    report = der.run_once(_corpus(), registry=reg)

    assert report.n_episodes == 48
    assert report.acted
    assert report.failure_classes[0].action == "X"
    assert [g.action for g in report.guardrails] == ["X"]
    assert report.predicted_lift > 0.3            # recovering ~the harm X causes
    # the crank's effect persisted: the registry now flags X
    assert reg.consult("X") is not None


def test_run_once_empty_corpus(tmp_path):
    reg = nk.GuardrailRegistry(path=tmp_path / "g.json")
    report = der.run_once([], registry=reg)
    assert report.n_episodes == 0 and not report.acted and report.predicted_lift == 0.0


def test_maybe_run_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("MAVERICK_DATA_ENGINE", raising=False)
    monkeypatch.setattr("maverick.config.get_data_engine", lambda: {"enable": False})
    report = der.maybe_run()
    assert report.n_episodes == 0 and not report.acted
