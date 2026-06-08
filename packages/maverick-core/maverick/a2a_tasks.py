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
import hashlib
import hmac
import logging
import os
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from threading import Lock
from typing import Any

log = logging.getLogger(__name__)

TERMINAL_STATES = {"completed", "failed", "canceled", "rejected"}


def _max_tasks() -> int:
    try:
        return max(16, int(os.environ.get("MAVERICK_A2A_MAX_TASKS", "1000")))
    except ValueError:
        return 1000


_MAX_TASKS = _max_tasks()

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


def _redacted_push_config(cfg: dict | None) -> dict | None:
    """Mask the push-notification ``token`` for read-back.

    The token is a write-only secret an A2A caller registers so it can
    authenticate the callbacks we POST to its webhook. Echoing it back from
    ``get_push_config`` would let a peer that shares the (single) A2A bearer
    token read another caller's webhook secret. Mask it to a fixed marker so
    the owner can still tell that a token is configured; the real value stays
    in storage for ``_fire_push``.
    """
    if not cfg or "token" not in cfg:
        return cfg
    redacted = dict(cfg)
    redacted["token"] = "***"
    return redacted


# Runner signature: (text, *, max_dollars, max_wall, max_depth) -> result str.
Runner = Callable[..., str]


def _a2a_capability() -> Any:
    """Tool ceiling for A2A-initiated goals.

    A2A is a remote, machine-to-machine surface, so its goals run under a
    capability instead of inheriting full local tool access. Defaults to
    ``max_risk="medium"`` -- high-risk tools (shell / code_exec / write / send /
    infra, plus the unclassified MCP tools that now default to high) are off
    unless an operator opts in. Configurable via the ``[a2a]`` config section
    (``max_risk``, ``tools`` allowlist, ``deny_tools``) with a
    ``MAVERICK_A2A_MAX_RISK`` env override; set the risk to ``none``/``off`` to
    lift the ceiling entirely (the prior behaviour).
    """
    from .capability import Capability
    from .safety.tool_risk import RISK_LEVELS

    try:
        from .config import load_config
        cfg = (load_config() or {}).get("a2a") or {}
    except Exception:
        cfg = {}

    raw = os.environ.get("MAVERICK_A2A_MAX_RISK")
    if raw is None:
        raw = cfg.get("max_risk", "medium")
    raw = str(raw).strip().lower()
    if raw in ("none", "off", "any", "unlimited", ""):
        max_risk: str | None = None
    elif raw in RISK_LEVELS:
        max_risk = raw
    else:
        max_risk = "medium"  # unrecognized value -> safe default

    def _names(cfg_key: str, env_key: str) -> frozenset[str]:
        vals = cfg.get(cfg_key)
        if vals is None:
            vals = os.environ.get(env_key, "").split(",")
        if isinstance(vals, str):
            vals = [vals]
        return frozenset(str(v).strip() for v in vals if str(v).strip())

    return Capability(
        principal="a2a",
        allow_tools=_names("tools", "MAVERICK_A2A_TOOLS"),
        deny_tools=_names("deny_tools", "MAVERICK_A2A_DENY_TOOLS"),
        max_risk=max_risk,
    )


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
    # A2A goals run under a tool ceiling (default max_risk="medium") so a remote
    # caller can't reach full local tool access; see _a2a_capability.
    return run_goal_sync(
        llm, world, budget, goal_id, sandbox=sandbox, max_depth=max_depth,
        capability=_a2a_capability(),
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
        # Principal that created the task; get/cancel/push-config are scoped to
        # it so one A2A caller can't read/cancel/redirect another's task.
        self.principal: str = ""
        # Client-requested budget captured at creation, clamped to the operator
        # ceiling at run time (see TaskEngine._limits).
        self.budget_request: dict = {}

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

    @staticmethod
    def principal_for(authorization: str | None) -> str:
        """Derive a stable principal id for a request, used to scope tasks.

        A task is bound to its creator's principal at creation, and
        get/cancel/push-config reject a mismatch -- so one A2A caller cannot
        read, cancel, or redirect another caller's task.

        NOTE: the A2A bearer is a single shared operator token (the protocol
        carries no per-caller identity), so all callers presenting the *same*
        bearer share one principal. The scope this enforces is between
        *different bearer values* and between unauthenticated callers -- the
        latter being the ``MAVERICK_A2A_ALLOW_UNAUTHENTICATED=1`` case the issue
        calls out, where any local client could otherwise reach another's task.
        We key on a hash of the presented bearer (never stored raw) and fall
        back to ``anon`` when none is presented."""
        if authorization and authorization.startswith("Bearer "):
            given = authorization[len("Bearer "):].strip()
            if given:
                return "bearer:" + hashlib.sha256(given.encode()).hexdigest()
        return "anon"

    def _owned(self, task_id: str, principal: str) -> _Task:
        """Look up a task and enforce principal ownership.

        Raises a 'task not found' error (not a distinct 'forbidden') for both a
        missing task and a cross-principal one, so a caller can't probe which
        ids exist that belong to someone else."""
        task = self._tasks.get(task_id or "")
        if task is None or task.principal != principal:
            raise _RpcError(_TASK_NOT_FOUND, "task not found")
        return task

    def _limits(self, task: _Task | None = None) -> dict:
        """Resolve per-run limits, clamping the CLIENT request to the operator
        ceiling.

        The operator env vars are the hard ceiling; the A2A caller may request
        *less* via its message (captured in ``task.budget_request``). We pass
        the client value as ``value`` and the operator setting as ``ceiling`` so
        ``min(client, operator)`` clamps the request DOWN -- never up. The
        previous code passed the same env var as both value and ceiling, so the
        ``min`` was a tautology and the client request was ignored entirely.
        With no client value the run defaults to the operator ceiling."""
        req = task.budget_request if task else {}
        ceil_dollars = os.environ.get("MAVERICK_A2A_MAX_DOLLARS", 5.0)
        ceil_wall = os.environ.get("MAVERICK_A2A_MAX_WALL_SECONDS", 3600.0)
        ceil_depth = os.environ.get("MAVERICK_A2A_MAX_DEPTH", 3)
        return {
            "max_dollars": _bounded_float(
                req.get("max_dollars", ceil_dollars),
                default=_bounded_float(ceil_dollars, default=5.0, ceiling=ceil_dollars),
                ceiling=ceil_dollars,
            ),
            "max_wall": _bounded_float(
                req.get("max_wall", ceil_wall),
                default=_bounded_float(ceil_wall, default=3600.0, ceiling=ceil_wall),
                ceiling=ceil_wall,
            ),
            "max_depth": _bounded_int(
                req.get("max_depth", ceil_depth),
                default=_bounded_int(ceil_depth, default=3, ceiling=ceil_depth),
                ceiling=ceil_depth,
            ),
        }

    @staticmethod
    def _client_budget(params: dict | None) -> dict:
        """Extract a client-requested budget from the request params.

        A2A callers carry per-call budget hints in ``params.configuration`` and
        /or the message ``metadata``; we read a small explicit set of keys.
        Absent / junk values simply don't appear here and fall back to the
        operator ceiling in ``_limits`` -- and whatever the client asks for is
        still clamped DOWN to the ceiling there, never up."""
        params = params or {}
        sources: list[dict] = []
        cfg = params.get("configuration")
        if isinstance(cfg, dict):
            sources.append(cfg)
        msg = params.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("metadata"), dict):
            sources.append(msg["metadata"])
        out: dict = {}
        for src in sources:
            for key in ("max_dollars", "max_wall", "max_depth"):
                if key in src and key not in out:
                    out[key] = src[key]
        return out

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

    def _new_task(self, params: dict, principal: str = "anon") -> _Task:
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
        task.principal = principal
        task.budget_request = self._client_budget(params)
        user_message["taskId"] = task.id
        user_message["contextId"] = task.context_id
        with self._lock:
            # Bound the in-memory task store so an authenticated client can't
            # grow it without limit (memory DoS). Evict the oldest tasks past
            # the cap -- dict preserves insertion order, so popping the front
            # drops the least-recently-created. Override via
            # MAVERICK_A2A_MAX_TASKS.
            self._tasks[task.id] = task
            while len(self._tasks) > _MAX_TASKS:
                self._tasks.pop(next(iter(self._tasks)))
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
        limits = self._limits(task)
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

    async def send(self, params: dict, principal: str = "anon") -> dict:
        task = self._new_task(params, principal)
        await self._run(task)
        await self._fire_push(task)
        return task.to_dict()

    async def stream(
        self, params: dict, principal: str = "anon",
    ) -> AsyncIterator[dict]:
        """Yield A2A stream events (already in result-object form)."""
        task = self._new_task(params, principal)
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
        limits = self._limits(task)
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

    def get(self, params: dict, principal: str = "anon") -> dict:
        task = self._owned((params or {}).get("id", ""), principal)
        return task.to_dict()

    def cancel(self, params: dict, principal: str = "anon") -> dict:
        task = self._owned((params or {}).get("id", ""), principal)
        task.cancel_requested = True
        if task.state not in TERMINAL_STATES:
            task.set_state("canceled")
        return task.to_dict()

    def set_push_config(self, params: dict, principal: str = "anon") -> dict:
        task = self._owned((params or {}).get("taskId", ""), principal)
        cfg = (params or {}).get("pushNotificationConfig") or {}
        url = cfg.get("url")
        if not url:
            raise _RpcError(_INVALID_PARAMS, "pushNotificationConfig.url required")
        # Validate the push URL at REGISTRATION (not just at fire time): a
        # loopback/metadata/internal target must be refused here so it can never
        # be stored, mirroring the SSRF guard _fire_push applies. Reuse the same
        # resolve-and-check primitive.
        try:
            from urllib.parse import urlparse

            from .tools._ssrf import BlockedHost, resolve_pinned_ip
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                raise BlockedHost(f"scheme {parsed.scheme!r} not allowed")
            resolve_pinned_ip(parsed.hostname or "")
        except BlockedHost as e:
            raise _RpcError(
                _INVALID_PARAMS, f"pushNotificationConfig.url rejected: {e}",
            )
        except ImportError:  # pragma: no cover - guard unavailable, fall through
            pass
        task.push_config = cfg
        return {"taskId": task.id, "pushNotificationConfig": _redacted_push_config(cfg)}

    def get_push_config(self, params: dict, principal: str = "anon") -> dict:
        task = self._owned((params or {}).get("id", "")
                           or (params or {}).get("taskId", ""), principal)
        return {
            "taskId": task.id,
            "pushNotificationConfig": _redacted_push_config(task.push_config),
        }

    async def _fire_push(self, task: _Task) -> None:
        """POST the terminal Task to a registered webhook (best-effort).

        The webhook URL is supplied by the (outward-facing) A2A caller, so it
        is routed through the SSRF guard: a peer must not be able to make the
        server POST the task to ``169.254.169.254`` / ``127.0.0.1`` / other
        internal hosts. ``safe_async_client`` resolves once, rejects any
        non-public address, and pins the connection (no rebind window).
        """
        cfg = task.push_config
        if not cfg or task.state not in TERMINAL_STATES:
            return
        try:
            from .tools._ssrf import BlockedHost, safe_async_client
        except Exception:  # pragma: no cover
            return
        url = cfg.get("url") or ""
        headers = {}
        tok = cfg.get("token")
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        # ``safe_async_client`` resolves the host once, rejects any non-public
        # address, and pins the connection to that IP (Host/SNI preserved) --
        # so there is no second lookup to rebind. A bad scheme or non-public
        # host raises BlockedHost and we fail closed (no request sent).
        try:
            client = safe_async_client(url, timeout=15.0)
        except BlockedHost as e:
            log.warning("a2a push notify blocked for %s (SSRF guard): %s", task.id, e)
            return
        try:
            async with client:
                await client.post(url, headers=headers, json=task.to_dict())
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
