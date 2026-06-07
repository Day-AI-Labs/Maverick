"""A2A (Agent2Agent) discovery: serve a standards-shaped Agent Card.

The A2A protocol (Linux Foundation, v1.0 — crossed 150+ orgs and went to
production in 2026) lets agents discover and describe each other. The
foundational primitive is the **Agent Card**, a JSON document served at
``/.well-known/agent-card.json`` describing who the agent is and what it
can do.

This module makes Maverick *discoverable* as an A2A agent: a pure
``build_agent_card()`` (fully unit-testable, no server) plus a ``mount()``
that registers the well-known route on the FastAPI app.

Off by default: the card is an outward-facing description of a local agent,
so an operator opts in via ``MAVERICK_A2A_ENABLED=1`` or ``[a2a] enabled =
true``. When off, no route is registered.

Scope: this module is the discovery half of A2A (the Agent Card). The
task lifecycle — ``message/send`` / ``message/stream`` / ``tasks/*`` with
auth, budget caps, and push notifications — lives in ``a2a_tasks`` and is
wired onto ``/a2a/v1`` by ``mount()`` below.
"""
from __future__ import annotations

import os
from typing import Any

A2A_PROTOCOL_VERSION = "1.0"

# Default public base URL; overridable so a card served behind a reverse
# proxy advertises the right address.
_DEFAULT_BASE_URL = "http://localhost:8000"


def a2a_enabled() -> bool:
    """Opt-in gate. Off by default (outward-facing surface)."""
    env = os.environ.get("MAVERICK_A2A_ENABLED")
    if env is not None:
        return env.strip().lower() in {"1", "true", "yes", "on"}
    try:
        from .config import load_config
        cfg = (load_config() or {}).get("a2a") or {}
        val = cfg.get("enabled", False)
    except Exception:
        return False
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return bool(val)


def _base_url(override: str | None = None) -> str:
    url = (
        override
        or os.environ.get("MAVERICK_A2A_BASE_URL")
        or _DEFAULT_BASE_URL
    )
    return url.rstrip("/")


def _version() -> str:
    try:
        from . import __version__
        return str(__version__)
    except Exception:
        return "0"


# Coarse A2A "skills" (capability descriptors, not internal agent roles).
_SKILLS: list[dict[str, Any]] = [
    {
        "id": "execute-goal",
        "name": "Execute a long-horizon goal",
        "description": (
            "Give Maverick a goal; a swarm of specialist sub-agents plans, "
            "runs in parallel, and verifies the result -- under a hard "
            "budget cap, with every step screened by a safety layer."
        ),
        "tags": ["autonomy", "multi-agent", "long-horizon", "safety"],
    },
    {
        "id": "research",
        "name": "Research and synthesize",
        "description": "Search across sources, verify, and synthesize a cited answer.",
        "tags": ["research", "web", "synthesis"],
    },
    {
        "id": "code",
        "name": "Write and test code",
        "description": "Implement, run, and verify code changes in a sandbox.",
        "tags": ["code", "sandbox"],
    },
]


