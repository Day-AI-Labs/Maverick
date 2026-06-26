"""Streamable HTTP transport for Maverick's MCP server (spec 2025-11-25).

The stdio JSON-RPC transport in `server.py` works great for desktop
clients (Claude Desktop, Cursor) that spawn Maverick as a subprocess.
For hosted Maverick — VPS deployments, multi-tenant setups, MCP
gateways like Composio / MintMCP / Cloudflare — clients need an HTTP
endpoint.

This module ships a single POST endpoint that accepts JSON-RPC
requests. When the client sends ``Accept: text/event-stream``, the
response is a Server-Sent Events stream (MCP 2025-11-25 Streamable
HTTP): for a long-running request the server emits
``notifications/progress`` events while the work runs, then the final
JSON-RPC response, then closes. Without that Accept header it returns a
single blocking ``application/json`` response, exactly as before.

Not yet implemented: server-initiated ``sampling`` (the server asking
the client's LLM to complete) — that needs a bidirectional channel and
is a separate follow-up.

Usage::

    MAVERICK_MCP_TOKEN=secret maverick mcp --http --port 8771

Security:
  - Bearer-token auth required when MAVERICK_MCP_TOKEN is set.
  - Per the 2025-11-25 spec, server runs as an OAuth resource server;
    full OAuth flow is a v0.3 follow-up. Bearer is the simpler path
    that works today.
  - All requests are routed through the same MCPServer.handle_*
    dispatch as stdio, so the security audit you do on the stdio
    side covers HTTP too.

Spec deprecation note: the older SSE-only transport is EOL mid-2026
across major clients; we ship Streamable HTTP as the GA transport.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import threading
import time
from collections import OrderedDict, deque
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_MAX_PROGRESS_TOKEN_CHARS = 128
_DEFAULT_MAX_PROGRESS_EVENTS = 240
_DEFAULT_MAX_RESOURCE_SESSIONS = 1024
_SESSION_COOKIE_MAX_AGE = 3600  # seconds; header-based clients re-mint freely
_LOOPBACK_PEERS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


try:
    from fastapi import FastAPI, Header, HTTPException, Request, Response
    from fastapi.responses import JSONResponse, StreamingResponse
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False
    FastAPI = Header = HTTPException = Request = Response = None  # type: ignore
    JSONResponse = StreamingResponse = None  # type: ignore


# JSON-RPC requests are small control messages. Cap the body so an
# (authenticated) client can't force the server to buffer an arbitrarily
# large payload in memory before dispatch. Override via MAVERICK_MCP_MAX_BODY.
def _max_body_bytes() -> int:
    try:
        return max(1024, int(os.environ.get("MAVERICK_MCP_MAX_BODY", str(2 * 1024 * 1024))))
    except ValueError:
        return 2 * 1024 * 1024


def _max_resource_sessions() -> int:
    try:
        configured = os.environ.get(
            "MAVERICK_MCP_MAX_RESOURCE_SESSIONS",
            str(_DEFAULT_MAX_RESOURCE_SESSIONS),
        )
        return max(1, int(configured))
    except ValueError:
        return _DEFAULT_MAX_RESOURCE_SESSIONS


async def _read_limited_json(request, http_exc):
    """Read + parse the JSON body with a hard size cap.

    Rejects oversized requests via Content-Length up front, then streams with
    the same cap so a chunked/lengthless request can't bypass it.
    """
    cap = _max_body_bytes()
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > cap:
                raise http_exc(status_code=413, detail="request body too large")
        except ValueError:
            raise http_exc(status_code=400, detail="invalid Content-Length") from None
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > cap:
            raise http_exc(status_code=413, detail="request body too large")
    try:
        return json.loads(buf or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise http_exc(status_code=400, detail="body must be valid JSON") from None


def _normalized_origin(origin: str) -> str | None:
    """Return a canonical Origin value, or None when malformed/unsupported."""
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        return None
    try:
        parsed_port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname.lower().rstrip(".")
    if ":" in host:
        host = f"[{host}]"
    port = f":{parsed_port}" if parsed_port is not None else ""
    return f"{parsed.scheme}://{host}{port}"


def _origin_host_is_loopback(origin: str) -> bool:
    parsed = urlparse(origin)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _allowed_origins() -> set[str]:
    """Explicit Origin values allowed for browser requests.

    Comma-separated list in MAVERICK_MCP_ALLOWED_ORIGINS (e.g. a gateway's
    public origin). Localhost/loopback Origins are also allowed for local
    browser clients. The request Host header is intentionally not trusted:
    DNS rebinding makes Host attacker-controlled for this defense.
    """
    raw = os.environ.get("MAVERICK_MCP_ALLOWED_ORIGINS", "")
    return {
        normalized
        for origin in raw.split(",")
        if (normalized := _normalized_origin(origin.strip()))
    }


def _is_origin_allowed(request) -> bool:
    """DNS-rebinding defense for the loopback HTTP transport.

    A browser page on any site can POST no-cors to http://127.0.0.1:8771,
    and DNS rebinding lets an attacker's hostname resolve to loopback. The
    bearer token is still the primary gate, but the Origin layer rejects
    browser requests unless they come from an explicit allowlist or from a
    literal localhost/loopback Origin.

    Requests with no Origin header (native MCP clients, curl, server-to-
    server) are allowed — like the dashboard, the Origin check only ever
    constrains browser-issued cross-origin requests; non-browser callers
    omit Origin and are gated by the bearer token instead.
    """
    origin = request.headers.get("origin")
    if not origin:
        return True
    normalized = _normalized_origin(origin)
    if not normalized:
        return False
    if _origin_host_is_loopback(normalized):
        return True
    return normalized in _allowed_origins()


def _is_loopback_request(request) -> bool:
    """True when the request's peer is loopback/in-process.

    Mirrors the dashboard: decides only the cookie ``Secure`` flag, so a
    real (non-loopback) deployment never sends the session cookie over
    plain HTTP, while loopback dev over http still works.
    """
    host = request.client.host if request.client else ""
    return host in _LOOPBACK_PEERS


def _http_tasks_enabled() -> bool:
    """Whether async MCP tasks are offered over the HTTP transport.

    Opt-in (default off): each HTTP caller gets an opaque MCP session id and
    task records are bound to that session, so tasks/list, tasks/get,
    tasks/result, and tasks/cancel only operate on the caller's own tasks.
    Set MAVERICK_MCP_HTTP_TASKS=1 to enable.
    """
    return os.environ.get("MAVERICK_MCP_HTTP_TASKS", "").strip().lower() in (
        "1", "true", "yes", "on")


# --- per-caller request rate limiting (sliding 60s window) -------------------
_RATE_LOCK = threading.Lock()
_RATE_HITS: dict[str, deque] = {}
# Cap the number of tracked callers so a long-running server facing many
# distinct IPs/tokens can't grow this map without bound. When exceeded, idle
# buckets (no hits inside the window) are swept; memory stays ~O(active callers).
_RATE_MAX_KEYS = 8192


def _rate_limit_per_min() -> int:
    """Requests/minute allowed per caller. Default 600; 0 disables. An authed
    caller can otherwise spam goal-spawning RPCs with unbounded concurrency."""
    try:
        return max(0, int(os.environ.get("MAVERICK_MCP_RATE_LIMIT", "600")))
    except ValueError:
        return 600


def _rate_key(authorization: str | None, request) -> str:
    """Bucket by bearer token (hashed) when present, else by client IP."""
    if authorization and authorization.startswith("Bearer "):
        tok = authorization[len("Bearer "):].strip()
        return "tok:" + hashlib.sha256(tok.encode("utf-8")).hexdigest()[:16]
    host = getattr(getattr(request, "client", None), "host", None) or "?"
    return "ip:" + str(host)


def _rate_ok(key: str) -> bool:
    """True if ``key`` is under its per-minute budget (and records the hit)."""
    limit = _rate_limit_per_min()
    if limit <= 0:
        return True
    now = time.monotonic()
    with _RATE_LOCK:
        cutoff = now - 60.0
        dq = _RATE_HITS.setdefault(key, deque())
        while dq and dq[0] < cutoff:
            dq.popleft()
        # Sweep idle buckets when the map grows large, so stale callers don't
        # leak. Keep the current key even if momentarily empty.
        if len(_RATE_HITS) > _RATE_MAX_KEYS:
            for k in [k for k, d in _RATE_HITS.items()
                      if k != key and (not d or d[-1] < cutoff)]:
                del _RATE_HITS[k]
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True


def _check_bearer(authorization: str | None) -> tuple[bool, str]:
    """Bearer-token gate for network HTTP transport.

    Returns ``(ok, caller_identity)`` -- ``caller_identity`` is the per-caller
    :class:`TrustedAgent` id when a per-caller ``[agent_trust] mcp_token``
    authenticated the request, or ``""`` for the shared ``MAVERICK_MCP_TOKEN``
    (which carries no per-caller identity). The transport binds this identity
    onto fleet-memory ops so a caller cannot act AS another rostered agent.

    Unlike stdio, HTTP requests are network-reachable; token auth is
    therefore mandatory. Two accepted credentials: the shared
    ``MAVERICK_MCP_TOKEN`` and a per-caller ``[agent_trust] mcp_token`` (real
    per-caller identity). On top of authentication, when the Agent Trust Plane
    is engaged the caller must be a permitted inbound agent — a per-caller token
    gates on its own entry, a shared-token caller on the surface-wide ``"mcp"``
    entry — so engaging the plane default-denies MCP instead of leaving it open
    on the shared bearer. No-op (auth only) when disengaged.
    """
    expected = os.environ.get("MAVERICK_MCP_TOKEN")
    given = ""
    if authorization and authorization.startswith("Bearer "):
        given = authorization[len("Bearer "):].strip()
    if not given:
        return False, ""
    agent = None
    try:
        from maverick.agent_trust import agent_for_token
        agent = agent_for_token(given, "mcp")
    except Exception:  # pragma: no cover - never break auth on a read error
        agent = None
    authed = bool(
        (expected and hmac.compare_digest(expected.encode(), given.encode()))
        or agent is not None
    )
    if not authed:
        return False, ""
    if not _mcp_trust_ok(agent):
        return False, ""
    return True, (agent.id if agent is not None else "")


def _mcp_trust_ok(agent) -> bool:
    """Agent Trust Plane admission for MCP. True to admit; default-deny (when
    engaged) for a caller that isn't a registered inbound agent."""
    try:
        from maverick import agent_trust
        enforced, registry = agent_trust.load_trust_state()
    except Exception:  # pragma: no cover - config read never breaks auth
        return True
    if not enforced:
        return True
    agent_id = agent.id if agent is not None else "mcp"
    decision = agent_trust.decide_inbound(agent_id, registry=registry, enforced=True)
    if decision.denied:
        agent_trust.record_denied(agent_id, decision, direction="inbound")
        return False
    return True


