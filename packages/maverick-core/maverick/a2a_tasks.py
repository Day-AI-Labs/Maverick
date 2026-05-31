"""A2A task lifecycle: the execution half of A2A (discovery lives in
``a2a.py``).

Implements the A2A v1.0 JSON-RPC task surface over a single ``POST
/a2a/v1`` endpoint, mounted on the dashboard FastAPI app by
``a2a.mount()`` when A2A is enabled:

  - ``message/send``     run a goal to completion, return the final Task.
  - ``message/stream``   same, but stream Task / status-update /
                         artifact-update events over SSE.
  - ``tasks/get``        fetch a task (status + message + state history).
  - ``tasks/cancel``     best-effort cancel (marks terminal; an already
                         in-flight goal isn't force-killed).
  - ``tasks/pushNotificationConfig/set|get``  register a webhook that
                         receives the Task when it reaches a terminal state.

Spec shapes follow https://a2a-protocol.org (v1.0): Task ``kind="task"``,
``status.state`` in {submitted, working, completed, failed, canceled,
rejected}, and ``status-update`` / ``artifact-update`` stream events.

Security — this surface is outward-facing and spends real provider
budget, so by default it requires bearer auth: set ``MAVERICK_A2A_TOKEN``
and callers must send ``Authorization: Bearer <token>``. For a trusted
localhost you can run it open with
``MAVERICK_A2A_ALLOW_UNAUTHENTICATED=1``. Client-supplied budget is always
clamped to operator ceilings (``MAVERICK_A2A_MAX_DOLLARS`` /
``_MAX_WALL_SECONDS`` / ``_MAX_DEPTH``), and the prompt is screened by the
safety shield when installed (fail-open).
"""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import logging
import os
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from urllib.parse import urlparse

from .tools._ssrf import BlockedHost, safe_async_client

log = logging.getLogger(__name__)

TERMINAL_STATES = {"completed", "failed", "canceled", "rejected"}

# JSON-RPC error codes used by the engine (-32000..-32099 is the
# server-defined range; the standard codes like parse/invalid-request are
# emitted as literals at the HTTP boundary in a2a.py).
_INVALID_PARAMS = -32602
_AUTH_REQUIRED = -32001
_TASK_NOT_FOUND = -32002


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _text_parts(text: str) -> list[dict]:
    return [{"kind": "text", "text": text}]


def _message_text(message: dict) -> str:
    """Concatenate the text parts of an A2A Message."""
    parts = message.get("parts") or []
    chunks = [p.get("text", "") for p in parts if p.get("kind") == "text"]
    return "\n".join(c for c in chunks if c).strip()


def _is_blocked_ip_literal(hostname: str) -> bool:
    """Return True when ``hostname`` is itself a non-public IP address."""
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _validated_push_url(cfg: dict) -> str:
    """Validate and normalize an A2A push webhook URL.

    Push notifications are server-side callbacks to caller-controlled URLs, so
    only HTTPS webhooks with a syntactically valid, non-literal-private host are
    accepted. DNS-backed private/metadata targets are checked again immediately
    before delivery with a resolve-once pinned HTTP client.
    """
    url = str((cfg or {}).get("url") or "").strip()
    if not url:
        raise _RpcError(_INVALID_PARAMS, "pushNotificationConfig.url required")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise _RpcError(
            _INVALID_PARAMS,
            "pushNotificationConfig.url must be an https URL with a host",
        )
    if _is_blocked_ip_literal(parsed.hostname):
        raise _RpcError(
            _INVALID_PARAMS,
            "pushNotificationConfig.url host must be public",
        )
    return url


def _bounded_float(value: Any, *, default: float, ceiling: Any) -> float:
    """Clamp a client-supplied number to [0, ceiling]; fall back on junk."""
    try:
        v = float(value)
        cap = float(ceiling)
    except (TypeError, ValueError):
        return default
    if v != v or v < 0:  # NaN or negative
        return default
    return min(v, cap)


def _bounded_int(value: Any, *, default: int, ceiling: Any) -> int:
    return int(_bounded_float(value, default=float(default), ceiling=ceiling))


# Runner signature: (text, *, max_dollars, max_wall, max_depth) -> result str.
Runner = Callable[..., str]


def _default_runner(
    text: str, *, max_dollars: float, max_wall: float, max_depth: int,
) -> str:
    """Run a goal through the real orchestrator and return its result."""
    from .budget import Budget
    from .llm import LLM
    from .orchestrator import run_goal_sync
    from .sandbox import build_sandbox
    from .world_model import WorldModel

    budget = Budget(max_dollars=max_dollars, max_wall_seconds=max_wall)
    world = WorldModel()
    goal_id = world.create_goal(text[:120] or "a2a task", text)
    llm = LLM()
    sandbox = build_sandbox()
    return run_goal_sync(
        llm, world, budget, goal_id, sandbox=sandbox, max_depth=max_depth,
    )


