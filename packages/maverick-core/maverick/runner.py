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
import os
import threading

log = logging.getLogger(__name__)

# Process-wide concurrency cap. Override with MAVERICK_MAX_CONCURRENT_GOALS.
MAX_CONCURRENT_GOALS = int(os.environ.get("MAVERICK_MAX_CONCURRENT_GOALS", "3"))
_run_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_GOALS)


DEFAULT_MAX_DOLLARS = float(os.environ.get("MAVERICK_DEFAULT_MAX_DOLLARS", "2.0"))
DEFAULT_MAX_WALL_SECONDS = float(os.environ.get("MAVERICK_DEFAULT_MAX_WALL_SECONDS", "1800"))
DEFAULT_MAX_DEPTH = int(os.environ.get("MAVERICK_DEFAULT_MAX_DEPTH", "3"))


def run_goal_in_thread(
    goal_id: int,
    max_dollars: float = DEFAULT_MAX_DOLLARS,
    max_wall_seconds: float = DEFAULT_MAX_WALL_SECONDS,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> None:
    """Synchronously run a goal under the global concurrency semaphore.

    Designed to be passed to ``fastapi.BackgroundTasks.add_task`` or any
    threadpool. Acquires the semaphore (blocking if cap is reached),
    runs the swarm, releases the semaphore, and never re-raises -- the
    caller's API contract (return a goal id, poll for result) doesn't
    surface mid-run exceptions.

    Acquires a fresh WorldModel + LLM + Sandbox per call so each
    background goal gets its own connection (SQLite WAL + check_same_thread
    handles the concurrency).
    """
    _run_semaphore.acquire()
    try:
        from .budget import Budget
        from .llm import LLM
        from .orchestrator import run_goal_sync
        from .sandbox import build_sandbox
        from .world_model import DEFAULT_DB, WorldModel
        world = WorldModel(DEFAULT_DB)
        llm = LLM()
        sandbox = build_sandbox()
        run_goal_sync(
            llm, world,
            Budget(max_dollars=max_dollars, max_wall_seconds=max_wall_seconds),
            goal_id, sandbox=sandbox, max_depth=max_depth,
        )
    except Exception:
        log.exception("background goal run failed (goal_id=%s)", goal_id)
    finally:
        _run_semaphore.release()


def run_goal_in_background(
    goal_id: int,
    max_dollars: float = DEFAULT_MAX_DOLLARS,
    max_wall_seconds: float = DEFAULT_MAX_WALL_SECONDS,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> None:
    """Alias for run_goal_in_thread. Reserved for future change to a
    proper task queue (Celery / arq / RQ) without breaking callers."""
    return run_goal_in_thread(
        goal_id=goal_id, max_dollars=max_dollars,
        max_wall_seconds=max_wall_seconds, max_depth=max_depth,
    )
