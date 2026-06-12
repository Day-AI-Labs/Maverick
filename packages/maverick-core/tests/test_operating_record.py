"""The Operating Record: decisions as a system of record + signed capsule."""
from __future__ import annotations

import pytest
from maverick import operating_record as orec
from maverick.world_model import WorldModel


@pytest.fixture()
def world(tmp_path):
    w = WorldModel(tmp_path / "w.db")
    gid = w.create_goal("Reconcile the quarterly ledger", domain="finance_sox")
    eid = w.start_episode(gid)
    w.end_episode(eid, "done", "success")
    w.set_goal_status(gid, "done", result="tied out")
    aid = w.create_approval("bank_transfer", risk="high",
                            detail="Q3 vendor batch")
    w.decide_approval(aid, "approved", decided_by="user:cfo")
    return w


def test_assemble_threads_goals_and_approvals(world):
    records = orec.assemble(world)
    kinds = {r.kind for r in records}
    assert kinds == {"goal", "approval"}
    goal = next(r for r in records if r.kind == "goal")
    assert goal.department == "finance_sox" and goal.outcome == "done"
    approval = next(r for r in records if r.kind == "approval")
    assert approval.decided_by == "user:cfo"
    s = orec.stats(records)
    assert s.n_goals == 1 and s.n_approvals == 1 and s.n_human_decisions == 1
    assert s.departments == {"finance_sox": 1}


def test_query_finds_every_decision_that_touched_x(world):
    records = orec.assemble(world)
    assert len(orec.query(records, text="ledger")) == 1
    assert len(orec.query(records, actor="user:cfo")) == 1
    assert orec.query(records, department="legal_x") == []


def test_capsule_roundtrip_and_tamper_detection(world, tmp_path, monkeypatch):
    pytest.importorskip("cryptography")
    import maverick.audit.signing as signing
    monkeypatch.setattr(signing, "KEY_DIR", tmp_path / "keys")
    out = orec.export_capsule(world, tmp_path / "mind.capsule.json", now=5.0)
    ok, reason = orec.verify_capsule(out)
    assert ok, reason
    # Tamper with one decision: the capsule must fail verification.
    text = out.read_text(encoding="utf-8").replace(
        "Reconcile the quarterly ledger", "Reconcile the doctored ledger")
    out.write_text(text, encoding="utf-8")
    ok, reason = orec.verify_capsule(out)
    assert not ok and "FAILED" in reason
