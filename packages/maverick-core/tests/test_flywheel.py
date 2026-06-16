"""The flywheel: one grounded pass triages, guards, consolidates, and discovers
-- every engine turning together."""
from __future__ import annotations

from maverick import consequence as cq
from maverick import flywheel
from maverick import negative_knowledge as nk
from maverick import procedural_memory as pm
from maverick.counterfactual_rollout import Transition, TransitionModel
from maverick.trajectory_store import TrajectoryStep


def _ep(eid, domain, tool, outcome):
    return [
        TrajectoryStep(ts=1.0, goal_id=1, episode_id=eid, step=0, role="coder",
                       tool=tool, domain=domain),
        TrajectoryStep(ts=1.0, goal_id=1, episode_id=eid, step=1, role="coder",
                       tool="log", domain=domain, is_final=True, outcome=outcome),
    ]


def _corpus():
    # X is causally harmful (0.2), Y causally beneficial (0.9), in both domains.
    steps, eid = [], 0
    for domain in ("fin", "ops"):
        for _ in range(12):
            eid += 1
            steps += _ep(eid, domain, "X", 0.2)
        for _ in range(12):
            eid += 1
            steps += _ep(eid, domain, "Y", 0.9)
    return steps


def test_run_once_turns_every_engine(tmp_path):
    rails = nk.GuardrailRegistry(path=tmp_path / "g.json")
    mem = pm.MemoryStore(path=tmp_path / "m.json")
    rep = flywheel.run_once(_corpus(), guardrails=rails, memory=mem)

    assert rep.n_episodes == 48 and rep.acted
    assert [g.action for g in rep.guardrails] == ["X"]          # guard: harmful X
    assert [m.action for m in rep.memories] == ["Y"]            # remember: beneficial Y
    assert rep.hypotheses and rep.hypotheses[0].baseline_action == "X"
    assert rep.hypotheses[0].candidate_action == "Y"            # discover: swap X -> Y
    assert rep.predicted_lift > 0.5
    # registries persisted
    assert rails.consult("X") is not None and mem.strength_of("Y") > 0


def test_run_once_simulates_when_world_model_supplied(tmp_path):
    START, GOOD, BAD = ("start",), ("good",), ("bad",)
    wm = TransitionModel().fit(
        [Transition(START, "Y", GOOD)] * 12 + [Transition(GOOD, "go", None, 1.0)] * 12
        + [Transition(START, "X", BAD)] * 12 + [Transition(BAD, "go", None, 0.0)] * 12
    )
    rep = flywheel.run_once(
        _corpus(), guardrails=nk.GuardrailRegistry(path=tmp_path / "g.json"),
        memory=pm.MemoryStore(path=tmp_path / "m.json"),
        world_model=wm, start_states=[START])
    assert rep.simulations
    assert rep.simulations[0].sim_lift > 0 and rep.simulations[0].worth_experimenting


def test_grounded_outcome_prefers_reality(tmp_path, monkeypatch):
    store = cq.ConsequenceStore(path=tmp_path / "c.ndjson")
    store.record(1, 7, 1.0)  # reality: this episode actually succeeded
    monkeypatch.setattr("maverick.consequence.shared", lambda: store)
    monkeypatch.setenv("MAVERICK_CONSEQUENCE", "1")

    of = flywheel.grounded_outcome_fn()
    ep = _ep(7, "fin", "X", 0.2)   # proxy says 0.2, reality says 1.0
    assert of(ep) == 1.0


def test_maybe_run_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("MAVERICK_DATA_ENGINE", raising=False)
    monkeypatch.setattr("maverick.config.get_data_engine", lambda: {"enable": False})
    rep = flywheel.maybe_run()
    assert rep.n_episodes == 0 and not rep.acted
