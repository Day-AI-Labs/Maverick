"""WAL contention audit at N=16 (roadmap 2027-H1 performance).

The world model promises that one agent process plus a dashboard (and a
worker pool) can write concurrently: WAL journal mode + busy_timeout. This
audit pins that promise at N=16 concurrent writers — every write must land,
zero 'database is locked' errors — so a regression in the connection setup
(dropped busy_timeout, journal mode off) fails loudly here instead of as a
flaky 500 in production.

CI-sized: 16 threads x 20 writes each = 320 rows; runs in well under a second.
"""
from __future__ import annotations

import threading

from maverick.world_model import open_world

N_WRITERS = 16
WRITES_EACH = 20


def test_sixteen_concurrent_writers_no_lock_errors(tmp_path):
    db = tmp_path / "world.db"
    # Create the schema once before the writers race.
    w0 = open_world(db)
    goal_id = w0.create_goal("contention audit", "16 writers", owner="")

    errors: list[Exception] = []
    barrier = threading.Barrier(N_WRITERS)

    def writer(i: int) -> None:
        try:
            w = open_world(db)  # one connection per thread, like real workers
            barrier.wait()      # maximise overlap
            for j in range(WRITES_EACH):
                w.append_event(goal_id, f"writer-{i}", "audit", f"write={j}")
        except Exception as e:  # noqa: BLE001 -- the audit records ANY failure
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(N_WRITERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"concurrent writes failed: {errors[:3]}"
    events = [e for e in w0.goal_events(goal_id, limit=100_000) if e.kind == "audit"]
    assert len(events) == N_WRITERS * WRITES_EACH


def test_wal_mode_and_busy_timeout_are_set(tmp_path):
    """The two pragmas the audit depends on must stay on."""
    w = open_world(tmp_path / "world.db")
    journal = w.conn.execute("PRAGMA journal_mode").fetchone()[0]
    busy = w.conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert str(journal).lower() == "wal"
    assert int(busy) >= 1000, "busy_timeout too low for concurrent writers"
