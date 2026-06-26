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
import contextlib
import hashlib
import hmac
import logging
import os
import uuid
from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import Lock
from typing import Any

log = logging.getLogger(__name__)

# The resolved trust-registry id of the current A2A caller (set per task from
# its principal; read by _a2a_capability to apply that caller's ceiling). A
# contextvar so it propagates into the worker thread (asyncio.to_thread copies
# the context) without threading it through the fixed Runner signature.
_caller_agent: ContextVar[str | None] = ContextVar("a2a_caller_agent", default=None)


def _agent_id_of(principal: str | None) -> str | None:
    """The registry agent id behind a principal, or ``None`` for shared/anon."""
    if principal and principal.startswith("agent:"):
        return principal[len("agent:"):]
    return None

TERMINAL_STATES = {"completed", "failed", "canceled", "rejected"}


def _max_tasks() -> int:
    try:
        return max(16, int(os.environ.get("MAVERICK_A2A_MAX_TASKS", "1000")))
    except ValueError:
        return 1000


_MAX_TASKS = _max_tasks()


def _max_concurrency() -> int:
    """Max A2A goals that may execute concurrently. Default small (4) so one
    caller can't saturate the process-wide default ThreadPoolExecutor (which
    asyncio.to_thread uses) with long-running goals and stall every other
    to_thread consumer in the dashboard process. 0 disables the cap."""
    try:
        return max(0, int(os.environ.get("MAVERICK_A2A_MAX_CONCURRENCY", "4")))
    except ValueError:
        return 4


# One semaphore per running event loop. The engine is constructed once at
# mount, but a Semaphore must be awaited on the loop it was created on; keying
# by the running loop keeps this correct across the test harness's per-call
# loops and under a single long-lived server loop in production. The map is
# bounded so a churn of short-lived loops can't leak entries -- a missing entry
# just recreates the (cheap) semaphore for the current loop.
_RUN_SEM_LOCK = Lock()
_RUN_SEMAPHORES: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}
_RUN_SEM_MAX_LOOPS = 64


def _run_semaphore() -> asyncio.Semaphore | None:
    """The concurrency limiter for the current event loop, or None when the
    cap is disabled (MAVERICK_A2A_MAX_CONCURRENCY=0)."""
    limit = _max_concurrency()
    if limit <= 0:
        return None
    loop = asyncio.get_running_loop()
    with _RUN_SEM_LOCK:
        sem = _RUN_SEMAPHORES.get(loop)
        if sem is None:
            if len(_RUN_SEMAPHORES) >= _RUN_SEM_MAX_LOOPS:
                # Sweep semaphores bound to loops that have closed; drop the
                # oldest if none are reclaimable so the map stays bounded.
                for stale in [lp for lp in _RUN_SEMAPHORES if lp.is_closed()]:
                    _RUN_SEMAPHORES.pop(stale, None)
                while len(_RUN_SEMAPHORES) >= _RUN_SEM_MAX_LOOPS:
                    _RUN_SEMAPHORES.pop(next(iter(_RUN_SEMAPHORES)))
            sem = asyncio.Semaphore(limit)
            _RUN_SEMAPHORES[loop] = sem
    return sem


@contextlib.asynccontextmanager
async def _run_slot() -> AsyncIterator[None]:
    """Hold a concurrency slot for the duration of a goal run, or admit freely
    when the cap is disabled. Sized by MAVERICK_A2A_MAX_CONCURRENCY (default 4)."""
    sem = _run_semaphore()
    if sem is None:
        yield
        return
    async with sem:
        yield

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
    """Concatenate the text parts of an A2A Message.

    Defensive about a hostile client's shape: ``parts`` may be any JSON value
    (a string/number, not a list) and its items may be non-objects, so this
    must not assume a list of dicts — otherwise iterating a string or calling
    ``.get`` on a non-dict raises out of the task runner (a 500 / DoS)."""
    parts = message.get("parts")
    if not isinstance(parts, list):
        return ""
    chunks = [
        p.get("text", "") for p in parts
        if isinstance(p, dict) and p.get("kind") == "text"
    ]
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

    cap = Capability(
        principal="a2a",
        allow_tools=_names("tools", "MAVERICK_A2A_TOOLS"),
        deny_tools=_names("deny_tools", "MAVERICK_A2A_DENY_TOOLS"),
        max_risk=max_risk,
    )
    # When the Agent Trust Plane is engaged, the caller's [agent_trust] entry
    # tightens this ceiling (intersection, never a broadening). A per-caller
    # bearer resolves to that caller's own entry (via the _caller_agent
    # contextvar); a shared-bearer/anon caller falls back to the surface-wide
    # "a2a" entry. Admission itself is gated separately by _a2a_trust_block.
    try:
        from . import agent_trust
        if agent_trust.agent_trust_enforced():
            caller = _caller_agent.get()
            entry = agent_trust.lookup(caller) if caller else None
            if entry is None:
                entry = agent_trust.lookup("a2a")
            if entry is not None:
                cap = cap.intersect(entry.capability(principal="a2a"),
                                    principal="a2a")
    except Exception as e:  # narrow: log, don't silently widen the ceiling
        log.warning("a2a: trust ceiling read failed (using base ceiling): %s", e)
    return cap


