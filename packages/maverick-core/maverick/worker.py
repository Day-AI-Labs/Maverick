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
from pathlib import Path
from typing import Callable, Optional

from .job_queue import Job, JobQueue

log = logging.getLogger(__name__)


Handler = Callable[[Job], None]


class UnknownJobKind(Exception):
    """Raised when no handler is registered for a job.kind."""


class Worker:
    def __init__(
        self,
        queue: Optional[JobQueue] = None,
        *,
        db_path: Optional[Path] = None,
        idle_sleep: float = 2.0,
        max_attempts: int = 5,
        retry_after: float = 60.0,
    ) -> None:
        self.queue = queue or JobQueue(db_path=db_path)
        self.idle_sleep = float(idle_sleep)
        self.max_attempts = int(max_attempts)
        self.retry_after = float(retry_after)
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
            # Sync wait so the queue waits before claiming the next job.
            from .runner import run_goal_in_thread
            t = run_goal_in_thread(int(goal_id))
            if hasattr(t, "join"):
                t.join()
        self._handlers["run_goal"] = _run_goal

    def stop(self) -> None:
        self._stop.set()

    def _dispatch(self, job: Job) -> None:
        handler = self._handlers.get(job.kind)
        if handler is None:
            raise UnknownJobKind(job.kind)
        handler(job)

    def run_once(self) -> bool:
        """Process at most one job. Returns True if a job ran."""
        job = self.queue.claim()
        if job is None:
            return False
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


__all__ = ["Worker", "UnknownJobKind"]
