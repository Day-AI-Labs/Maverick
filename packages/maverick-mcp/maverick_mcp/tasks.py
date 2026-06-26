"""MCP Tasks (spec 2025-11-25, experimental): async, pollable tool execution.

A task-augmented ``tools/call`` returns a ``CreateTaskResult`` immediately and
runs the tool on a background worker; the requestor polls ``tasks/get`` and
retrieves the result via ``tasks/result`` once terminal. This lets a long
``maverick_start`` run without wedging the single stdio loop — the client can
poll, cancel, or call other tools while the swarm works.

Scope of this module: the basic lifecycle (``working`` → ``completed`` /
``failed`` / ``cancelled``, plus ``get`` / ``result`` / ``list`` / ``cancel``).
The optional ``input_required`` status (task-driven elicitation) and
``notifications/tasks/status`` push are deferred — requestors poll, which the
spec requires them to support regardless.

The store is transport/server-agnostic: it's handed a ``runner`` that turns a
``(tool_name, arguments)`` pair into a ``CallToolResult`` dict, so it unit-tests
without a real server or LLM. ``server.py`` supplies a runner that executes the
tool on a fresh ``MCPServer`` instance (isolated per-call state; no stdio).
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone

log = logging.getLogger(__name__)

TASK_TERMINAL = frozenset({"completed", "failed", "cancelled"})
RELATED_TASK_META = "io.modelcontextprotocol/related-task"

_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603

# Runner: (tool_name, arguments) -> CallToolResult dict (isError + content[/...]).
Runner = Callable[[str, dict], dict]


class TaskError(Exception):
    """A JSON-RPC protocol error from a task operation. ``server.py`` maps this
    onto the same wire error its ``_ProtocolError`` produces."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_int(name: str, default: int, *, lo: int, hi: int) -> int:
    try:
        v = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _first_text(result: dict) -> str:
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            return str(block.get("text", ""))
    return ""


class McpTask:
    """In-memory record of one task-augmented request's execution state."""

    def __init__(self, *, ttl_ms: int, poll_interval_ms: int, owner: str | None = None):
        # No auth context on stdio (single client owns the pipe), so per the
        # spec's security guidance the id is cryptographically random with
        # ample entropy rather than guessable/sequential.
        self.id = secrets.token_hex(16)
        self.owner = owner
        self.status = "working"
        self.status_message = "The operation is now in progress."
        self.created_at = _now_iso()
        self.updated_at = self.created_at
        self._created_epoch = time.time()
        self.ttl_ms = ttl_ms
        self.poll_interval_ms = poll_interval_ms
        self.result: dict | None = None
        self.future: Future | None = None
        self.cancel_requested = False
        # Set when the task reaches a terminal status; tasks/result blocks on it.
        self.done = threading.Event()
        # Frozen "working" snapshot for the CreateTaskResult. Captured here,
        # before the worker is submitted, so the acceptance ack always reports
        # the spec-mandated initial `working` status even if a fast tool has
        # already finished by the time the response is serialized.
        self.create_result = self.to_dict()

    def set_status(self, status: str, message: str | None = None) -> None:
        self.status = status
        if message is not None:
            self.status_message = message
        self.updated_at = _now_iso()
        if status in TASK_TERMINAL:
            self.done.set()

    def is_expired(self, now_epoch: float) -> bool:
        return (
            self.ttl_ms is not None
            and (now_epoch - self._created_epoch) * 1000.0 > self.ttl_ms
        )

    def to_dict(self) -> dict:
        d: dict = {
            "taskId": self.id,
            "status": self.status,
            "createdAt": self.created_at,
            "lastUpdatedAt": self.updated_at,
            "ttl": self.ttl_ms,
            "pollInterval": self.poll_interval_ms,
        }
        if self.status_message:
            d["statusMessage"] = self.status_message
        return d


