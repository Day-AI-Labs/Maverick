"""Cross-agent message bus.

Lets agents in the same swarm communicate outside the parent/child
spawn relationship. Parent-child handoff is already covered by the
spawn tool's return value; this bus is for cousins / peers / debate
patterns where two agents at the same depth need to exchange info.

Storage: per-process in-memory queues, one per ``agent_id``. Reads
are blocking with timeout. Writes never block. Audit-logged for the
goal so the trace shows who-told-what-to-whom.

This is intentionally tiny. Just enough plumbing to enable a few
roadmap patterns (debate, supervisor-watch, cross-task negotiation)
without committing to a heavier message-passing framework.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass
class Message:
    sender: str
    recipient: str
    payload: Any
    ts: float = field(default_factory=time.time)
    correlation_id: Optional[str] = None  # threads request/response


_inboxes: dict[str, "queue.Queue[Message]"] = {}
_inboxes_lock = threading.Lock()


def _get_inbox(agent_id: str) -> "queue.Queue[Message]":
    """Get-or-create the inbox for an agent."""
    with _inboxes_lock:
        q = _inboxes.get(agent_id)
        if q is None:
            q = queue.Queue(maxsize=1000)
            _inboxes[agent_id] = q
        return q


def send(
    sender: str,
    recipient: str,
    payload: Any,
    *,
    correlation_id: Optional[str] = None,
    goal_id: Optional[int] = None,
) -> bool:
    """Deliver a message to ``recipient``'s inbox. Non-blocking.

    Returns True on success. If the recipient's inbox is full, the
    message is dropped and a warning is logged.
    """
    msg = Message(
        sender=sender, recipient=recipient,
        payload=payload, correlation_id=correlation_id,
    )
    inbox = _get_inbox(recipient)
    try:
        inbox.put_nowait(msg)
    except queue.Full:
        log.warning("agent_bus: inbox full for %s; dropping message", recipient)
        return False
    # Audit-log so the trace records inter-agent traffic. Fail-safe.
    try:
        from .audit import record
        record(
            "agent_message",
            agent=sender, goal_id=goal_id,
            recipient=recipient,
            correlation_id=correlation_id,
        )
    except Exception:  # pragma: no cover
        pass
    return True


def recv(
    agent_id: str,
    *,
    timeout: float = 0.0,
    correlation_id: Optional[str] = None,
) -> Optional[Message]:
    """Pull one message from ``agent_id``'s inbox.

    ``timeout`` 0 = non-blocking. >0 = block up to that many seconds.
    If ``correlation_id`` is given, filters for that id; non-matching
    messages are re-queued.
    """
    inbox = _get_inbox(agent_id)
    deadline = time.time() + max(0.0, timeout)
    # Non-matching messages are held aside (NOT re-queued one-by-one) so we
    # never: (a) drop a valid message belonging to another waiter when the
    # inbox is at maxsize, nor (b) re-read our own re-queued message ahead
    # of the target (busy-spin). Whatever we don't consume goes back at the
    # end, in original order.
    held: list[Message] = []
    found: Optional[Message] = None
    try:
        while True:
            try:
                msg = inbox.get(
                    block=timeout > 0,
                    timeout=max(0.001, deadline - time.time()),
                )
            except queue.Empty:
                break
            if correlation_id and msg.correlation_id != correlation_id:
                held.append(msg)
                if time.time() >= deadline:
                    break
                continue
            found = msg
            break
    finally:
        # Put the held (non-matching) messages back, in original order. We
        # only hold messages we dequeued, so under no concurrent producer
        # there's always room. A concurrent send() could still fill the
        # queue in between; that's a far narrower window than the old
        # per-message re-queue (which dropped on EVERY full inbox), and the
        # warning makes any residual loss visible instead of silent.
        for m in held:
            try:
                inbox.put_nowait(m)
            except queue.Full:  # pragma: no cover -- shouldn't happen; see above
                log.warning(
                    "agent_bus: inbox full re-queueing held message for %s",
                    agent_id,
                )
    return found


def peek(agent_id: str) -> int:
    """Count messages waiting in ``agent_id``'s inbox."""
    inbox = _get_inbox(agent_id)
    return inbox.qsize()


def clear(agent_id: Optional[str] = None) -> None:
    """Drop all messages. ``agent_id`` None = nuke every inbox."""
    with _inboxes_lock:
        if agent_id is None:
            _inboxes.clear()
            return
        _inboxes.pop(agent_id, None)


__all__ = ["Message", "send", "recv", "peek", "clear"]