def build_agent_card(base_url: str | None = None) -> dict[str, Any]:
    """Return an A2A v1.0-shaped Agent Card for this Maverick instance.

    Pure function -- no I/O beyond reading the version/base-url config -- so
    it can be unit-tested and embedded wherever needed.
    """
    url = _base_url(base_url)
    return {
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "name": "Maverick",
        "description": (
            "An open-source recursive multi-agent swarm that runs long-horizon "
            "work locally -- your models, a hard budget cap, safety baked in."
        ),
        "url": f"{url}/a2a/v1",
        "version": _version(),
        "provider": {
            "organization": "Maverick",
            "url": "https://github.com/Day-AI-Labs/Maverick",
        },
        "capabilities": {
            # Backed by the task endpoint (a2a_tasks): message/stream over
            # SSE, push-notification webhooks, and a recorded status-history.
            "streaming": True,
            "pushNotifications": True,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": list(_SKILLS),
    }


def mount(app: Any) -> None:
    """Register the A2A well-known Agent Card route, if enabled.

    No-op when A2A is disabled (the default), so the surface only exists
    when an operator opts in.
    """
    if not a2a_enabled():
        return

    async def _agent_card() -> dict[str, Any]:
        return build_agent_card()

    # Canonical A2A v1.0 location, plus the pre-1.0 alias some clients still probe.
    app.add_api_route("/.well-known/agent-card.json", _agent_card, methods=["GET"])
    app.add_api_route("/.well-known/agent.json", _agent_card, methods=["GET"])

    _mount_task_endpoint(app)


def _mount_task_endpoint(app: Any) -> None:
    """Register the A2A JSON-RPC task endpoint at ``POST /a2a/v1``.

    Imports FastAPI lazily so the kernel still imports without it; this
    runs only when the dashboard (which has FastAPI) mounts A2A.
    """
    import json as _json

    from starlette.responses import JSONResponse, StreamingResponse

    from .a2a_tasks import STREAM_METHODS, TaskEngine, _RpcError

    engine = TaskEngine()

    # A2A JSON-RPC bodies are small task envelopes. Cap them with the same
    # 256 KiB limit the dashboard webhooks use so an (optionally
    # unauthenticated) caller can't force the server to buffer an arbitrarily
    # large request body. ``request.json()`` buffers the whole body before
    # parsing, so enforce the cap on the raw stream first.
    _MAX_A2A_BODY_BYTES = 256 * 1024

    async def _read_limited_body(request) -> bytes | None:
        """Read the body with a hard size cap; return None if it's too large."""
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > _MAX_A2A_BODY_BYTES:
                    return None
            except ValueError:
                return None
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > _MAX_A2A_BODY_BYTES:
                return None
        return bytes(body)

    def _rpc_result(req_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _rpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": code, "message": message}}

    def _sse(obj: dict[str, Any]) -> str:
        return f"data: {_json.dumps(obj)}\n\n"

    # Registered as a raw Starlette route (not add_api_route): the handler
    # takes the Request directly, so FastAPI doesn't try to resolve the
    # stringized `from __future__` annotations against this module's globals
    # (where the locally-imported Request wouldn't be found -> 422).
    async def _a2a_rpc(request):
        authorization = request.headers.get("authorization")
        raw = await _read_limited_body(request)
        if raw is None:
            return JSONResponse(
                _rpc_error(None, -32600, "request body too large"),
                status_code=413,
            )
        try:
            body = _json.loads(raw)
        except Exception:
            return JSONResponse(_rpc_error(None, -32700, "parse error"))
        if not isinstance(body, dict):
            return JSONResponse(_rpc_error(None, -32600, "invalid request"))
        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}

        auth_err = engine.auth_error(authorization)
        if auth_err is not None:
            return JSONResponse(
                _rpc_error(req_id, auth_err["code"], auth_err["message"]),
                status_code=401,
            )

        # Bind every call to a principal so tasks are scoped to their creator: a
        # client can't get/cancel/redirect another principal's task. Derived
        # from the presented bearer; "anon" when unauthenticated.
        principal = engine.principal_for(authorization)

        if method in STREAM_METHODS:
            async def _gen():
                try:
                    async for event in engine.stream(params, principal):
                        yield _sse(_rpc_result(req_id, event))
                except _RpcError as e:
                    yield _sse(_rpc_error(req_id, e.code, e.message))
            return StreamingResponse(_gen(), media_type="text/event-stream")

        try:
            if method == "message/send":
                result = await engine.send(params, principal)
            elif method == "tasks/get":
                result = engine.get(params, principal)
            elif method == "tasks/cancel":
                result = engine.cancel(params, principal)
            elif method == "tasks/pushNotificationConfig/set":
                result = engine.set_push_config(params, principal)
            elif method == "tasks/pushNotificationConfig/get":
                result = engine.get_push_config(params, principal)
            else:
                return JSONResponse(
                    _rpc_error(req_id, -32601, f"method not found: {method}")
                )
        except _RpcError as e:
            return JSONResponse(_rpc_error(req_id, e.code, e.message))
        return JSONResponse(_rpc_result(req_id, result))

    app.add_route("/a2a/v1", _a2a_rpc, methods=["POST"])