class _Task:
    """In-memory task record with status + state-transition history."""

    def __init__(self, context_id: str, user_message: dict):
        self.id = _new_id()
        self.context_id = context_id or _new_id()
        self.created_at = _now_iso()
        self.state = "submitted"
        self.status_history: list[dict] = [
            {"state": "submitted", "timestamp": self.created_at}
        ]
        self.messages: list[dict] = [user_message]
        self.artifacts: list[dict] = []
        self.push_config: dict | None = None
        self.cancel_requested = False

    def set_state(self, state: str) -> dict:
        self.state = state
        entry = {"state": state, "timestamp": _now_iso()}
        self.status_history.append(entry)
        return entry

    def add_artifact(self, text: str, name: str = "result") -> dict:
        art = {
            "artifactId": _new_id(),
            "name": name,
            "parts": _text_parts(text),
        }
        self.artifacts.append(art)
        return art

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "contextId": self.context_id,
            "status": {
                "state": self.state,
                "timestamp": self.status_history[-1]["timestamp"],
            },
            "artifacts": list(self.artifacts),
            "history": list(self.messages),
            "kind": "task",
            # stateTransitionHistory capability: expose the recorded
            # status timeline so clients can audit how the task progressed.
            "metadata": {"statusHistory": list(self.status_history)},
        }


