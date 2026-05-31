"""Concurrent WorldModel opens must not raise 'database is locked'.

The dashboard and the agent each open their own connection to the same world
DB. Switching the journal mode to WAL needs a brief exclusive lock, so two
connections opening at the same instant raced and the loser raised
``OperationalError("database is locked")`` -- the root cause of the
intermittent consent-test CI flake (a background thread opened a second
connection). ``__init__`` now arms ``busy_timeout`` before the WAL switch and
retries the switch on a transient lock; these hammer that path with a barrier
so all threads open simultaneously.
"""
import threading

from maverick.world_model import WorldModel


def _hammer_opens(db, n: int) -> list[Exception]:
    barrier = threading.Barrier(n)
    errors: list[Exception] = []

    def _open():
        try:
            barrier.wait()  # release all threads at once -> maximal contention
            wm = WorldModel(path=db)
            wm.conn.execute("SELECT 1").fetchone()  # connection is usable
            wm.close()
        except Exception as e:  # pragma: no cover - only fires on regression
            errors.append(e)

    threads = [threading.Thread(target=_open) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return errors


def test_many_concurrent_opens_never_lock(tmp_path):
    db = tmp_path / "world.db"
    WorldModel(path=db).close()  # seed file + schema, then hammer re-opens
    errors = _hammer_opens(db, 24)
    assert not errors, f"concurrent opens raised: {errors[:3]}"


def test_concurrent_first_open_of_fresh_db(tmp_path):
    """Even with no pre-existing file, concurrent first-opens must not lock."""
    errors = _hammer_opens(tmp_path / "fresh.db", 16)
    assert not errors, f"concurrent first-opens raised: {errors[:3]}"
