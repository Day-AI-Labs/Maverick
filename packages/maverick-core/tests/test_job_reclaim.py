"""Stale-job recovery for the persistent JobQueue.

A worker that claims a job and then dies hard (OOM / kill -9 / segfault)
never runs ``complete()`` or ``fail()``, so the row is stranded in
'running' forever -- ``claim()`` only ever picks 'pending' rows. The
``reclaim_stale`` helper (run on worker start) returns such jobs to the
queue, with a poison-pill cap so a job that keeps crashing the process is
eventually failed rather than requeued forever.
"""
from __future__ import annotations


def _running_job(q, *, at: float, attempts_via_claim: int = 1) -> int:
    """Enqueue a job and drive it into 'running' deterministically at time ``at``."""
    jid = q.enqueue("noop", {}, run_at=at)
    job = q.claim(now=at)
    assert job is not None and job.id == jid
    assert job.status == "running" and job.attempts == attempts_via_claim
    return jid


def test_reclaim_stale_requeues_orphaned_running(tmp_path):
    from maverick.job_queue import JobQueue
    q = JobQueue(db_path=tmp_path / "jobs.db")
    jid = _running_job(q, at=1000.0)

    # Lease of 100s; "now" is 200s after the claim -> well past the lease.
    moved = q.reclaim_stale(100.0, now=1200.0)
    assert moved == 1

    job = q.get(jid)
    assert job.status == "pending"
    assert job.attempts == 1  # preserved, not reset

    # And it is claimable again.
    again = q.claim(now=1300.0)
    assert again is not None and again.id == jid
    assert again.attempts == 2


def test_reclaim_stale_leaves_fresh_running_alone(tmp_path):
    from maverick.job_queue import JobQueue
    q = JobQueue(db_path=tmp_path / "jobs.db")
    jid = _running_job(q, at=1000.0)

    # Lease of 1000s; only 10s elapsed -> still within lease, untouched.
    moved = q.reclaim_stale(1000.0, now=1010.0)
    assert moved == 0
    assert q.get(jid).status == "running"


def test_reclaim_stale_fails_poison_job_at_max_attempts(tmp_path):
    from maverick.job_queue import JobQueue
    q = JobQueue(db_path=tmp_path / "jobs.db")
    # One claim -> attempts == 1; with max_attempts=1 it's already spent.
    jid = _running_job(q, at=1000.0)

    moved = q.reclaim_stale(100.0, now=1200.0, max_attempts=1)
    assert moved == 1
    job = q.get(jid)
    assert job.status == "failed"  # terminal, not requeued
    assert "lease expired" in job.last_error


def test_worker_reclaims_stale_jobs_on_start(tmp_path):
    """run_forever recovers a prior crash's orphaned job before draining."""
    from maverick.job_queue import JobQueue
    from maverick.worker import Worker

    q = JobQueue(db_path=tmp_path / "jobs.db")
    # updated_at is set to this ancient timestamp, so against real wall-clock
    # "now" the job is far past any small lease.
    jid = _running_job(q, at=1000.0)

    w = Worker(queue=q, reclaim_lease=1.0, idle_sleep=0.0)
    w.stop()  # ensure the drain loop exits immediately after the reclaim
    w.run_forever()

    assert q.get(jid).status == "pending"
