"""Job-queue worker daemon.

Drains :class:`maverick.job_queue.JobQueue` by claiming pending jobs
and dispatching them to registered handlers. Designed for one or
more worker processes to share the same SQLite DB safely (claim is
atomic).

A handler is just a callable ``(job: Job) -> None``. Raise to fail;
return cleanly to succeed. The worker handles retry / terminal
failure / sleep-when-empty automatically.

Built-in handlers:
  - ``run_goal``  — payload {"goal_id": int} -> runs the goal via
    maverick.runner.run_goal_in_thread (with a sync wait).

Custom handlers are registered via :meth:`Worker.register`.

CLI entry: ``maverick worker [--db PATH] [--idle-sleep 2.0]``
(wired in cli.py when shipped; this module just exposes the loop).
"""
from __future__ import annotations

import logging
import signal
import threading
import traceback
from collections.abc import Callable
from pathlib import Path

from .job_queue import Job, JobQueue

log = logging.getLogger(__name__)


Handler = Callable[[Job], None]


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
            status = run_goal_in_thread(int(goal_id))
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

    def run_once(self) -> bool:
        """Process at most one job. Returns True if a job ran."""
        job = self.queue.claim()
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

    def run_forever(self) -> None:
        """Loop until ``stop()`` is called or SIGTERM is received."""
        self._wire_signals()
        log.info("worker: started; polling %s every %.1fs",
                 self.queue.db_path, self.idle_sleep)
        # Recover jobs orphaned in 'running' by a previously-crashed worker
        # before draining the queue, so they aren't stuck forever.
        reclaimed = self.queue.reclaim_stale(
            self.reclaim_lease, max_attempts=self.max_attempts,
        )
        if reclaimed:
            log.info("worker: reclaimed %d stale job(s) from a prior crash",
                     reclaimed)
        while not self._stop.is_set():
            ran = False
            try:
                ran = self.run_once()
            except Exception:
                log.exception("worker: unexpected error in loop")
            if not ran:
                # Idle: wait, but wake up cleanly on stop().
                self._stop.wait(self.idle_sleep)
        log.info("worker: stopped")

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
