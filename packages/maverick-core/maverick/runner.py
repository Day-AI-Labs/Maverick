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
import time
from typing import Any, Protocol

from ._envparse import env_float, env_int

log = logging.getLogger(__name__)

# Two-level fair concurrency so people don't wait behind each other:
#
#   * a per-PRINCIPAL lane (MAX_CONCURRENT_GOALS_PER_PRINCIPAL) — one user can
#     run several goals at once but cannot monopolise the host; and
#   * a global ceiling (MAX_CONCURRENT_GOALS) that only protects the box from
#     total overload. It is sized so normal multi-user load never reaches it,
#     so one user's runs do not block another's — only a host-wide saturation
#     queues anyone. Both are env-overridable.
#
# BoundedSemaphore(0) raises ValueError, so clamp to at least 1.
MAX_CONCURRENT_GOALS = max(1, env_int("MAVERICK_MAX_CONCURRENT_GOALS", 16))
MAX_CONCURRENT_GOALS_PER_PRINCIPAL = max(
    1, env_int("MAVERICK_MAX_CONCURRENT_GOALS_PER_PRINCIPAL", 3))
_run_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_GOALS)

# Per-principal lanes, created on first use. Guarded by _principal_sems_lock.
# The dict grows with the number of distinct principals seen this process — a
# bounded, small set in practice (one per user/agent), so no eviction needed.
_principal_sems: dict[str, threading.BoundedSemaphore] = {}
_principal_sems_lock = threading.Lock()
_ANON_PRINCIPAL = "_anonymous"


def _principal_semaphore(principal: str | None) -> threading.BoundedSemaphore:
    """The concurrency lane for ``principal`` (one shared lane for anon runs)."""
    key = principal or _ANON_PRINCIPAL
    with _principal_sems_lock:
        sem = _principal_sems.get(key)
        if sem is None:
            sem = threading.BoundedSemaphore(MAX_CONCURRENT_GOALS_PER_PRINCIPAL)
            _principal_sems[key] = sem
        return sem

# Cap how long a caller will block waiting for a concurrency slot. Without
# this, a single wedged goal holding a permit blocks the worker's loop
# thread forever (the daemon stops draining the queue entirely). On
# timeout we refuse the run and let the job queue retry later.
_ACQUIRE_TIMEOUT = env_float("MAVERICK_GOAL_ACQUIRE_TIMEOUT", 300.0)


def inflight_goals() -> int:
    """How many goals currently hold a concurrency slot (are running).

    Derived from the bounded semaphore's free permits; the same expression the
    dashboard's /healthz + /metrics gauges use."""
    return MAX_CONCURRENT_GOALS - _run_semaphore._value  # type: ignore[attr-defined]


def drain_inflight(timeout: float = 25.0, poll: float = 0.5) -> int:
    """Block until no goal holds a slot, or ``timeout`` elapses.

    For graceful shutdown: give running goals a bounded chance to finish before
    the worker process exits, instead of hard-killing them mid-LLM-call (which
    bills for work that is then discarded and can leave a goal wedged 'running').
    Returns the count still in-flight at return (0 = fully drained). Synchronous
    (polls the semaphore) -- call it off the event loop. Never raises."""
    deadline = time.monotonic() + max(0.0, timeout)
    while inflight_goals() > 0 and time.monotonic() < deadline:
        time.sleep(max(0.05, poll))
    return inflight_goals()


DEFAULT_MAX_DOLLARS = env_float("MAVERICK_DEFAULT_MAX_DOLLARS", 2.0)
DEFAULT_MAX_WALL_SECONDS = env_float("MAVERICK_DEFAULT_MAX_WALL_SECONDS", 1800.0)
DEFAULT_MAX_DEPTH = env_int("MAVERICK_DEFAULT_MAX_DEPTH", 3)


