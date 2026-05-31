"""Cross-agent message-bus tools.

Agent-callable wrappers around ``maverick.agent_bus``. Let a running
agent push a message to a peer's inbox (``send_to_agent``) and drain
its own inbox (``recv_from_agent``). Both are bound to the current
agent's id so ``send`` records the right sender and ``recv`` reads the
right inbox — the agent never has to know (or spoof) ids.

The bus itself is per-process and in-memory; see ``agent_bus.py``.
"""
from __future__ import annotations

import math
from typing import Any

from .. import agent_bus
from . import Tool

MAX_RECV_TIMEOUT_SECONDS = 5.0


_SEND_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "to_id": {
            "type": "string",
            "description": "Recipient agent id (e.g. 'coder-1-ab12cd').",
        },
        "payload": {
            "description": "Message body. Any JSON-serialisable value.",
        },
    },
    "required": ["to_id", "payload"],
}

_RECV_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "timeout": {
            "type": "number",
            "minimum": 0,
            "maximum": MAX_RECV_TIMEOUT_SECONDS,
            "description": (
                "Seconds to block waiting for a message (default 0 = non-blocking; "
                f"maximum {MAX_RECV_TIMEOUT_SECONDS:g})."
            ),
        },
    },
}


def send_to_agent(agent_id: str) -> Tool:
    """Factory: ``send_to_agent`` bound to the current agent as sender."""

    def _run(args: dict[str, Any]) -> str:
        to_id = (args.get("to_id") or "").strip()
        if not to_id:
            return "ERROR: to_id is required"
        if "payload" not in args:
            return "ERROR: payload is required"
        ok = agent_bus.send(agent_id, to_id, args["payload"])
        if not ok:
            return f"ERROR: could not deliver to {to_id!r} (inbox full)"
        return f"sent to {to_id!r}"

    return Tool(
        name="send_to_agent",
        description=(
            "Send a message to a peer agent's inbox via the cross-agent "
            "bus. Non-blocking. Use to coordinate with cousins/peers "
            "outside the parent/child spawn relationship."
        ),
        input_schema=_SEND_SCHEMA,
        fn=_run,
    )


def recv_from_agent(agent_id: str) -> Tool:
    """Factory: ``recv_from_agent`` reading the current agent's inbox."""

    def _run(args: dict[str, Any]) -> str:
        raw_timeout = args.get("timeout") or 0.0
        timeout = float(raw_timeout)
        if not math.isfinite(timeout):
            return "ERROR: timeout must be a finite number"
        timeout = min(max(0.0, timeout), MAX_RECV_TIMEOUT_SECONDS)
        msg = agent_bus.recv(agent_id, timeout=timeout)
        if msg is None:
            return "(no messages)"
        return f"from {msg.sender!r}: {msg.payload!r}"

    return Tool(
        name="recv_from_agent",
        description=(
            "Pull one message from your own inbox on the cross-agent bus. "
            "Returns '(no messages)' when empty. Pass 'timeout' (seconds) "
            "to block waiting for a peer's message."
        ),
        input_schema=_RECV_SCHEMA,
        fn=_run,
    )
