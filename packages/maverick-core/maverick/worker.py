"""Job-queue worker daemon.

Drains :class:`maverick.job_queue.JobQueue` by claiming pending jobs
and dispatching them to registered handlers. Designed for one or
more worker processes to share the same SQLite DB safely (claim is
atomic).

A handler is just a callable ``(job: Job) -> None``. Raise to fail;
return cleanly to succeed. The worker handles retry / terminal
failure / sleep-when-empty automatically.

Built-in handlers:
  - ``run_goal``  — payload {"goal_id": int} -> runs an EXISTING goal via
    maverick.runner.run_goal_in_thread (with a sync wait).
  - ``start_goal`` — payload {"text": str, "title"?: str} -> creates a FRESH
    goal from the prompt on each run, then runs it. This is the kind to pair
    with cron for a recurring autonomous task (``maverick schedule goal``).

Custom handlers are registered via :meth:`Worker.register`.

CLI entry: ``maverick worker [--db PATH] [--idle-sleep 2.0]``
(wired in cli.py when shipped; this module just exposes the loop).
"""
from __future__ import annotations

import logging
import signal
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from .job_queue import Job, JobQueue

log = logging.getLogger(__name__)


Handler = Callable[[Job], None]

# Job kinds the worker handles out of the box. Embedders add more at runtime
# via Worker.register(); this is the set the bare ``maverick worker`` knows.
# Exposed so ``maverick schedule add`` can warn on a likely-typo'd kind that
# would otherwise sit in the queue and fail terminally only at worker time.
BUILTIN_JOB_KINDS = frozenset({"run_goal", "start_goal"})


def _run_identity_kwargs(payload: dict) -> dict[str, str]:
    """Extract optional runner identity context from a queue payload."""
    run_kwargs: dict[str, str] = {}
    channel = str(payload.get("channel") or "").strip()
    user_id = str(payload.get("user_id") or "").strip()
    if channel:
        run_kwargs["channel"] = channel
    if user_id:
        run_kwargs["user_id"] = user_id
    return run_kwargs

class UnknownJobKind(Exception):
    """Raised when no handler is registered for a job.kind."""


class GoalRunFailed(Exception):
    """Raised by the built-in run_goal handler when the goal did not reach
    a successful terminal status, so run_once() routes it through the
    queue's retry/backoff path instead of marking the job done."""


