"""Per-thread WAL reader connections: concurrent reads run off the write lock,
the writer thread still sees its own uncommitted rows, and :memory: (which is
per-connection) keeps using the shared connection."""
from __future__ import annotations

import threading

from maverick.world_model import WorldModel


def test_reader_used_for_file_db(tmp_path):
    w = WorldModel(tmp_path / "w.db")
    try:
        gid = w.create_goal("t", "d")
        # A plain read (different "thread context" not required) goes via a
        # reader connection, distinct from the write connection.
        assert w._reader() is not None
        assert w._reader() is not w.conn
        assert w.get_goal(gid).id == gid
    finally:
        w.close()


def test_writer_thread_sees_own_uncommitted_rows(tmp_path):
    w = WorldModel(tmp_path / "w.db")
    try:
        gid = w.create_goal("t", "d")
        with w._writing() as c:
            c.execute("UPDATE goals SET status='mid' WHERE id=?", (gid,))
            # Mid-transaction read on the writer thread must see the uncommitted
            # value -> served from the write connection, not a reader snapshot.
            row = w._read_one("SELECT status FROM goals WHERE id=?", (gid,))
            assert row["status"] == "mid"
    finally:
        w.close()


def test_concurrent_reads_during_writes(tmp_path):
    w = WorldModel(tmp_path / "w.db")
    gid = w.create_goal("t", "d")
    errors: list[Exception] = []
    stop = threading.Event()

    def reader():
        try:
            while not stop.is_set():
                w.get_goal(gid)
                w.list_goals(limit=10)
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for i in range(200):
            w.append_event(gid, "a", "k", f"event-{i}")
    finally:
        stop.set()
        for t in threads:
            t.join(5)
    assert not errors, errors
    assert len(w.goal_events(gid)) >= 1
    w.close()


def test_close_shuts_reader_connections(tmp_path):
    w = WorldModel(tmp_path / "w.db")
    w.create_goal("t", "d")
    w.list_goals()  # open a reader on this thread
    assert w._reader_conns  # at least one reader registered
    w.close()
    assert w._reader_conns == []  # drained + closed
