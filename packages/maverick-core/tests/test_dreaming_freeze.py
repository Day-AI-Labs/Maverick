"""The calibration learning-freeze interlock must gate the dreaming
consolidation path (skills + insights), not just rehearse()."""
from __future__ import annotations

from maverick import dreaming, reflexion


class _Profile:
    def __init__(self, description=""):
        self.description = description
        self.persona = ""


PROFILES = {"finance_sox": _Profile("SOX ICFR control testing and reconciliation")}


def _two_clustered_failures(path):
    for goal in ("erp export timed out on batches", "erp export timed out in demo"):
        reflexion.record(goal_text=goal, failure_class="agent_error",
                         failure_msg="timeout", reflection="r",
                         domain="finance_sox", path=path)


def _run(tmp_path):
    return dreaming.dream_cycle(
        None, profiles=PROFILES, reflexion_path=tmp_path / "reflexions.ndjson",
        insights_path=tmp_path / "insights.ndjson",
        skill_store=tmp_path / "skills",
        skill_stats_path=tmp_path / "skill_stats.json",
    )


def test_unfrozen_consolidates_insights(tmp_path, monkeypatch):
    monkeypatch.setattr(dreaming, "settings", lambda: {"enable": True, "min_cluster": 2})
    monkeypatch.setattr("maverick.calibration.learning_frozen", lambda: False)
    _two_clustered_failures(tmp_path / "reflexions.ndjson")
    report = _run(tmp_path)
    assert report.learning_frozen is False
    assert report.insights_written >= 1   # baseline: it would learn


def test_frozen_verifier_blocks_consolidation(tmp_path, monkeypatch):
    # The headline interlock: a frozen (distrusted) verifier must stop the
    # consolidation that writes live, recallable behavior -- otherwise the
    # grader's drift gets baked into learned skills/insights.
    monkeypatch.setattr(dreaming, "settings", lambda: {"enable": True, "min_cluster": 2})
    monkeypatch.setattr("maverick.calibration.learning_frozen", lambda: True)
    _two_clustered_failures(tmp_path / "reflexions.ndjson")
    report = _run(tmp_path)
    assert report.learning_frozen is True
    assert report.insights_written == 0
    assert report.skills_distilled == 0
    assert dreaming.load_insights(tmp_path / "insights.ndjson") == []  # nothing written


def test_rollout_aborts_when_snapshot_raises(monkeypatch):
    # A pre-promotion snapshot failure must ABORT (no reliable rollback), not
    # proceed into a promotion that can't be cleanly undone.
    from maverick import learning_rollout as lr

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("maverick.dreaming.snapshot_learning_state", boom)
    constraint_calls = []

    def _constraint(cand, fraction):
        constraint_calls.append(fraction)
        return True, "ok"

    res = lr.promote_skill_live("skill-x", [_constraint])
    assert res.completed is False
    assert "aborted" in res.reason
    assert res.stages == []          # never reached the staged rollout
    assert constraint_calls == []    # and never deployed/checked