class Worker:
    def __init__(
        self,
        queue: JobQueue | None = None,
        *,
        db_path: Path | None = None,
        idle_sleep: float = 2.0,
        max_attempts: int = 5,
        retry_after: float = 60.0,
        reclaim_lease: float = 3600.0,
    ) -> None:
        self.queue = queue or JobQueue(db_path=db_path)
        self.idle_sleep = float(idle_sleep)
        self.max_attempts = int(max_attempts)
        self.retry_after = float(retry_after)
        # Jobs stuck 'running' longer than this (a prior worker crashed
        # mid-job) are requeued on start. Keep it above the longest expected
        # job runtime so a live worker's in-flight job is never stolen.
        self.reclaim_lease = float(reclaim_lease)
        self._handlers: dict[str, Handler] = {}
        self._stop = threading.Event()
        self._install_builtin_handlers()

    def register(self, kind: str, handler: Handler) -> None:
        self._handlers[kind] = handler

    def _install_builtin_handlers(self) -> None:
        def _run_goal(job: Job) -> None:
            goal_id = job.payload.get("goal_id")
            if not goal_id:
                raise ValueError("run_goal payload requires goal_id")
            # Sync run so the queue waits before claiming the next job.
            from .runner import run_goal_in_thread
            status = run_goal_in_thread(int(goal_id), **_run_identity_kwargs(job.payload))
            # Retry only genuinely transient outcomes: couldn't start (None) or
            # an internal crash ('error'/'failed'). A goal that ended 'blocked'
            # is a DELIBERATE stop -- budget cap hit, killswitch armed, or
            # awaiting user input -- and must NOT be retried, or run_once()
            # re-executes the entire swarm and re-spends budget. Let those
            # complete the job normally.
            if status is None or status in ("error", "failed"):
                raise GoalRunFailed(
                    f"goal {goal_id} terminal status={status!r}"
                )
        self._handlers["run_goal"] = _run_goal

        def _start_goal(job: Job) -> None:
            # A recurring autonomous task creates a FRESH goal from the prompt
            # on every fire -- unlike run_goal, which re-runs one fixed goal_id
            # (re-executing the same world-model row). Pair with cron via
            # `maverick schedule goal "<cron>" "<prompt>"`; _maybe_rearm carries
            # the prompt forward in the payload so each occurrence is new.
            text = (job.payload.get("text") or "").strip()
            if not text:
                raise ValueError("start_goal payload requires non-empty 'text'")
            # Idempotent across retries: create the fresh goal only once, then
            # persist its id into the job payload. A retry of THIS job reuses it
            # (re-running the existing goal, like run_goal) instead of minting a
            # duplicate goal row on every transient failure. _maybe_rearm runs
            # before dispatch, so the next cron occurrence still gets the
            # original (goal_id-free) payload and creates its own fresh goal.
            goal_id = job.payload.get("goal_id")
            if not goal_id:
                title = (job.payload.get("title") or text).strip()[:80]
                from .world_model import open_world
                world = open_world()  # client/tenant-floored canonical world
                try:
                    owner = str(job.payload.get("owner") or "")
                    goal_id = world.create_goal(title, text, owner=owner)
                    # Provenance: link this run to its schedule so the dashboard
                    # Automations page can show the schedule's run history. Only
                    # on first creation (not retries, which reuse goal_id).
                    schedule_id = job.payload.get("schedule_id")
                    if schedule_id:
                        world.record_goal_origin(goal_id, "schedule", str(schedule_id))
                finally:
                    world.close()
                job.payload["goal_id"] = goal_id
                self.queue.set_payload(job.id, job.payload)
            # Same retry contract as run_goal: only transient outcomes requeue.
            from .runner import run_goal_in_thread
            status = run_goal_in_thread(int(goal_id), **_run_identity_kwargs(job.payload))
            if status is None or status in ("error", "failed"):
                raise GoalRunFailed(
                    f"scheduled goal {goal_id} terminal status={status!r}"
                )
        self._handlers["start_goal"] = _start_goal

    def stop(self) -> None:
        self._stop.set()

    def _dispatch(self, job: Job) -> None:
        handler = self._handlers.get(job.kind)
        if handler is None:
            raise UnknownJobKind(job.kind)
        handler(job)

    def _maybe_rearm(self, job: Job) -> None:
        """Re-arm a recurring (cron) job's next occurrence.

        ``maverick schedule add`` stores the cron expression in
        ``payload['__cron__']``. We re-arm on the FIRST claim only
        (``attempts == 1``) so a retry of a failed run doesn't enqueue
        duplicate future occurrences; the next occurrence is independent of
        this run's outcome, matching cron. Best-effort: a bad expression
        logs and is skipped rather than killing the worker.
        """
        if job.attempts != 1:
            return
        expr = job.payload.get("__cron__")
        if not expr:
            return
        try:
            from .scheduler import schedule_cron
            _jid, run_at = schedule_cron(self.queue, expr, job.kind, job.payload)
            log.info("worker: re-armed cron job kind=%s next=%.0f", job.kind, run_at)
        except Exception:
            log.exception("worker: failed to re-arm cron job %d (%r)", job.id, expr)

    def run_once(self, *, ready_at: float | None = None) -> bool:
        """Process at most one job. Returns True if a job ran.

        ``ready_at`` bounds which pending rows are considered ready. The
        daemon leaves it unset so each claim uses the current wall clock;
        one-shot drain mode passes its start time so jobs that become due
        while an earlier long-running handler executes wait for the next
        invocation.
        """
        job = self.queue.claim(ready_at=ready_at)
        if job is None:
            return False
        self._maybe_rearm(job)
        log.info("worker: claimed job %d kind=%s (attempt %d)",
                 job.id, job.kind, job.attempts)
        try:
            self._dispatch(job)
            self.queue.complete(job.id)
            log.info("worker: job %d done", job.id)
        except UnknownJobKind as e:
            # No retry — terminal.
            self.queue.fail(job.id, f"no handler for kind {e}",
                            retry_after=None, max_attempts=0)
            log.warning("worker: job %d has no handler (%s)", job.id, e)
        except Exception:
            err = traceback.format_exc(limit=4)
            self.queue.fail(
                job.id, err,
                retry_after=self.retry_after,
                max_attempts=self.max_attempts,
            )
            log.warning("worker: job %d failed, requeued: %s",
                        job.id, err.splitlines()[-1])
        return True

    def _reclaim_stale(self) -> None:
        """Requeue 'running' jobs orphaned by a crashed worker; log if any."""
        reclaimed = self.queue.reclaim_stale(
            self.reclaim_lease, max_attempts=self.max_attempts,
        )
        if reclaimed:
            log.info("worker: reclaimed %d stale job(s) from a prior crash",
                     reclaimed)

    def run_forever(self) -> None:
        """Loop until ``stop()`` is called or SIGTERM is received."""
        self._wire_signals()
        log.info("worker: started; polling %s every %.1fs",
                 self.queue.db_path, self.idle_sleep)
        # Recover jobs orphaned in 'running' by a previously-crashed worker
        # before draining the queue, so they aren't stuck forever.
        self._reclaim_stale()
        # ...then keep re-running it on an interval: claim() only ever picks
        # 'pending' rows, so a *peer* worker's hard crash (kill -9/OOM, which
        # skip run_once's except path) would otherwise leave its job stuck
        # 'running' until THIS daemon restarts -- which, for a long-lived
        # daemon in a multi-worker cluster, may be never. Re-reclaim every
        # reclaim_lease/2 so a still-running job is never stolen but a crashed
        # peer's orphan is recovered within ~one lease without a restart.
        reclaim_interval = max(self.reclaim_lease / 2.0, 1.0)
        last_reclaim = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_reclaim >= reclaim_interval:
                try:
                    self._reclaim_stale()
                except Exception:
                    log.exception("worker: periodic reclaim failed")
                last_reclaim = now
            ran = False
            try:
                ran = self.run_once()
            except Exception:
                log.exception("worker: unexpected error in loop")
            if not ran:
                # Idle: wait, but wake up cleanly on stop().
                self._stop.wait(self.idle_sleep)
        log.info("worker: stopped")

    def drain(self) -> int:
        """Run every currently-ready job, then return; for cron/systemd timers.

        Reclaims stale jobs once (like ``run_forever``), snapshots the
        drain start time, then processes only jobs whose ``run_at`` was ready
        at that moment. Re-armed cron occurrences, retries, or other jobs
        that become due while a long-running handler is executing wait for
        the next ``--once`` invocation.
        """
        reclaimed = self.queue.reclaim_stale(
            self.reclaim_lease, max_attempts=self.max_attempts,
        )
        if reclaimed:
            log.info("worker: reclaimed %d stale job(s) from a prior crash",
                     reclaimed)
        ready_at = time.time()
        count = 0
        while self.run_once(ready_at=ready_at):
            count += 1
        return count

    def _wire_signals(self) -> None:
        # Only wire signals from the main thread (signal.signal is
        # main-thread-only). Background callers (tests) skip cleanly.
        if threading.current_thread() is not threading.main_thread():
            return

        def _handler(signum, _frame):
            log.info("worker: signal %d -> shutdown", signum)
            self.stop()

        try:
            signal.signal(signal.SIGINT, _handler)
            signal.signal(signal.SIGTERM, _handler)
        except (ValueError, OSError):
            # Some hosts disallow signal.signal (e.g. embedded).
            pass


__all__ = ["Worker", "UnknownJobKind", "GoalRunFailed"]
