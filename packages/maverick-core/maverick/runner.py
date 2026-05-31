"""Background-task runner for goal execution.

Single source of truth for "start a goal in the background and run it to
completion." The dashboard's BackgroundTask, the REST API, the MCP
server's maverick_start tool, and any future channel adapter all funnel
through here.

Council-flagged: the previous implementation was duplicated across
``dashboard/app.py``, ``dashboard/api.py``, and ``mcp/server.py`` with
three different hardcoded budgets and divergent error handling.
Extracting once means every adapter inherits the same concurrency cap,
spend cap, error logging, and goal-status finalization.

Usage::

    from maverick.runner import run_goal_in_background, run_goal_in_thread

    run_goal_in_thread(goal_id=42, max_dollars=2.0)   # blocking, sync
    bg.add_task(run_goal_in_thread, goal_id=42)        # FastAPI BG task
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from ._envparse import env_float, env_int

log = logging.getLogger(__name__)

# Process-wide concurrency cap. Override with MAVERICK_MAX_CONCURRENT_GOALS.
# BoundedSemaphore(0) raises ValueError, so clamp to at least 1.
MAX_CONCURRENT_GOALS = max(1, env_int("MAVERICK_MAX_CONCURRENT_GOALS", 3))
_run_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_GOALS)

# Cap how long a caller will block waiting for a concurrency slot. Without
# this, a single wedged goal holding a permit blocks the worker's loop
# thread forever (the daemon stops draining the queue entirely). On
# timeout we refuse the run and let the job queue retry later.
_ACQUIRE_TIMEOUT = env_float("MAVERICK_GOAL_ACQUIRE_TIMEOUT", 300.0)


DEFAULT_MAX_DOLLARS = env_float("MAVERICK_DEFAULT_MAX_DOLLARS", 2.0)
DEFAULT_MAX_WALL_SECONDS = env_float("MAVERICK_DEFAULT_MAX_WALL_SECONDS", 1800.0)
DEFAULT_MAX_DEPTH = env_int("MAVERICK_DEFAULT_MAX_DEPTH", 3)


def run_goal_in_thread(
    goal_id: int,
    max_dollars: Optional[float] = None,
    max_wall_seconds: Optional[float] = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> Optional[str]:
    """Synchronously run a goal under the global concurrency semaphore.

    Designed to be passed to ``fastapi.BackgroundTasks.add_task`` or any
    threadpool. Acquires the semaphore (blocking up to
    ``_ACQUIRE_TIMEOUT`` if the cap is reached), runs the swarm, releases
    the semaphore, and never re-raises -- the FastAPI / channel callers'
    contract (return a goal id, poll for result) doesn't surface mid-run
    exceptions.

    Returns the goal's terminal status string (``"done"`` / ``"blocked"``
    / ...) so the worker daemon can decide whether the *job* succeeded:
    a goal that ends ``blocked``/``failed`` -- or ``None`` when the run
    could not even start (no slot) -- must surface as a job failure so the
    queue's retry/backoff actually runs. Polling callers ignore the value.

    Acquires a fresh WorldModel + LLM + Sandbox per call so each
    background goal gets its own connection (SQLite WAL + check_same_thread
    handles the concurrency), and always closes the WorldModel so the
    per-goal connection + WAL handle don't leak for the process lifetime.
    """
    if not _run_semaphore.acquire(timeout=_ACQUIRE_TIMEOUT):
        log.error(
            "run_goal_in_thread: no concurrency slot within %.0fs "
            "(goal_id=%s); refusing run", _ACQUIRE_TIMEOUT, goal_id,
        )
        return None
    world = None
    try:
        from .budget import budget_from_config
        from .llm import LLM
        from .orchestrator import run_goal_sync
        from .sandbox import build_sandbox
        from .world_model import DEFAULT_DB, open_world
        world = open_world(DEFAULT_DB)
        llm = LLM()
        sandbox = build_sandbox()
        # Precedence: explicit caller arg > [budget] config > the
        # background runner's conservative defaults (tighter than the
        # interactive Budget defaults on purpose).
        budget = budget_from_config(
            defaults={
                "max_dollars": DEFAULT_MAX_DOLLARS,
                "max_wall_seconds": DEFAULT_MAX_WALL_SECONDS,
            },
            max_dollars=max_dollars,
            max_wall_seconds=max_wall_seconds,
        )
        try:
            run_goal_sync(
                llm, world, budget,
                goal_id, sandbox=sandbox, max_depth=max_depth,
            )
        except Exception:
            # If the swarm raises an unexpected exception (anything not
            # caught by run_goal itself), the goal row is still 'active'.
            # Mark it 'blocked' so the dashboard doesn't show a ghost.
            log.exception("goal #%s crashed inside run_goal_sync", goal_id)
            try:
                world.set_goal_status(goal_id, "blocked", result="internal error")
            except Exception:  # pragma: no cover
                log.exception("failed to reclaim goal #%s after crash", goal_id)
        # Read back the terminal status so the worker can decide retry.
        try:
            g = world.get_goal(goal_id)
            return g.status if g else None
        except Exception:  # pragma: no cover
            log.exception("run_goal_in_thread: status read-back failed (goal_id=%s)", goal_id)
            return None
    except Exception:
        log.exception("background goal run failed (goal_id=%s)", goal_id)
        return None
    finally:
        if world is not None:
            try:
                world.close()
            except Exception:  # pragma: no cover
                log.debug("run_goal_in_thread: world.close() failed", exc_info=True)
        _run_semaphore.release()


def run_goal_in_background(
    goal_id: int,
    max_dollars: Optional[float] = None,
    max_wall_seconds: Optional[float] = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> Optional[str]:
    """Alias for run_goal_in_thread. Reserved for future change to a
    proper task queue (Celery / arq / RQ) without breaking callers."""
    return run_goal_in_thread(
        goal_id=goal_id, max_dollars=max_dollars,
        max_wall_seconds=max_wall_seconds, max_depth=max_depth,
    )
