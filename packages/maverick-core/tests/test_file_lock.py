"""Shared cross-process lock + atomic write helper (maverick.file_lock).

These back the file-race fixes across the state stores: atomic_write_text must
never leave a torn file for a concurrent reader, and cross_process_lock must
serialize a read-modify-write so concurrent writers don't lose updates.
"""
from __future__ import annotations

import json
import os
import threading

from maverick.file_lock import atomic_write_text, cross_process_lock


def test_atomic_write_replaces_whole_file(tmp_path):
    p = tmp_path / "s.json"
    atomic_write_text(p, json.dumps({"a": 1}))
    assert json.loads(p.read_text()) == {"a": 1}
    atomic_write_text(p, json.dumps({"a": 2}))
    assert json.loads(p.read_text()) == {"a": 2}


def test_atomic_write_creates_parent_dirs(tmp_path):
    p = tmp_path / "nested" / "deep" / "s.txt"
    atomic_write_text(p, "hello")
    assert p.read_text() == "hello"


def test_atomic_write_sets_mode_0600(tmp_path):
    p = tmp_path / "s.txt"
    atomic_write_text(p, "x")
    assert (p.stat().st_mode & 0o777) == 0o600


def test_atomic_write_leaves_no_temp_files(tmp_path):
    p = tmp_path / "s.txt"
    atomic_write_text(p, "x")
    # Only the target file remains -- the unique temp was replaced into place.
    assert [f.name for f in tmp_path.iterdir()] == ["s.txt"]


def test_atomic_write_no_torn_read_under_concurrency(tmp_path):
    p = tmp_path / "s.json"
    atomic_write_text(p, json.dumps({"n": 0}))
    errors: list[Exception] = []
    stop = threading.Event()

    def writer():
        for i in range(300):
            atomic_write_text(p, json.dumps({"n": i, "pad": "y" * 200}))

    def reader():
        while not stop.is_set():
            try:
                json.loads(p.read_text())
            except (ValueError, OSError) as e:
                errors.append(e)

    rt = threading.Thread(target=reader)
    wt = threading.Thread(target=writer)
    rt.start()
    wt.start()
    wt.join()
    stop.set()
    rt.join()
    assert not errors, errors[:3]


def test_cross_process_lock_serializes_writers(tmp_path):
    """The lock must serialize a load-modify-save so concurrent increments of a
    shared counter don't lose updates."""
    p = tmp_path / "counter.json"
    atomic_write_text(p, json.dumps({"c": 0}))
    n, per = 12, 50

    def worker():
        for _ in range(per):
            with cross_process_lock(p):
                cur = json.loads(p.read_text())["c"]
                atomic_write_text(p, json.dumps({"c": cur + 1}))

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert json.loads(p.read_text())["c"] == n * per


def test_cross_process_lock_creates_sidecar(tmp_path):
    p = tmp_path / "x.json"
    with cross_process_lock(p):
        pass
    assert (tmp_path / "x.json.lock").exists()
    # The lock sidecar is separate from the target (os.replace swaps the inode).
    assert not p.exists()


def test_cross_process_lock_degrades_when_dir_unwritable(tmp_path):
    # An impossible lock dir must not raise -- the manager yields best-effort.
    bogus = tmp_path / "missing-parent-file" / "child.json"
    # Create a *file* where a directory is expected so mkdir/open fail.
    (tmp_path / "missing-parent-file").write_text("not a dir")
    with cross_process_lock(bogus):
        pass  # must reach here without raising
    assert not os.path.exists(str(bogus) + ".lock")
