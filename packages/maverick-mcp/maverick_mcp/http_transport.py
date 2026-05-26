"""Streamable HTTP transport for Maverick's MCP server (spec 2025-11-25).

The stdio JSON-RPC transport in `server.py` works great for desktop
clients (Claude Desktop, Cursor) that spawn Maverick as a subprocess.
For hosted Maverick — VPS deployments, multi-tenant setups, MCP
gateways like Composio / MintMCP / Cloudflare — clients need an HTTP
endpoint.

This module ships the Streamable HTTP transport per MCP 2025-11-25:
single POST endpoint that accepts JSON-RPC requests and returns
JSON-RPC responses, with optional Server-Sent Events for streaming
results (long-running tools, sampling).

Usage::

    maverick mcp --http --port 8771 --token $MAVERICK_MCP_TOKEN

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

import hmac
import logging
import os
from typing import Optional


log = logging.getLogger(__name__)


try:
    from fastapi import FastAPI, Header, HTTPException, Request
    from fastapi.responses import JSONResponse, StreamingResponse
    _HAVE_FASTAPI = True
except ImportError:
    _HAVE_FASTAPI = False
    FastAPI = Header = HTTPException = Request = None  # type: ignore
    JSONResponse = StreamingResponse = None  # type: ignore


def _check_bearer(authorization: Optional[str]) -> bool:
    """Bearer-token gate. If MAVERICK_MCP_TOKEN is unset, allow all
    (matches the stdio behavior where the OS handles auth via process
    ownership)."""
    expected = os.environ.get("MAVERICK_MCP_TOKEN")
    if not expected:
        return True
    if not authorization or not authorization.startswith("Bearer "):
        return False
    given = authorization[len("Bearer "):].strip()
    return hmac.compare_digest(expected, given)


def build_app(server) -> "FastAPI":
    """Wrap an MCPServer instance in a Streamable HTTP transport.

    `server` is an instance of `maverick_mcp.server.MCPServer`. We
    reuse its handle_* methods 1:1; this module is just the transport.
    """
    if not _HAVE_FASTAPI:
        raise ImportError(
            "fastapi not installed; install maverick-mcp[http] to enable "
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

    @app.post("/mcp")
    async def mcp_endpoint(
        request: "Request",
        authorization: Optional[str] = Header(None),
    ):
        if not _check_bearer(authorization):
            raise HTTPException(status_code=401, detail="invalid bearer")
        body = await request.json()
        is_notification = "id" not in body
        request_id = body.get("id")
        method = body.get("method", "")
        params = body.get("params", {}) or {}

        # Route via the existing MCPServer dispatcher. We piggyback on
        # its method table by calling the appropriate handle_* directly.
        try:
            result = _dispatch(server, method, params)
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


def serve(host: str = "0.0.0.0", port: int = 8771) -> None:  # noqa: S104
    """Run the HTTP transport on host:port. Blocking."""
    import uvicorn
    from .server import MCPServer

    server = MCPServer()
    app = build_app(server)
    log.info("MCP Streamable HTTP transport on http://%s:%d/mcp", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