def _a2a_trust_block(principal: str = "anon") -> str | None:
    """Default-deny admission for the A2A surface when the plane is engaged.

    Gates on the CALLER's registry entry: a per-caller bearer (principal
    ``agent:<id>``) is governed by that agent's entry; a shared-bearer/anon
    caller falls back to the surface-wide ``"a2a"`` entry. So engaging the plane
    does not leave A2A open at its medium ceiling to anyone with the bearer (the
    prior tighten-only, fail-open gap). Returns ``None`` (admit) when disengaged.
    """
    try:
        from . import agent_trust
        enforced, registry = agent_trust.load_trust_state()
    except Exception:  # config unreadable -> can't assert engagement; admit
        return None
    if not enforced:
        return None
    agent_id = _agent_id_of(principal) or "a2a"
    decision = agent_trust.decide_inbound(agent_id, registry=registry, enforced=True)
    if decision.denied:
        agent_trust.record_denied(agent_id, decision, direction="inbound")
        return decision.reason
    return None


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
        else None.

        Two accepted credentials: the shared operator bearer
        (``MAVERICK_A2A_TOKEN``) and a per-caller ``[agent_trust] a2a_token``
        (which also establishes per-caller identity, see ``principal_for``).
        Bearer required unless ``MAVERICK_A2A_ALLOW_UNAUTHENTICATED`` and no
        token of either kind is configured."""
        env_token = os.environ.get("MAVERICK_A2A_TOKEN", "").strip()
        given = ""
        if authorization and authorization.startswith("Bearer "):
            given = authorization[len("Bearer "):].strip()
        per_caller = None
        if given:
            try:
                from . import agent_trust
                per_caller = agent_trust.agent_for_a2a_token(given)
            except Exception:  # pragma: no cover - never break auth on read error
                per_caller = None
        if not env_token and per_caller is None and not given:
            if _env_true("MAVERICK_A2A_ALLOW_UNAUTHENTICATED"):
                return None
            return _err(
                _AUTH_REQUIRED,
                "A2A task endpoint requires auth: set MAVERICK_A2A_TOKEN, a "
                "per-caller [agent_trust] a2a_token (or "
                "MAVERICK_A2A_ALLOW_UNAUTHENTICATED=1 for trusted localhost).",
            )
        if not given:
            return _err(_AUTH_REQUIRED, "missing bearer token")
        if env_token and hmac.compare_digest(env_token.encode(), given.encode()):
            return None
        if per_caller is not None:
            return None
        return _err(_AUTH_REQUIRED, "invalid bearer token")

    @staticmethod
    def principal_for(authorization: str | None) -> str:
        """Derive a stable principal id for a request, used to scope tasks.

        A task is bound to its creator's principal at creation, and
        get/cancel/push-config reject a mismatch -- so one A2A caller cannot
        read, cancel, or redirect another caller's task.

        A per-caller ``[agent_trust] a2a_token`` resolves to the stable
        principal ``agent:<id>`` — real per-caller identity the trust plane
        governs individually. Otherwise the shared operator bearer maps all its
        callers to one ``bearer:<hash>`` principal (we never store the raw
        bearer), and an unauthenticated request is ``anon``."""
        if authorization and authorization.startswith("Bearer "):
            given = authorization[len("Bearer "):].strip()
            if given:
                try:
                    from . import agent_trust
                    agent = agent_trust.agent_for_a2a_token(given)
                    if agent is not None:
                        return f"agent:{agent.id}"
                except Exception:  # pragma: no cover - fall back to bearer hash
                    pass
                return "bearer:" + hashlib.sha256(given.encode()).hexdigest()
        return "anon"

    def _owned(self, task_id: object, principal: str) -> _Task:
        """Look up a task and enforce principal ownership.

        Raises a 'task not found' error (not a distinct 'forbidden') for both a
        missing task and a cross-principal one, so a caller can't probe which
        ids exist that belong to someone else.

        Task ids are opaque strings; a hostile client can send a non-string
        ``id``/``taskId`` (a list/dict), which must resolve to 'not found'
        rather than blow up the dict lookup with an unhashable-key TypeError."""
        key = task_id if isinstance(task_id, str) else ""
        task = self._tasks.get(key)
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

        Delegates to :func:`maverick.shield_policy.scan_block`: a scan error
        blocks (fail-toward-gate), and a *missing* shield blocks only when the
        shield is required (enterprise / [safety] require_shield) — so an
        outward-facing A2A surface can't silently admit unscreened input on a
        regulated deployment, while personal installs keep the fail-open default.
        """
        from .shield_policy import scan_block
        return scan_block(text)

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
        tblock = _a2a_trust_block(task.principal)
        if tblock:
            task.set_state("rejected")
            task.add_artifact(f"refused by agent trust plane: {tblock}", "error")
            return
        block = self._shield_block(text)
        if block:
            task.set_state("rejected")
            task.add_artifact(f"blocked by safety shield: {block}", "error")
            return
        task.set_state("working")
        limits = self._limits(task)
        # Bind the caller id so _a2a_capability applies THIS caller's ceiling
        # (the contextvar copies into the worker thread).
        cv = _caller_agent.set(_agent_id_of(task.principal))
        try:
            # Cap concurrently executing goals so one caller can't saturate the
            # process-wide default ThreadPoolExecutor (asyncio.to_thread) for up
            # to the max_wall ceiling and stall every other to_thread consumer.
            async with _run_slot():
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
        finally:
            _caller_agent.reset(cv)
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
            block = _a2a_trust_block(task.principal) or self._shield_block(text)
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
        cv = _caller_agent.set(_agent_id_of(task.principal))
        try:
            async with _run_slot():
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
        finally:
            _caller_agent.reset(cv)
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
        except ImportError:  # pragma: no cover - SSRF guard unavailable
            # Caught BEFORE the BlockedHost clause: if the import above failed,
            # the BlockedHost name is unbound, and evaluating `except BlockedHost`
            # would raise NameError instead of falling through here.
            pass
        except BlockedHost as e:
            raise _RpcError(
                _INVALID_PARAMS, f"pushNotificationConfig.url rejected: {e}",
            ) from e
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