def _result_envelope(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_envelope(request_id, exc: Exception) -> dict:
    from .server import _ProtocolError
    from .tasks import TaskError
    # Both _ProtocolError and TaskError carry an explicit JSON-RPC (code,
    # message); preserve them so a task error (e.g. -32602 task not found)
    # reaches the HTTP client with the same wire code the stdio path produces.
    if isinstance(exc, (_ProtocolError, TaskError)):
        code, message = exc.code, exc.message
    else:
        # Scrub the message before it reaches the HTTP client: a raw exception's
        # args can carry secrets (DSNs, tokens, credentialed URLs). The stdio
        # dispatch path (server._dispatch) already scrubs the same class of
        # error; mirror it so both transports withhold the same internal detail.
        try:
            from maverick.secrets import scrub
            detail = scrub(f"{type(exc).__name__}: {exc}")
        except Exception:  # pragma: no cover - scrub must never mask the error
            detail = type(exc).__name__
        code, message = -32603, f"internal error: {detail}"
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def _sse(obj: dict) -> str:
    """Format a JSON-RPC message as one SSE event."""
    return f"data: {json.dumps(obj)}\n\n"


def _heartbeat_seconds() -> float:
    """Progress-heartbeat cadence for SSE streams. Override via
    MAVERICK_MCP_SSE_HEARTBEAT (seconds)."""
    try:
        return max(0.01, float(os.environ.get("MAVERICK_MCP_SSE_HEARTBEAT", "15")))
    except ValueError:
        return 15.0


def _max_progress_events() -> int:
    """Maximum number of progress events sent on one SSE response."""
    try:
        return max(0, int(os.environ.get(
            "MAVERICK_MCP_SSE_MAX_PROGRESS_EVENTS",
            str(_DEFAULT_MAX_PROGRESS_EVENTS),
        )))
    except ValueError:
        return _DEFAULT_MAX_PROGRESS_EVENTS


def _progress_token(params: dict, http_exc):
    """Return a bounded MCP progressToken or reject unsafe values.

    Progress tokens are echoed in every progress notification, so keep them
    scalar and small enough that heartbeats cannot amplify large request data.
    """
    meta = params.get("_meta") or {}
    if not isinstance(meta, dict):
        raise http_exc(status_code=400, detail="params._meta must be a JSON object")
    token = meta.get("progressToken")
    if token is None:
        return None
    if isinstance(token, bool) or not isinstance(token, (str, int, float)):
        raise http_exc(
            status_code=400,
            detail="params._meta.progressToken must be a string or number",
        )
    if len(str(token)) > _MAX_PROGRESS_TOKEN_CHARS:
        raise http_exc(
            status_code=400,
            detail=(
                "params._meta.progressToken must be "
                f"{_MAX_PROGRESS_TOKEN_CHARS} characters or fewer"
            ),
        )
    return token


def _sse_stream(
    *,
    server,
    method: str,
    params: dict,
    task_owner: str | None,
    caller_identity: str | None = None,
    subscriptions: set,
    request_id,
    should_persist_session: bool,
    sid: str | None,
    store_session,
):
    """Async SSE generator: progress heartbeats, then the final JSON-RPC result.

    Factored out of ``mcp_endpoint`` so the streaming branch's control flow does
    not inflate the endpoint's complexity. Behavior is identical.
    """
    progress_token = _progress_token(params, HTTPException)
    max_progress_events = _max_progress_events()

    def _dispatch_with_updates():
        with server.resource_update_scope(subscriptions):
            result = _dispatch(server, method, params, task_owner=task_owner,
                               caller_identity=caller_identity)
            updates = server.drain_resource_updates()
            return result, updates

    async def _stream():
        task = asyncio.create_task(asyncio.to_thread(_dispatch_with_updates))
        interval = _heartbeat_seconds()
        progress = 0
        while not task.done():
            done, _pending = await asyncio.wait({task}, timeout=interval)
            if task in done:
                break
            # Progress notifications are only valid when the client
            # supplied a token to correlate them (per spec).
            if progress_token is not None and progress < max_progress_events:
                progress += 1
                yield _sse({
                    "jsonrpc": "2.0",
                    "method": "notifications/progress",
                    "params": {
                        "progressToken": progress_token,
                        "progress": progress,
                        "message": "working",
                    },
                })
        try:
            result, updates = task.result()
        except Exception as e:
            yield _sse(_error_envelope(request_id, e))
        else:
            if should_persist_session and sid is not None:
                store_session(sid, subscriptions)
            yield _sse(_result_envelope(request_id, result))
            # HTTP analog of stdio's _flush_resource_updates: push any
            # resources/updated the tool dirtied that this client
            # subscribed to, on the same SSE stream, after the result.
            for uri in updates:
                yield _sse({
                    "jsonrpc": "2.0",
                    "method": "notifications/resources/updated",
                    "params": {"uri": uri},
                })

    return _stream()


def _supplied_session_id(request, resource_sessions: OrderedDict) -> str | None:
    supplied = (
        request.headers.get("Mcp-Session-Id")
        or request.cookies.get("maverick_mcp_session")
    )
    if supplied and supplied in resource_sessions:
        resource_sessions.move_to_end(supplied)
        return supplied
    return None


def _store_session(
    resource_sessions: OrderedDict, sid: str, subscriptions: set[str],
) -> None:
    resource_sessions[sid] = subscriptions
    resource_sessions.move_to_end(sid)
    while len(resource_sessions) > _max_resource_sessions():
        resource_sessions.popitem(last=False)


def _attach_session(response, sid: str | None, request):
    if sid is None:
        return response
    response.headers["Mcp-Session-Id"] = sid
    response.set_cookie(
        "maverick_mcp_session",
        sid,
        max_age=_SESSION_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=not _is_loopback_request(request),
    )
    return response


def build_app(server) -> FastAPI:
    """Wrap an MCPServer instance in a Streamable HTTP transport.

    `server` is an instance of `maverick_mcp.server.MCPServer`. We
    reuse its handle_* methods 1:1; this module is just the transport.
    """
    if not _HAVE_FASTAPI:
        raise ImportError(
            "fastapi not installed; install maverick-mcp-server[http] to enable "
            "the streamable HTTP transport"
        )

    app = FastAPI(
        title="Maverick MCP HTTP",
        description=(
            "MCP 2025-11-25 streamable HTTP transport. POST a JSON-RPC "
            "request; receive a JSON-RPC response or an SSE stream."
        ),
        version="0.2.0",
    )

    from maverick import a2a
    a2a.mount(app)

    # Offer async tasks over HTTP when opted in (MAVERICK_MCP_HTTP_TASKS). The
    # store lives on this server instance, so task records are bound to the
    # caller's opaque MCP session id before the client polls
    # tasks/get|result|cancel|list on later POSTs. Off by default -> task field
    # ignored and tasks/* return -32601, exactly as before.
    server._tasks_enabled = _http_tasks_enabled()

    # One MCPServer handles the whole HTTP app, but resource subscriptions and
    # async task records are per MCP HTTP client. Persist a small opaque session
    # id in both the standard-ish MCP-Session-Id header and a same-site cookie
    # fallback so clients that do not yet send a session header still get
    # isolated state. Sessions are created only when a request needs persistent
    # subscription/task state, and the map is capped so callers that ignore
    # returned ids cannot grow process memory without bound.
    resource_sessions: OrderedDict[str, set[str]] = OrderedDict()
    app.state.resource_sessions = resource_sessions

    @app.post("/mcp")
    async def mcp_endpoint(
        request: Request,
        authorization: str | None = Header(None),
    ):
        if not _is_origin_allowed(request):
            raise HTTPException(
                status_code=403,
                detail="cross-origin request blocked (set MAVERICK_MCP_ALLOWED_ORIGINS to allow)",
            )
        authed, caller_identity = _check_bearer(authorization)
        if not authed:
            raise HTTPException(status_code=401, detail="invalid bearer")
        # Per-caller rate limit (after auth so unauthenticated probes can't
        # exhaust a victim's budget). Returns 429 over the per-minute cap.
        if not _rate_ok(_rate_key(authorization, request)):
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        # Opt-in, consent-gated client-language analytics (off by default; no-op
        # and never raises when disabled). Feeds the language-bindings decision.
        try:
            from maverick.mcp_analytics import record_client
            record_client(request.headers.get("user-agent"))
        except Exception:  # pragma: no cover -- analytics never blocks a request
            pass
        # Bounded read (size cap) + parse; rejects oversized / malformed /
        # non-object bodies with a clean error instead of a 500.
        body = await _read_limited_json(request, HTTPException)
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        # Match the stdio transport: a JSON-RPC notification is a message with
        # NO id key. An explicit `"id": null` is a request still owed a reply,
        # so it must NOT be treated as a notification.
        is_notification = "id" not in body
        request_id = body.get("id")
        method = body.get("method", "")
        params = body.get("params", {}) or {}
        if not isinstance(params, dict):
            raise HTTPException(status_code=400, detail="params must be a JSON object")
        accepts_sse = "text/event-stream" in (request.headers.get("accept") or "")
        sid = _supplied_session_id(request, resource_sessions)
        subscriptions = resource_sessions[sid] if sid is not None else set()
        is_task_request = (
            server._tasks_enabled
            and (
                method.startswith("tasks/")
                or (method == "tools/call" and isinstance(params.get("task"), dict))
            )
        )
        should_persist_session = (
            method == "resources/subscribe" or sid is not None or is_task_request
        )
        if should_persist_session and sid is None:
            sid = secrets.token_urlsafe(24)
        task_owner = sid if is_task_request else None

        # Streamable HTTP: when the client accepts SSE and this is a real
        # request (not a fire-and-forget notification), stream progress
        # while the work runs, then the final JSON-RPC response. Dispatch
        # always goes to a worker thread -- the swarm tools call
        # run_goal_sync() -> asyncio.run, which can't run inline under
        # FastAPI's loop.
        if accepts_sse and not is_notification:
            # Streamable HTTP path: progress events while the work runs, then
            # the final JSON-RPC response, on one SSE stream.
            stream = _sse_stream(
                server=server,
                method=method,
                params=params,
                task_owner=task_owner,
                caller_identity=caller_identity,
                subscriptions=subscriptions,
                request_id=request_id,
                should_persist_session=should_persist_session,
                sid=sid,
                store_session=lambda s, subs: _store_session(resource_sessions, s, subs),
            )
            response = StreamingResponse(stream, media_type="text/event-stream")
            return _attach_session(response, sid, request)

        # Blocking JSON path (default). Dispatch runs in a worker thread
        # for the same asyncio.run reason as above.
        def _dispatch_for_session():
            with server.resource_update_scope(subscriptions):
                return _dispatch(server, method, params, task_owner=task_owner,
                                 caller_identity=caller_identity)

        try:
            result = await asyncio.to_thread(_dispatch_for_session)
        except Exception as e:
            if is_notification:
                # 204 must carry no body; JSONResponse({}) writes "{}" which
                # strict proxies (e.g. Cloudflare) reject as a protocol violation.
                return _attach_session(
                    Response(status_code=204),
                    sid,
                    request,
                )
            return _attach_session(
                JSONResponse(_error_envelope(request_id, e)),
                sid,
                request,
            )

        if should_persist_session and sid is not None:
            _store_session(resource_sessions, sid, subscriptions)

        if is_notification:
            # 204 must carry no body (see above).
            return _attach_session(Response(status_code=204), sid, request)
        return _attach_session(JSONResponse(_result_envelope(request_id, result)), sid, request)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "transport": "http"}

    return app


