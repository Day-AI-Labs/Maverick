"""Differential erasure verification: residual check + before/after proof."""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from maverick import erasure_verify
from maverick.cli import main
from maverick.world_model import WorldModel

# ---- differential (pure) ----

def test_differential_verified_when_after_clean_and_had_data():
    before = {"conversations": 1, "turns": 2, "goals": 1}
    after = {"conversations": 0, "turns": 0, "goals": 0}
    d = erasure_verify.differential(before, after)
    assert d["verified"] is True
    assert d["after_clean"] is True
    assert d["removed"]["turns"] == 2


def test_differential_not_verified_when_residual_remains():
    d = erasure_verify.differential({"turns": 2}, {"turns": 1})
    assert d["after_clean"] is False and d["verified"] is False
    assert d["removed"]["turns"] == 1


def test_differential_not_verified_when_nothing_to_remove():
    # after is clean but there was no data to begin with -> not a proof of erasure
    d = erasure_verify.differential({"turns": 0}, {"turns": 0})
    assert d["after_clean"] is True and d["verified"] is False


# ---- verify_erasure (over a monkeypatched export) ----

def test_verify_erasure_clean(monkeypatch):
    monkeypatch.setattr(
        "maverick.dsar.export_subject_data",
        lambda u, *, channel=None, tenant=None: {
            "subject": {"user_id": u, "channel": channel},
            "counts": {"conversations": 0, "turns": 0, "goals": 0,
                       "episodes": 0, "audit_events": 0},
        },
    )
    rep = erasure_verify.verify_erasure("alice", channel="telegram")
    assert rep["clean"] is True
    assert rep["residual"] == {}


def test_verify_erasure_dirty(monkeypatch):
    monkeypatch.setattr(
        "maverick.dsar.export_subject_data",
        lambda u, *, channel=None, tenant=None: {
            "subject": {"user_id": u, "channel": channel},
            "counts": {"conversations": 1, "turns": 3, "goals": 0},
        },
    )
    rep = erasure_verify.verify_erasure("alice", channel="telegram")
    assert rep["clean"] is False
    assert rep["residual"] == {"conversations": 1, "turns": 3}


# ---- real end-to-end: seed -> verify dirty -> erase -> verify clean ----

def _world_db() -> Path:
    return Path.home() / ".maverick" / "world.db"


def _seed():
    wm = WorldModel(_world_db())
    conv = wm.get_or_create_conversation("telegram", "alice")
    gid = wm.create_goal("alice's goal", "do the alice thing")
    wm.append_turn(conv.id, "user", "alice secret", goal_id=gid)
    wm.close()


def test_end_to_end_erase_then_verify_clean():
    _seed()
    before = erasure_verify.verify_erasure("alice", channel="telegram")
    assert before["clean"] is False  # residual present before erase

    res = CliRunner().invoke(
        main, ["erase", "--channel", "telegram", "--user", "alice", "--yes"])
    assert res.exit_code == 0

    after = erasure_verify.verify_erasure("alice", channel="telegram")
    assert after["clean"] is True  # nothing left

    proof = erasure_verify.differential(before["counts"], after["counts"])
    assert proof["verified"] is True


def test_cli_erase_verify_clean_exit_zero():
    # No data seeded for this subject -> CLEAN, exit 0.
    res = CliRunner().invoke(
        main, ["erase-verify", "--channel", "telegram", "--user", "nobody"])
    assert res.exit_code == 0
    assert "CLEAN" in res.output


def test_cli_erase_verify_residual_exit_one():
    _seed()
    res = CliRunner().invoke(
        main, ["erase-verify", "--channel", "telegram", "--user", "alice"])
    assert res.exit_code == 1
    assert "RESIDUAL DATA" in res.output


def test_verify_erasure_counts_user_scoped_facts():
    wm = WorldModel(_world_db())
    wm.upsert_fact("user:telegram:alice:preference", "alice secret PII")
    wm.upsert_fact("user:telegram:bob:preference", "bob secret PII")
    wm.upsert_fact("global:telegram:alice", "not deliberately scoped")
    wm.close()

    rep = erasure_verify.verify_erasure("alice", channel="telegram")

    assert rep["clean"] is False
    assert rep["counts"]["facts"] == 1
    assert rep["residual"]["facts"] == 1


def test_cli_erase_verify_json_residual_exit_one():
    _seed()
    res = CliRunner().invoke(
        main, ["erase-verify", "--channel", "telegram", "--user", "alice", "--json"])
    assert res.exit_code == 1
    assert '"clean": false' in res.output
