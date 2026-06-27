"""Regression for the job-queue lease-steal terminal-write clobber (finding c1).

A slow worker can have its 'running' job reclaimed (reclaim_stale) and re-claimed
by a peer, which bumps `attempts`. Without a fence, the original worker's
complete()/fail() clobbers the job the new owner is running. complete()/fail()
now take `expected_attempts` and no-op when the attempt count has moved on.
"""
import tempfile
from pathlib import Path

from maverick.job_queue import JobQueue


def _q():
    d = tempfile.mkdtemp()
    return JobQueue(db_path=Path(d) / "jobs.db")


def test_stale_complete_does_not_clobber_reclaimed_job():
    q = _q()
    q.enqueue("k", {"x": 1})
    a = q.claim()                  # worker A, attempts=1
    q.reclaim_stale(0)             # lease expires -> back to pending
    b = q.claim()                  # worker B re-claims, attempts=2
    assert a.attempts != b.attempts
    # A finished late; its fenced completion must be rejected.
    assert q.complete(a.id, expected_attempts=a.attempts) is False
    # B, the current owner, completes successfully.
    assert q.complete(b.id, expected_attempts=b.attempts) is True


def test_stale_fail_does_not_reschedule_reclaimed_job():
    q = _q()
    q.enqueue("k", {})
    a = q.claim()
    q.reclaim_stale(0)
    b = q.claim()
    assert q.fail(a.id, "boom", expected_attempts=a.attempts) is False
    assert q.fail(b.id, "boom", expected_attempts=b.attempts) is True


def test_fence_is_opt_in_unfenced_callers_unaffected():
    q = _q()
    q.enqueue("k", {})
    a = q.claim()
    # No expected_attempts -> legacy behaviour (completes regardless).
    assert q.complete(a.id) is True
