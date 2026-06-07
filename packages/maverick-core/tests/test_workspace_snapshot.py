"""Workspace snapshot / restore (ROADMAP 2028 H1)."""
from __future__ import annotations

import tarfile

import pytest
from maverick.workspace_snapshot import (
    create_snapshot,
    list_snapshots,
    restore_snapshot,
)


def _src(tmp_path):
    src = tmp_path / "work"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("alpha", encoding="utf-8")
    (src / "sub" / "b.txt").write_text("beta", encoding="utf-8")
    return src


def test_snapshot_then_restore_roundtrip(tmp_path):
    src = _src(tmp_path)
    store = tmp_path / "snaps"
    man = create_snapshot(src, store, label="before edit")
    assert man["id"] == "snap-0001"
    assert man["files"] == 2

    dest = tmp_path / "restored"
    res = restore_snapshot(store, "snap-0001", dest)
    assert res["restored"] == 2
    assert (dest / "a.txt").read_text(encoding="utf-8") == "alpha"
    assert (dest / "sub" / "b.txt").read_text(encoding="utf-8") == "beta"


def test_ids_increment_and_list_newest_first(tmp_path):
    src = _src(tmp_path)
    store = tmp_path / "snaps"
    create_snapshot(src, store, label="one")
    create_snapshot(src, store, label="two")
    snaps = list_snapshots(store)
    assert [s["id"] for s in snaps] == ["snap-0002", "snap-0001"]
    assert snaps[0]["label"] == "two"


def test_snapshot_rejects_missing_dir(tmp_path):
    with pytest.raises(ValueError):
        create_snapshot(tmp_path / "nope", tmp_path / "snaps")


def test_restore_unknown_id_errors(tmp_path):
    store = tmp_path / "snaps"
    store.mkdir()
    with pytest.raises(ValueError):
        restore_snapshot(store, "snap-0009", tmp_path / "out")


def test_restore_blocks_path_traversal(tmp_path):
    """A tarbomb member with ../ must not escape the destination."""
    store = tmp_path / "snaps"
    store.mkdir()
    evil = store / "snap-0001-evil.tar.gz"
    payload = tmp_path / "payload"
    payload.write_text("pwned", encoding="utf-8")
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(payload, arcname="../escape.txt")
    with pytest.raises(ValueError):
        restore_snapshot(store, "snap-0001", tmp_path / "dest")
    assert not (tmp_path / "escape.txt").exists()
