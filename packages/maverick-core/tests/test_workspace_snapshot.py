"""Workspace snapshot / restore (ROADMAP 2028 H1)."""
from __future__ import annotations

import tarfile

import pytest
from maverick.workspace_snapshot import (
    create_snapshot,
    list_snapshots,
    restore_snapshot,
    workspace_snapshot,
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


class _Sandbox:
    def __init__(self, workdir):
        self.workdir = workdir


def test_tool_rejects_snapshot_path_outside_workspace(tmp_path, monkeypatch):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setattr(
        "maverick.workspace_snapshot.store_dir", lambda: tmp_path / "snaps")

    out = workspace_snapshot(_Sandbox(workdir)).fn({
        "op": "snapshot", "path": str(outside)})

    assert "escapes the workspace" in out
    assert not (tmp_path / "snaps").exists()


def test_tool_rejects_restore_dest_outside_workspace(tmp_path, monkeypatch):
    workdir = tmp_path / "workdir"
    src = _src(workdir)
    store = tmp_path / "snaps"
    create_snapshot(src, store)
    outside = tmp_path / "outside"
    monkeypatch.setattr("maverick.workspace_snapshot.store_dir", lambda: store)

    out = workspace_snapshot(_Sandbox(workdir)).fn({
        "op": "restore", "id": "snap-0001", "dest": str(outside)})

    assert "escapes the workspace" in out
    assert not outside.exists()


def test_tool_snapshots_and_restores_workspace_relative_paths(tmp_path, monkeypatch):
    workdir = tmp_path / "workdir"
    _src(workdir)
    store = tmp_path / "snaps"
    monkeypatch.setattr("maverick.workspace_snapshot.store_dir", lambda: store)
    tool = workspace_snapshot(_Sandbox(workdir))

    snap = tool.fn({"op": "snapshot", "path": "work"})
    restore = tool.fn({"op": "restore", "id": "snap-0001", "dest": "restored"})

    assert snap.startswith("created snap-0001")
    assert restore.startswith("restored 2 files")
    assert (workdir / "restored" / "a.txt").read_text(encoding="utf-8") == "alpha"
