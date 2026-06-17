"""WebSocket tool: one-shot connect / send / receive over ws(s).

For agents that need to talk to a WebSocket endpoint (live APIs, dev servers)
without a full browser. A single ``request`` op connects, optionally sends a
message, reads one reply, and closes. Scheme is restricted to ``ws``/``wss`` and
the host runs through the same SSRF guard as ``http_fetch`` (private/loopback
hosts refused unless ``MAVERICK_FETCH_ALLOW_PRIVATE=1``). The host check runs
*before* importing the optional ``websockets`` dependency, so the SSRF guard is
testable without it. Requires ``pip install maverick-agent[websocket]``.
"""
from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

from . import Tool

_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "ws:// or wss:// URL"},
        "message": {"type": "string", "description": "text to send after connect"},
        "timeout": {"type": "number", "description": "seconds to await a reply (default 30)"},
        "recv": {"type": "boolean", "description": "wait for one reply (default true)"},
    },
    "required": ["url"],
}


def _check_url(url: str) -> str | None:
    """Return an error string if the URL is unsafe, else None."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("ws", "wss"):
        return f"ERROR: only ws/wss supported; got scheme={scheme!r}"
    if not parsed.hostname:
        return "ERROR: missing host in URL"
    from .http_fetch import is_blocked_host
    if is_blocked_host(parsed.hostname):
        return (f"ERROR: refusing to connect to {parsed.hostname!r}: resolves to a "
                "private/loopback/reserved address (SSRF guard). "
                "Set MAVERICK_FETCH_ALLOW_PRIVATE=1 to override.")
    return None


async def _run(args: dict[str, Any]) -> str:
    url = str(args.get("url") or "").strip()
    if not url:
        return "ERROR: url is required"
    bad = _check_url(url)
    if bad:
        return bad
    try:
        import websockets
    except ImportError:
        return ("ERROR: websockets not installed. "
                "Run: pip install 'maverick-agent[websocket]'")
    message = args.get("message")
    timeout = float(args.get("timeout") or 30)
    want_recv = args.get("recv", True)
    # SSRF: _check_url resolved the host once to validate it, but
    # websockets.connect(url) would re-resolve the SAME name independently --
    # a DNS-rebinding window (validate -> public IP, connect -> 169.254.169.254
    # / 127.0.0.1). Pin the connection to a single validated public IP (the
    # same defense _ssrf gives http_fetch/pdf_reader/...), keeping the original
    # hostname for the Host header and TLS SNI/cert validation on wss.
    from ._ssrf import BlockedHost, resolve_pinned_ip
    parsed = urlparse(url)
    try:
        pinned_ip = resolve_pinned_ip(parsed.hostname or "")
    except BlockedHost as e:
        return (f"ERROR: refusing to connect to {parsed.hostname!r}: {e} "
                "(SSRF guard). Set MAVERICK_FETCH_ALLOW_PRIVATE=1 to override.")
    scheme = (parsed.scheme or "").lower()
    connect_kwargs: dict[str, Any] = {
        "open_timeout": timeout,
        "host": pinned_ip,
        "port": parsed.port or (443 if scheme == "wss" else 80),
    }
    if scheme == "wss" and parsed.hostname:
        # Connect to the pinned IP but validate the cert against the real name.
        connect_kwargs["server_hostname"] = parsed.hostname
    try:
        async with websockets.connect(url, **connect_kwargs) as ws:
            if message is not None:
                await ws.send(str(message))
            if not want_recv:
                return "sent (no reply requested)"
            reply = await asyncio.wait_for(ws.recv(), timeout=timeout)
            if isinstance(reply, bytes):
                reply = reply.decode("utf-8", errors="replace")
            return str(reply)
    except asyncio.TimeoutError:
        return f"ERROR: timed out after {timeout}s waiting for a reply"
    except Exception as e:
        return f"ERROR: websocket failed: {type(e).__name__}: {e}"


def websocket_tool() -> Tool:
    return Tool(
        name="websocket",
        description=(
            "Connect to a ws:// or wss:// endpoint, optionally send a message, "
            "and read one reply. Input: url, message (optional), timeout, recv. "
            "Refuses private/loopback hosts (SSRF guard)."
        ),
        input_schema=_SCHEMA,
        fn=_run,
    )


__all__ = ["websocket_tool", "_check_url"]