class TaskStore:
    """Registry + background executor for MCP tasks.

    Thread-safety: a single lock guards the registry and per-task mutations.
    Workers only mutate their task record (never stdout), so the server's main
    loop stays the sole writer of the transport."""

    def __init__(
        self,
        runner: Runner,
        *,
        max_workers: int | None = None,
        max_tasks: int | None = None,
        max_tasks_per_owner: int | None = None,
        default_ttl_ms: int | None = None,
        max_ttl_ms: int | None = None,
        poll_interval_ms: int | None = None,
        result_block_ms: int | None = None,
        page_size: int = 100,
        on_status_change: Callable[[McpTask], None] | None = None,
    ):
        self._runner = runner
        # Optional: invoked with the task each time it changes status, so the
        # server can push notifications/tasks/status. Fired outside the lock.
        self._on_status_change = on_status_change
        self._max_tasks = max_tasks if max_tasks is not None else _env_int(
            "MAVERICK_MCP_MAX_TASKS", 256, lo=1, hi=100_000)
        # Per-owner sub-cap (HTTP multi-client mode only). The global cap above
        # is shared, and _make_room only evicts TERMINAL tasks, so without this
        # one HTTP session could fill all 256 slots with active tasks and block
        # task creation for every other client -- defeating the per-session
        # isolation MAVERICK_MCP_HTTP_TASKS exists to provide. Bounded by the
        # global cap; ignored for stdio (owner=None, single client).
        self._max_tasks_per_owner = (
            max_tasks_per_owner if max_tasks_per_owner is not None else _env_int(
                "MAVERICK_MCP_MAX_TASKS_PER_OWNER",
                min(32, self._max_tasks), lo=1, hi=self._max_tasks)
        )
        self._default_ttl_ms = default_ttl_ms if default_ttl_ms is not None else _env_int(
            "MAVERICK_MCP_TASK_TTL_MS", 3_600_000, lo=1_000, hi=604_800_000)
        self._max_ttl_ms = max_ttl_ms if max_ttl_ms is not None else _env_int(
            "MAVERICK_MCP_TASK_MAX_TTL_MS", 86_400_000, lo=1_000, hi=604_800_000)
        self._poll_ms = poll_interval_ms if poll_interval_ms is not None else _env_int(
            "MAVERICK_MCP_TASK_POLL_MS", 1_000, lo=50, hi=3_600_000)
        # Upper bound on how long a single ``tasks/result`` call blocks a worker
        # thread, INDEPENDENT of the task's ttl (see result()). Defaults to 60s.
        self._result_block_ms = result_block_ms if result_block_ms is not None else _env_int(
            "MAVERICK_MCP_TASK_RESULT_BLOCK_MS", 60_000, lo=1_000, hi=600_000)
        self._page_size = max(1, page_size)
        workers = max_workers if max_workers is not None else _env_int(
            "MAVERICK_MCP_TASK_WORKERS", 4, lo=1, hi=64)
        self._executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="mcp-task")
        self._tasks: dict[str, McpTask] = {}
        self._lock = threading.Lock()

    # ---- lifecycle ------------------------------------------------------

    def create(
        self,
        name: str,
        arguments: dict,
        task_param: dict,
        *,
        owner: str | None = None,
    ) -> McpTask:
        """Register a task (status working), kick off the worker, return it."""
        self._purge_expired()
        task = McpTask(
            ttl_ms=self._resolve_ttl(task_param),
            poll_interval_ms=self._poll_ms,
            owner=owner,
        )
        with self._lock:
            self._reject_if_owner_over_quota_locked(owner)
            self._make_room_for_task_locked()
            self._tasks[task.id] = task
            # Assign the future under the SAME lock that inserts the task: a
            # concurrent cancel()/_purge_expired() must never observe a freshly
            # inserted task with `future is None` and evict a starting worker.
            task.future = self._executor.submit(self._run, task, name, arguments)
        return task

    def _resolve_ttl(self, task_param: dict) -> int:
        raw = (task_param or {}).get("ttl")
        try:
            ttl = int(raw)
        except (TypeError, ValueError):
            ttl = self._default_ttl_ms
        if ttl <= 0:
            ttl = self._default_ttl_ms
        return min(ttl, self._max_ttl_ms)  # receivers MAY override the request

    def _run(self, task: McpTask, name: str, arguments: dict) -> None:
        if task.cancel_requested:  # cancelled before the worker picked it up
            return
        try:
            result = self._runner(name, arguments)
        except Exception as e:  # noqa: BLE001 -- a runner crash must fail the task, not the pool
            log.exception("mcp task %s (%s) crashed", task.id, name)
            changed = False
            with self._lock:
                if task.status not in TASK_TERMINAL:
                    task.result = {
                        "isError": True,
                        "content": [{"type": "text",
                                     "text": f"task failed: {type(e).__name__}"}],
                    }
                    task.set_status("failed", f"{type(e).__name__}: {e}"[:500])
                    changed = True
            if changed:
                self._notify(task)
            return
        changed = False
        with self._lock:
            if not (task.cancel_requested or task.status in TASK_TERMINAL):
                task.result = result
                if result.get("isError"):
                    task.set_status("failed", _first_text(result)[:500] or "tool reported an error")
                else:
                    task.set_status("completed", "The operation completed.")
                changed = True
            # else: cancelled while running -- keep cancelled, drop the result.
        if changed:
            self._notify(task)

    # ---- JSON-RPC task methods -----------------------------------------

    def get(self, task_id: str, *, owner: str | None = None) -> dict:
        return self._require(task_id, owner=owner).to_dict()

    def result(self, task_id: str, *, owner: str | None = None) -> dict:
        task = self._require(task_id, owner=owner)
        # Block until terminal (spec requirement) -- but bound how long a SINGLE
        # call blocks, independent of the task's ttl. result() runs on the HTTP
        # dispatch thread pool, so waiting the full ttl (up to 24h) lets a caller
        # pin every worker thread with a few large-ttl tasks and freeze the whole
        # server (auth, /healthz, everything). Cap at _result_block_ms (default
        # 60s); on timeout raise so the client re-issues tasks/result or polls
        # tasks/get. The task keeps running until it terminates or its ttl lapses.
        wait_s = max(1.0, min((task.ttl_ms or 0) / 1000.0 + 5.0,
                              self._result_block_ms / 1000.0))
        task.done.wait(timeout=wait_s)
        with self._lock:
            if task.status not in TASK_TERMINAL:
                raise TaskError(_INTERNAL_ERROR, "timed out waiting for task result")
            res = task.result
        if res is None:  # cancelled (or odd) -> there is no underlying result
            res = {"isError": True,
                   "content": [{"type": "text", "text": f"task {task.status}"}]}
        out = dict(res)
        meta = dict(out.get("_meta") or {})
        meta[RELATED_TASK_META] = {"taskId": task.id}
        out["_meta"] = meta
        return out

    def cancel(self, task_id: str, *, owner: str | None = None) -> dict:
        self._purge_expired()
        # A hostile client can send a non-string taskId (list/dict); coerce it to
        # "" so the lookup yields a clean -32602 instead of an unhashable-key
        # TypeError (mirrors a2a_tasks._owned).
        key = task_id if isinstance(task_id, str) else ""
        with self._lock:
            task = self._tasks.get(key)
            if task is None or not self._owner_matches(task, owner):
                raise TaskError(_INVALID_PARAMS, "task not found")
            if task.status in TASK_TERMINAL:
                raise TaskError(
                    _INVALID_PARAMS,
                    f"cannot cancel task in terminal status {task.status!r}")
            # Best effort: an in-flight run isn't force-killed, but queued work
            # remains counted until a worker drains it and running results are
            # discarded.
            self._cancel_task_locked(task, "The task was cancelled by request.")
            snapshot = task.to_dict()
        self._notify(task)
        return snapshot

    def list(self, cursor: str | None, *, owner: str | None = None) -> dict:
        self._purge_expired()
        start = self._decode_cursor(cursor)
        with self._lock:
            items = [
                task for task in self._tasks.values()
                if self._owner_matches(task, owner)
            ]
        if start > len(items):
            raise TaskError(_INVALID_PARAMS, "invalid cursor")
        chunk = items[start:start + self._page_size]
        out: dict = {"tasks": [t.to_dict() for t in chunk]}
        if start + self._page_size < len(items):
            out["nextCursor"] = base64.urlsafe_b64encode(
                str(start + self._page_size).encode()).decode()
        return out

    # ---- helpers --------------------------------------------------------

    def _require(self, task_id: str, *, owner: str | None = None) -> McpTask:
        self._purge_expired()
        # Coerce a non-string taskId (hostile list/dict) to "" so the lookup
        # raises a clean -32602 rather than an unhashable-key TypeError.
        key = task_id if isinstance(task_id, str) else ""
        with self._lock:
            task = self._tasks.get(key)
        if task is None or not self._owner_matches(task, owner):
            raise TaskError(_INVALID_PARAMS, "task not found")
        return task

    @staticmethod
    def _owner_matches(task: McpTask, owner: str | None) -> bool:
        # owner=None is the stdio/single-client mode: preserve existing behavior.
        # HTTP passes a per-client session owner to isolate task records while
        # returning the same "task not found" error for absent and foreign ids.
        return owner is None or task.owner == owner

    def _decode_cursor(self, cursor: str | None) -> int:
        if not cursor:
            return 0
        try:
            start = int(base64.urlsafe_b64decode(cursor.encode()).decode())
        except Exception:  # noqa: BLE001 -- opaque token; any garbage is invalid
            raise TaskError(_INVALID_PARAMS, "invalid cursor") from None
        if start < 0:
            raise TaskError(_INVALID_PARAMS, "invalid cursor")
        return start

    def _reject_if_owner_over_quota_locked(self, owner: str | None) -> None:
        # owner=None is stdio/single-client mode: the global cap governs, no
        # per-owner quota. In HTTP mode, count this owner's records that still
        # occupy the shared worker/queue capacity. That includes non-terminal
        # tasks and cancelled terminal tasks whose Future has not drained yet;
        # otherwise one session can repeatedly create+cancel tasks to bypass
        # the owner cap while filling the global cap with non-evictable records.
        if owner is None:
            return
        active = sum(
            1 for t in self._tasks.values()
            if t.owner == owner and self._task_occupies_capacity(t)
        )
        if active >= self._max_tasks_per_owner:
            raise TaskError(
                _INVALID_PARAMS, "too many active tasks for this session")

    @staticmethod
    def _task_occupies_capacity(task: McpTask) -> bool:
        if task.status not in TASK_TERMINAL:
            return True
        return task.future is not None and not task.future.done()

    def _make_room_for_task_locked(self) -> None:
        # Completed/failed/cancelled records are retained only for polling; drop
        # the oldest terminal snapshots first before rejecting new work. A
        # cancelled task may still occupy the executor queue, so keep it counted
        # until the worker has drained it and the future is done. Never evict
        # active records: losing those task ids would make their queued or
        # running executions unmanageable and defeat the configured task cap.
        while len(self._tasks) >= self._max_tasks:
            for tid, task in self._tasks.items():
                if not self._task_occupies_capacity(task):
                    self._tasks.pop(tid, None)
                    break
            else:
                raise TaskError(_INVALID_PARAMS, "too many active tasks")

    def _cancel_task_locked(self, task: McpTask, message: str) -> None:
        task.cancel_requested = True
        # Do not call Future.cancel() here: ThreadPoolExecutor leaves cancelled
        # work items in its internal queue until a worker drains them. Keeping
        # the future pending makes the task continue counting toward
        # _max_tasks, so repeated cancel/expire cycles cannot grow that queue
        # without bound. Running tasks cannot be force-killed; _run drops their
        # results after observing cancel_requested.
        task.set_status("cancelled", message)

    def _purge_expired(self) -> None:
        now = time.time()
        with self._lock:
            expired = [tid for tid, t in self._tasks.items() if t.is_expired(now)]
            for tid in expired:
                task = self._tasks.get(tid)
                if task is None:
                    continue
                if task.status not in TASK_TERMINAL:
                    self._cancel_task_locked(task, "The task expired.")
                    continue
                if not self._task_occupies_capacity(task):
                    self._tasks.pop(tid, None)

    def _notify(self, task: McpTask) -> None:
        cb = self._on_status_change
        if cb is None:
            return
        try:
            cb(task)
        except Exception:  # noqa: BLE001 -- a notify failure must not break the task
            log.warning("mcp task %s status-notify failed", task.id, exc_info=True)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