def run_goal_in_thread(
    goal_id: int,
    max_dollars: float | None = None,
    max_wall_seconds: float | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    *,
    channel: str | None = None,
    user_id: str | None = None,
    capability: Any | None = None,
    concurrency_principal: str | None = None,
) -> str | None:
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
    # Per-user lane first: bounds one caller's own fan-out without ever
    # blocking on another caller's runs.  Some execution identities (for
    # example fleet agent audit principals) are derived from user-controlled
    # objects, so callers may pass a separate stable authenticated principal
    # for scheduling while preserving ``user_id`` for audit/governance.
    lane_principal = concurrency_principal if concurrency_principal is not None else user_id
    principal_sem = _principal_semaphore(lane_principal)
    if not principal_sem.acquire(timeout=_ACQUIRE_TIMEOUT):
        log.error(
            "run_goal_in_thread: per-user concurrency cap (%d) reached within "
            "%.0fs (goal_id=%s, principal=%s); refusing run",
            MAX_CONCURRENT_GOALS_PER_PRINCIPAL, _ACQUIRE_TIMEOUT, goal_id, lane_principal,
        )
        return None
    # Global ceiling next: only a host-wide saturation makes anyone wait here.
    if not _run_semaphore.acquire(timeout=_ACQUIRE_TIMEOUT):
        principal_sem.release()
        log.error(
            "run_goal_in_thread: no global concurrency slot within %.0fs "
            "(goal_id=%s); refusing run", _ACQUIRE_TIMEOUT, goal_id,
        )
        return None
    world = None
    sandbox = None
    try:
        from .budget import budget_from_config
        from .llm import LLM
        from .orchestrator import run_goal_sync
        from .sandbox import build_sandbox
        from .world_model import open_world
        world = open_world()  # client/tenant-floored canonical world
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
        # Trace pinning: stamp the run with the workspace's git state so the
        # trace/replay ties to an exact commit. Best-effort, never blocks.
        from .trace_pin import pin_trace
        pin_trace(world, goal_id)
        try:
            run_goal_sync(
                llm, world, budget,
                goal_id, sandbox=sandbox, max_depth=max_depth,
                channel=channel, user_id=user_id, capability=capability,
                resume=True,
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
            # A genuine crash IS retryable -- return a distinct signal. An
            # intentional 'blocked' read back below (budget cap, killswitch
            # halt, awaiting-user) is TERMINAL and must not be re-run, or the
            # worker re-executes the whole swarm and re-spends budget.
            return "error"
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
        if sandbox is not None:
            close = getattr(sandbox, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:  # pragma: no cover
                    log.debug("run_goal_in_thread: sandbox.close() failed", exc_info=True)
        if world is not None:
            try:
                world.close()
            except Exception:  # pragma: no cover
                log.debug("run_goal_in_thread: world.close() failed", exc_info=True)
        # Release in reverse acquire order: global ceiling, then the user lane.
        _run_semaphore.release()
        principal_sem.release()


class Dispatcher(Protocol):
    """Where a goal runs. The seam between "execute in-process" (today) and a
    distributed task queue (arq / Celery / Temporal) later.

    ``submit`` runs a goal to completion and returns its terminal status string
    (or ``None`` if it could not start), the same contract as
    :func:`run_goal_in_thread`, so swapping the dispatcher never changes a
    caller's interface. A queue-backed implementation would enqueue the goal and
    wait on (or hand back) the result without callers noticing.
    """

    def submit(
        self,
        goal_id: int,
        *,
        max_dollars: float | None = None,
        max_wall_seconds: float | None = None,
        max_depth: int = DEFAULT_MAX_DEPTH,
        channel: str | None = None,
        user_id: str | None = None,
        capability: Any | None = None,
        concurrency_principal: str | None = None,
    ) -> str | None: ...


class LocalThreadDispatcher:
    """Default dispatcher: run the goal in-process under the concurrency
    semaphore (the current behaviour). Delegates to
    :func:`run_goal_in_thread` so there is exactly one execution path."""

    def submit(
        self,
        goal_id: int,
        *,
        max_dollars: float | None = None,
        max_wall_seconds: float | None = None,
        max_depth: int = DEFAULT_MAX_DEPTH,
        channel: str | None = None,
        user_id: str | None = None,
        capability: Any | None = None,
        concurrency_principal: str | None = None,
    ) -> str | None:
        return run_goal_in_thread(
            goal_id=goal_id, max_dollars=max_dollars,
            max_wall_seconds=max_wall_seconds, max_depth=max_depth,
            channel=channel, user_id=user_id, capability=capability,
            concurrency_principal=concurrency_principal,
        )


_dispatcher: Dispatcher = LocalThreadDispatcher()


def get_dispatcher() -> Dispatcher:
    """The active goal dispatcher (default: in-process thread execution)."""
    return _dispatcher


def set_dispatcher(dispatcher: Dispatcher) -> None:
    """Swap the goal dispatcher process-wide. The hook a queue/worker backend
    (arq / Celery / Temporal) installs at startup to move execution off the API
    process without touching any caller."""
    global _dispatcher
    _dispatcher = dispatcher


def run_goal_in_background(
    goal_id: int,
    max_dollars: float | None = None,
    max_wall_seconds: float | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    *,
    channel: str | None = None,
    user_id: str | None = None,
    capability: Any | None = None,
    concurrency_principal: str | None = None,
) -> str | None:
    """Dispatch a goal through the active :class:`Dispatcher`. Defaults to
    in-process thread execution; ``set_dispatcher`` swaps in a task queue
    without breaking callers (the contract is unchanged: returns the terminal
    status, or ``None`` if it could not start)."""
    return get_dispatcher().submit(
        goal_id, max_dollars=max_dollars,
        max_wall_seconds=max_wall_seconds, max_depth=max_depth,
        channel=channel, user_id=user_id, capability=capability,
        concurrency_principal=concurrency_principal,
    )
