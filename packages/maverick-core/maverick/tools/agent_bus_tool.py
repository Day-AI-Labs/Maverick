"""Cross-agent message-bus tools.

Agent-callable wrappers around ``maverick.agent_bus``. Let a running
agent push a message to a peer's inbox (``send_to_agent``) and drain
its own inbox (``recv_from_agent``). Both are bound to the current
agent's id so ``send`` records the right sender and ``recv`` reads the
right inbox — the agent never has to know (or spoof) ids.

The bus itself is per-process and in-memory; see ``agent_bus.py``.
"""
from __future__ import annotations

import asyncio
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


def recv_from_agent(agent_id: str, *, agent: Any = None) -> Tool:
    """Factory: ``recv_from_agent`` reading the current agent's inbox.

    When ``agent`` is supplied and the message is a signed handoff
    (``delegate_to_agent``), it is verified against the run's handoff authority
    and rendered as accepted-under-grant or rejected-with-reason; plain messages
    are returned as-is.
    """

    async def _run(args: dict[str, Any]) -> str:
        raw_timeout = args.get("timeout") or 0.0
        timeout = float(raw_timeout)
        if not math.isfinite(timeout):
            return "ERROR: timeout must be a finite number"
        timeout = min(max(0.0, timeout), MAX_RECV_TIMEOUT_SECONDS)
        from ..bus_handoff import authority_for, receive_handoff

        authority = authority_for(agent.ctx) if agent is not None else None
        # receive_handoff blocks on a threading.Queue for up to `timeout` seconds.
        # Run it off the event loop so a blocking wait here doesn't stall every
        # other concurrently-running agent/channel sharing it.
        delivery = await asyncio.to_thread(
            receive_handoff, authority, agent_id, timeout=timeout
        )
        if delivery is None:
            return "(no messages)"
        if delivery.is_handoff:
            v = delivery.verdict
            if v.ok:
                env = delivery.payload
                scope = ", ".join(sorted(env.required_tools)) or "the granted scope"
                return (
                    f"from {delivery.sender!r}: VERIFIED handoff — task={env.task!r}. "
                    f"You may run it under the delegated grant for {v.grant.principal!r} "
                    f"(scope: {scope}); nothing beyond it."
                )
            return (
                f"from {delivery.sender!r}: REJECTED handoff "
                f"({v.rule}: {v.reason}) — do not act on it."
            )
        return f"from {delivery.sender!r}: {delivery.payload!r}"

    return Tool(
        name="recv_from_agent",
        description=(
            "Pull one message from your own inbox on the cross-agent bus. "
            "Returns '(no messages)' when empty. Pass 'timeout' (seconds) "
            "to block waiting for a peer's message. A signed handoff from "
            "delegate_to_agent is verified before it is handed to you."
        ),
        input_schema=_RECV_SCHEMA,
        fn=_run,
    )


_DELEGATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "to_id": {
            "type": "string",
            "description": "Recipient agent id (e.g. 'analyst-1-ab12cd').",
        },
        "task": {
            "type": "string",
            "description": "The scoped sub-task to delegate to the peer.",
        },
        "tools": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Tool names to grant the recipient for this task — a SUBSET of "
                "your own. Omit to delegate under your inherited scope."
            ),
        },
    },
    "required": ["to_id", "task"],
}


def delegate_to_agent(agent: Any) -> Tool:
    """Factory: ``delegate_to_agent`` — hand a peer a *scoped, signed* sub-task.

    Unlike ``send_to_agent`` (a plain message), this mints a signed handoff
    carrying an **attenuated** capability (your grant, narrowed to ``tools`` and
    re-bound to the recipient) that the receiver verifies before acting — so the
    peer runs under exactly the authority you delegated, nothing more. Fails open
    to a plain message when capability enforcement is off / crypto is absent.
    """

    def _run(args: dict[str, Any]) -> str:
        to_id = (args.get("to_id") or "").strip()
        task = (args.get("task") or "").strip()
        if not to_id:
            return "ERROR: to_id is required"
        if not task:
            return "ERROR: task is required"
        raw_tools = args.get("tools") or []
        if not isinstance(raw_tools, list):
            return "ERROR: tools must be a list of tool names"
        tools = [str(t) for t in raw_tools]

        from ..bus_handoff import authority_for, send_handoff

        authority = authority_for(agent.ctx)
        sender_cap = getattr(agent, "capability", None)
        if authority is None or sender_cap is None:
            # Fail-open (kernel rule #1): no trust domain to sign/verify under, so
            # fall back to a plain, unverified bus message.
            ok = agent_bus.send(agent.name, to_id, {"task": task, "from": agent.name})
            if not ok:
                return f"ERROR: could not deliver to {to_id!r} (inbox full)"
            return (
                f"delegated to {to_id!r} as an UNVERIFIED message "
                f"(capability enforcement off): {task!r}"
            )
        # Attenuate this agent's own grant to the requested tools, re-bound to the
        # recipient principal (mint requires grant.principal == recipient).
        grant = sender_cap.attenuate(principal=to_id, allow=set(tools) or None)
        try:
            nonce = send_handoff(
                authority, sender=agent.name, recipient=to_id, grant=grant,
                task=task, required_tools=tuple(tools),
                goal_id=getattr(agent.ctx, "goal_id", None),
            )
        except Exception as e:  # mint/delivery failure -- surface, don't crash
            return f"ERROR: handoff not delivered: {e}"
        scope = ", ".join(tools) if tools else "your inherited scope"
        return (
            f"delegated to {to_id!r} under a SIGNED handoff (scope: {scope}); "
            f"they must verify it before acting. delivery id={nonce}"
        )

    return Tool(
        name="delegate_to_agent",
        description=(
            "Delegate a scoped sub-task to a peer agent with a SIGNED, attenuated "
            "capability they verify before acting (vs send_to_agent's plain "
            "message). Grant only the 'tools' the task needs — a subset of yours; "
            "the peer can never exceed it."
        ),
        input_schema=_DELEGATE_SCHEMA,
        fn=_run,
    )
