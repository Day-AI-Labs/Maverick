"""Governed rollout of learning: staged promotion with auto-rollback."""
from __future__ import annotations

from maverick.learning_rollout import (
    DEFAULT_STAGES,
    Stage,
    run_rollout,
    threshold_constraint,
)


def _recorder():
    deployed: list = []
    rolled: list = []
    return deployed, rolled, (lambda c, f: deployed.append((c, f))), (lambda c: rolled.append(c))


def test_all_constraints_pass_completes_full_rollout():
    deployed, rolled, deploy, rollback = _recorder()
    ok = threshold_constraint("win_rate", lambda c, f: 0.9, floor=0.8)
    res = run_rollout("skill-x", DEFAULT_STAGES, [ok], deploy=deploy, rollback=rollback)
    assert res.completed and not res.rolled_back
    assert res.reached_fraction == 1.0
    assert [f for _c, f in deployed] == [0.1, 0.5, 1.0]   # canary -> half -> full
    assert rolled == []


def test_failing_constraint_auto_rolls_back_and_stops():
    deployed, rolled, deploy, rollback = _recorder()
    # win-rate collapses once past the canary (fraction > 0.1)
    def metric(c, f):
        return 0.9 if f <= 0.1 else 0.4
    res = run_rollout("skill-x", DEFAULT_STAGES,
                      [threshold_constraint("win_rate", metric, floor=0.8)],
                      deploy=deploy, rollback=rollback)
    assert res.rolled_back and not res.completed
    assert "win_rate" in res.reason
    assert res.reached_fraction == 0.1                 # only the canary stuck
    assert [f for _c, f in deployed] == [0.1, 0.5]     # deployed canary + half, then stopped
    assert rolled == ["skill-x"]                       # rolled back exactly once


def test_canary_failure_rolls_back_immediately():
    deployed, rolled, deploy, rollback = _recorder()
    res = run_rollout("bad", [Stage("canary", 0.1)],
                      [threshold_constraint("health", lambda c, f: 0.0, floor=0.5)],
                      deploy=deploy, rollback=rollback)
    assert res.rolled_back and res.reached_fraction == 0.0
    assert [f for _c, f in deployed] == [0.1] and rolled == ["bad"]


def test_a_constraint_that_errors_is_treated_as_failing():
    deployed, rolled, deploy, rollback = _recorder()
    def boom(c, f):
        raise RuntimeError("eval harness down")
    res = run_rollout("x", DEFAULT_STAGES, [boom], deploy=deploy, rollback=rollback)
    assert res.rolled_back and "error" in res.reason
    assert rolled == ["x"]


def test_promote_skill_live_audits_each_stage_and_completes(monkeypatch):
    # Exercises the previously-untested live wiring: snapshot once, audit a
    # LEARNING_UPDATE per stage (the call that was silently wrong), no rollback.
    from maverick import learning_rollout as lr
    calls = {"snapshot": 0, "audit": []}
    monkeypatch.setattr("maverick.dreaming.snapshot_learning_state",
                        lambda *a, **k: calls.__setitem__("snapshot", calls["snapshot"] + 1))
    monkeypatch.setattr("maverick.dreaming.rollback_learning_state",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not roll back")))
    monkeypatch.setattr("maverick.audit.record",
                        lambda kind, **payload: calls["audit"].append((kind, payload)))
    ok = lr.threshold_constraint("h", lambda c, f: 1.0, floor=0.5)
    res = lr.promote_skill_live("sk", [ok],
                                stages=[lr.Stage("canary", 0.1), lr.Stage("full", 1.0)])
    from maverick.audit import EventKind
    assert res.completed and calls["snapshot"] == 1
    assert len(calls["audit"]) == 2
    assert all(k == EventKind.LEARNING_UPDATE for k, _ in calls["audit"])
    assert calls["audit"][0][1]["candidate"] == "sk"


def test_promote_skill_live_rolls_back_on_failure(monkeypatch):
    from maverick import learning_rollout as lr
    rolled = []
    monkeypatch.setattr("maverick.dreaming.snapshot_learning_state", lambda *a, **k: None)
    monkeypatch.setattr("maverick.dreaming.rollback_learning_state", lambda *a, **k: rolled.append(1))
    monkeypatch.setattr("maverick.audit.record", lambda *a, **k: None)
    bad = lr.threshold_constraint("h", lambda c, f: 0.0, floor=0.5)
    res = lr.promote_skill_live("sk", [bad], stages=[lr.Stage("canary", 0.1)])
    assert res.rolled_back and rolled == [1]