class TaskEngine:
    """Runs A2A tasks and tracks their lifecycle. FastAPI-agnostic so it
    can be unit-tested directly; ``a2a.mount`` adapts it to HTTP/SSE."""

    def __init__(self, runner: Runner | None = None):
        self._runner: Runner = runner or _default_runner
        self._tasks: dict[str, _Task] = {}
        self._lock = Lock()

    # ---- auth + limits -------------------------------------------------

    def auth_error(self, authorization: str | None) -> dict | None:
        """Return a JSON-RPC error object if the request isn't authorised,
        else None. Bearer required unless explicitly opted out."""
        token = os.environ.get("MAVERICK_A2A_TOKEN", "").strip()
        if not token:
            if _env_true("MAVERICK_A2A_ALLOW_UNAUTHENTICATED"):
                return None
            return _err(
                _AUTH_REQUIRED,
                "A2A task endpoint requires auth: set MAVERICK_A2A_TOKEN "
                "(or MAVERICK_A2A_ALLOW_UNAUTHENTICATED=1 for trusted "
                "localhost).",
            )
        if not authorization or not authorization.startswith("Bearer "):
            return _err(_AUTH_REQUIRED, "missing bearer token")
        given = authorization[len("Bearer "):].strip()
        if not hmac.compare_digest(token, given):
            return _err(_AUTH_REQUIRED, "invalid bearer token")
        return None

    def _limits(self) -> dict:
        return {
            "max_dollars": _bounded_float(
                os.environ.get("MAVERICK_A2A_MAX_DOLLARS", 5.0),
                default=5.0,
                ceiling=os.environ.get("MAVERICK_A2A_MAX_DOLLARS", 5.0),
            ),
            "max_wall": _bounded_float(
                os.environ.get("MAVERICK_A2A_MAX_WALL_SECONDS", 3600.0),
                default=3600.0,
                ceiling=os.environ.get("MAVERICK_A2A_MAX_WALL_SECONDS", 3600.0),
            ),
            "max_depth": _bounded_int(
                os.environ.get("MAVERICK_A2A_MAX_DEPTH", 3),
                default=3,
                ceiling=os.environ.get("MAVERICK_A2A_MAX_DEPTH", 3),
            ),
        }

    def _shield_block(self, text: str) -> str | None:
        """Return a reason string if the shield blocks the input, else None.
        Fail-open: any error/absence means allow."""
        try:
            from maverick_shield import Shield  # type: ignore
        except Exception:
            return None
        try:
            verdict = Shield().scan_input(text)
            if not getattr(verdict, "allowed", True):
                return "; ".join(getattr(verdict, "reasons", []) or ["blocked"])
        except Exception as e:  # pragma: no cover
            log.warning("a2a shield scan failed (fail-open): %s", e)
        return None

    # ---- task helpers --------------------------------------------------

    def _new_task(self, params: dict) -> _Task:
        message = (params or {}).get("message") or {}
        context_id = message.get("contextId") or ""
        # Normalise the inbound message so history echoes a complete record.
        user_message = {
            "role": message.get("role", "user"),
            "parts": message.get("parts") or [],
            "messageId": message.get("messageId") or _new_id(),
            "kind": "message",
        }
        task = _Task(context_id, user_message)
        user_message["taskId"] = task.id
        user_message["contextId"] = task.context_id
        with self._lock:
            self._tasks[task.id] = task
        return task

    async def _run(self, task: _Task) -> None:
        """Execute the goal, transitioning task state. Updates the record
        in place; callers read task.to_dict() afterwards."""
        text = _message_text(task.messages[0])
        if not text:
            task.set_state("rejected")
            task.add_artifact("empty message: no text parts to act on", "error")
            return
        block = self._shield_block(text)
        if block:
            task.set_state("rejected")
            task.add_artifact(f"blocked by safety shield: {block}", "error")
            return
        task.set_state("working")
        limits = self._limits()
        try:
            result = await asyncio.to_thread(
                self._runner,
                text,
                max_dollars=limits["max_dollars"],
                max_wall=limits["max_wall"],
                max_depth=limits["max_depth"],
            )
        except Exception as e:
            log.exception("a2a task %s failed", task.id)
            task.set_state("failed")
            task.add_artifact(f"task failed: {e}", "error")
            return
        if task.cancel_requested:
            # A cancel landed while we were running; honour it and drop the
            # result rather than reporting completion.
            task.set_state("canceled")
            return
        task.add_artifact(result or "")
        task.set_state("completed")

    # ---- JSON-RPC methods ----------------------------------------------

    async def send(self, params: dict) -> dict:
        task = self._new_task(params)
        await self._run(task)
        await self._fire_push(task)
        return task.to_dict()

    async def stream(self, params: dict) -> AsyncIterator[dict]:
        """Yield A2A stream events (already in result-object form)."""
        task = self._new_task(params)
        # 1. initial Task snapshot.
        yield task.to_dict()
        text = _message_text(task.messages[0])
        block = None if text else "empty message"
        if not block:
            block = self._shield_block(text)
        if block:
            task.set_state("rejected")
            yield _status_event(task, final=True)
            await self._fire_push(task)
            return
        # 2. working status.
        task.set_state("working")
        yield _status_event(task, final=False)
        # 3. run.
        limits = self._limits()
        try:
            result = await asyncio.to_thread(
                self._runner, text,
                max_dollars=limits["max_dollars"],
                max_wall=limits["max_wall"],
                max_depth=limits["max_depth"],
            )
        except Exception as e:
            log.exception("a2a stream task %s failed", task.id)
            task.set_state("failed")
            task.add_artifact(f"task failed: {e}", "error")
            yield _status_event(task, final=True)
            await self._fire_push(task)
            return
        if task.cancel_requested:
            task.set_state("canceled")
            yield _status_event(task, final=True)
            await self._fire_push(task)
            return
        # 4. artifact then terminal status.
        art = task.add_artifact(result or "")
        yield _artifact_event(task, art)
        task.set_state("completed")
        yield _status_event(task, final=True)
        await self._fire_push(task)

    def get(self, params: dict) -> dict:
        task = self._tasks.get((params or {}).get("id", ""))
        if task is None:
            raise _RpcError(_TASK_NOT_FOUND, "task not found")
        return task.to_dict()

    def cancel(self, params: dict) -> dict:
        task = self._tasks.get((params or {}).get("id", ""))
        if task is None:
            raise _RpcError(_TASK_NOT_FOUND, "task not found")
        task.cancel_requested = True
        if task.state not in TERMINAL_STATES:
            task.set_state("canceled")
        return task.to_dict()

    def set_push_config(self, params: dict) -> dict:
        task = self._tasks.get((params or {}).get("taskId", ""))
        if task is None:
            raise _RpcError(_TASK_NOT_FOUND, "task not found")
        cfg = dict((params or {}).get("pushNotificationConfig") or {})
        cfg["url"] = _validated_push_url(cfg)
        task.push_config = cfg
        return {"taskId": task.id, "pushNotificationConfig": cfg}

    def get_push_config(self, params: dict) -> dict:
        task = self._tasks.get((params or {}).get("id", "")
                               or (params or {}).get("taskId", ""))
        if task is None:
            raise _RpcError(_TASK_NOT_FOUND, "task not found")
        return {"taskId": task.id, "pushNotificationConfig": task.push_config}

    async def _fire_push(self, task: _Task) -> None:
        """POST the terminal Task to a registered webhook (best-effort)."""
        cfg = task.push_config
        if not cfg or task.state not in TERMINAL_STATES:
            return
        try:
            url = _validated_push_url(cfg)
        except _RpcError as e:
            log.warning("a2a push notify refused for %s: %s", task.id, e.message)
            return
        headers = {}
        tok = cfg.get("token")
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        try:
            async with safe_async_client(url, timeout=15.0) as client:
                await client.post(url, headers=headers, json=task.to_dict())
        except BlockedHost as e:
            log.warning(
                "a2a push notify refused for %s: non-public host (SSRF guard): %s",
                task.id, e,
            )
        except Exception as e:  # pragma: no cover
            log.warning("a2a push notify failed for %s: %s", task.id, e)


# Methods that return an SSE stream rather than a single JSON response.
STREAM_METHODS = {"message/stream"}


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _err(code: int, message: str) -> dict:
    return {"code": code, "message": message}


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _status_event(task: _Task, *, final: bool) -> dict:
    return {
        "taskId": task.id,
        "contextId": task.context_id,
        "kind": "status-update",
        "status": {
            "state": task.state,
            "timestamp": task.status_history[-1]["timestamp"],
        },
        "final": final,
    }


def _artifact_event(task: _Task, artifact: dict) -> dict:
    return {
        "taskId": task.id,
        "contextId": task.context_id,
        "kind": "artifact-update",
        "artifact": artifact,
        "append": False,
        "lastChunk": True,
    }