_METHOD_MAP = {
    "initialize":      "handle_initialize",
    "tools/list":      "handle_tools_list",
    "tools/call":      "handle_tools_call",
    "resources/list":  "handle_resources_list",
    "resources/read":  "handle_resources_read",
    "resources/subscribe":   "handle_resources_subscribe",
    "resources/unsubscribe": "handle_resources_unsubscribe",
    "prompts/list":    "handle_prompts_list",
    "prompts/get":     "handle_prompts_get",
    # Tasks (async, pollable). The handlers self-gate on _tasks_enabled and
    # return -32601 when tasks aren't enabled for this transport.
    "tasks/get":       "handle_tasks_get",
    "tasks/result":    "handle_tasks_result",
    "tasks/cancel":    "handle_tasks_cancel",
    "tasks/list":      "handle_tasks_list",
}


def _dispatch(
    server,
    method: str,
    params: dict,
    *,
    task_owner: str | None = None,
    caller_identity: str | None = None,
) -> dict:
    """Route a JSON-RPC method to the corresponding handle_* method.

    ``caller_identity`` (the authenticated per-caller agent id, ``""`` for the
    shared bearer) is bound for the duration of the handler so fleet-memory
    tools cannot act AS another rostered agent. Bound here -- inside the worker
    thread both dispatch paths funnel through -- so it cannot leak across
    concurrent requests (the ContextVar is set in this thread's context copy).
    """
    if method == "notifications/initialized":
        return {}
    if method == "ping":
        return {}
    handler_name = _METHOD_MAP.get(method)
    if not handler_name:
        from .server import _ProtocolError
        raise _ProtocolError(-32601, f"method not found: {method}")
    handler = getattr(server, handler_name)
    from maverick.fleet_memory import bind_caller
    with bind_caller(caller_identity):
        if method == "tools/call" or method.startswith("tasks/"):
            return handler(params, task_owner=task_owner)
        return handler(params)


def serve(host: str = "127.0.0.1", port: int = 8771) -> None:
    """Run the HTTP transport on host:port. Blocking."""
    from maverick.deployment import require_enterprise_or_die

    from .server import MCPServer

    require_enterprise_or_die()
    # build_app() raises a friendly "install maverick-mcp-server[http]" error
    # if fastapi is missing -- do it BEFORE importing uvicorn so the user
    # sees that hint, not a bare ModuleNotFoundError on uvicorn.
    server = MCPServer()
    app = build_app(server)
    try:
        import uvicorn
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "uvicorn not installed; install maverick-mcp-server[http] to enable "
            "the streamable HTTP transport"
        ) from e
    log.info("MCP Streamable HTTP transport on http://%s:%d/mcp", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
