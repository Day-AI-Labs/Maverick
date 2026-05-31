"""Streamable HTTP transport for Maverick's MCP server (spec 2025-11-25).

The stdio JSON-RPC transport in `server.py` works great for desktop
clients (Claude Desktop, Cursor) that spawn Maverick as a subprocess.
For hosted Maverick — VPS deployments, multi-tenant setups, MCP
gateways like Composio / MintMCP / Cloudflare — clients need an HTTP
endpoint.

This module ships a single POST endpoint that accepts JSON-RPC
requests and returns JSON-RPC responses synchronously. The MCP
2025-11-25 Streamable HTTP spec also allows Server-Sent Events for
streaming results (long-running tools, sampling); that SSE path is
NOT implemented yet — every request gets one blocking JSON-RPC
response. Clients that need streaming should not assume it here.

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
import hmac
import json
import logging
import os

log = logging.getLogger(__name__)


try:
    from fastapi import FastAPI, Header, HTTPException, Request
    from fastapi.responses import JSONResponse, StreamingResponse
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False
    FastAPI = Header = HTTPException = Request = None  # type: ignore
    JSONResponse = StreamingResponse = None  # type: ignore


# JSON-RPC requests are small control messages. Cap the body so an
# (authenticated) client can't force the server to buffer an arbitrarily
# large payload in memory before dispatch. Override via MAVERICK_MCP_MAX_BODY.
def _max_body_bytes() -> int:
    try:
        return max(1024, int(os.environ.get("MAVERICK_MCP_MAX_BODY", str(2 * 1024 * 1024))))
    except ValueError:
        return 2 * 1024 * 1024


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
            raise http_exc(status_code=400, detail="invalid Content-Length")
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > cap:
            raise http_exc(status_code=413, detail="request body too large")
    try:
        return json.loads(buf or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise http_exc(status_code=400, detail="body must be valid JSON")


def _check_bearer(authorization: str | None) -> bool:
    """Bearer-token gate for network HTTP transport.

    Unlike stdio, HTTP requests are network-reachable; token auth is
    therefore mandatory and a missing MAVERICK_MCP_TOKEN rejects all
    requests.
    """
    expected = os.environ.get("MAVERICK_MCP_TOKEN")
    if not expected:
        return False
    if not authorization or not authorization.startswith("Bearer "):
        return False
    given = authorization[len("Bearer "):].strip()
    return hmac.compare_digest(expected, given)


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

    @app.post("/mcp")
    async def mcp_endpoint(
        request: Request,
        authorization: str | None = Header(None),
    ):
        if not _check_bearer(authorization):
            raise HTTPException(status_code=401, detail="invalid bearer")
        body = await _read_limited_json(request, HTTPException)
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        is_notification = "id" not in body
        request_id = body.get("id")
        method = body.get("method", "")
        params = body.get("params", {}) or {}

        # Route via the existing MCPServer dispatcher. The dispatch is
        # SYNCHRONOUS and the swarm tools call run_goal_sync() -> asyncio.run,
        # which raises "asyncio.run() cannot be called from a running event
        # loop" if invoked inline under FastAPI's loop. Run it in a worker
        # thread so it gets its own loop; this fixes maverick_start /
        # maverick_resume over HTTP (they were completely broken).
        try:
            result = await asyncio.to_thread(_dispatch, server, method, params)
        except Exception as e:
            from .server import _ProtocolError
            if isinstance(e, _ProtocolError):
                code, message = e.code, e.message
            else:
                code, message = -32603, f"internal error: {e}"
            if is_notification:
                return JSONResponse({}, status_code=204)
            return JSONResponse({
                "jsonrpc": "2.0", "id": request_id,
                "error": {"code": code, "message": message},
            })

        if is_notification:
            return JSONResponse({}, status_code=204)
        return JSONResponse({
            "jsonrpc": "2.0", "id": request_id, "result": result,
        })

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
    "prompts/list":    "handle_prompts_list",
    "prompts/get":     "handle_prompts_get",
}


def _dispatch(server, method: str, params: dict) -> dict:
    """Route a JSON-RPC method to the corresponding handle_* method."""
    if method == "notifications/initialized":
        return {}
    if method == "ping":
        return {}
    handler_name = _METHOD_MAP.get(method)
    if not handler_name:
        from .server import _ProtocolError
        raise _ProtocolError(-32601, f"method not found: {method}")
    handler = getattr(server, handler_name)
    return handler(params)


def serve(host: str = "127.0.0.1", port: int = 8771) -> None:
    """Run the HTTP transport on host:port. Blocking."""
    from .server import MCPServer

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
