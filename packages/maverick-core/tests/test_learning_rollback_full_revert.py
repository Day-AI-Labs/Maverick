"""Round-2 regression: learning rollback must be a FULL revert.

A store that did not exist at snapshot time but was created during the cycle
(e.g. the first-ever insights file / learned-skills dir on a fresh tenant) must
be deleted on rollback -- otherwise newly-created (possibly poisoned) learning
survives a rollback that is supposed to leave state "fully restored or unchanged".
"""
from __future__ import annotations

from maverick import dreaming


def _stores(tmp):
    return {
        "pre_existing.ndjson": tmp / "pre_existing.ndjson",   # exists at snapshot
        "created_after.ndjson": tmp / "created_after.ndjson",  # created post-snapshot
        "learned-skills": tmp / "learned-skills",              # dir, created after
    }


def test_rollback_deletes_stores_created_after_snapshot(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    snaps = tmp_path / "snaps"
    stores = _stores(live)

    # Snapshot time: only the pre-existing store exists.
    stores["pre_existing.ndjson"].write_text("v1\n", encoding="utf-8")
    snap = dreaming.snapshot_learning_state(directory=snaps, stores=stores)
    assert snap is not None

    # During the "cycle": mutate the existing store AND create new ones.
    stores["pre_existing.ndjson"].write_text("v1\nMUTATED\n", encoding="utf-8")
    stores["created_after.ndjson"].write_text("poisoned insight\n", encoding="utf-8")
    skills = stores["learned-skills"]
    skills.mkdir()
    (skills / "bad-skill.md").write_text("learned during cycle\n", encoding="utf-8")

    restored = dreaming.rollback_learning_state(
        "latest", directory=snaps, stores=stores)

    # Pre-existing store reverted to snapshot content.
    assert stores["pre_existing.ndjson"].read_text(encoding="utf-8") == "v1\n"
    # Post-snapshot creations are GONE (the bug: they survived).
    assert not stores["created_after.ndjson"].exists()
    assert not skills.exists()
    assert "created_after.ndjson" in restored and "learned-skills" in restored


def test_rollback_noop_when_nothing_created_after(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    snaps = tmp_path / "snaps"
    stores = {"a.ndjson": live / "a.ndjson"}
    stores["a.ndjson"].write_text("orig\n", encoding="utf-8")
    dreaming.snapshot_learning_state(directory=snaps, stores=stores)
    stores["a.ndjson"].write_text("changed\n", encoding="utf-8")
    dreaming.rollback_learning_state("latest", directory=snaps, stores=stores)
    assert stores["a.ndjson"].read_text(encoding="utf-8") == "orig\n"
