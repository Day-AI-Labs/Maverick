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
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class Message:
    sender: str
    recipient: str
    payload: Any
    ts: float = field(default_factory=time.time)
    correlation_id: str | None = None  # threads request/response


_inboxes: dict[str, queue.Queue[Message]] = {}
_inboxes_lock = threading.Lock()


def _get_inbox(agent_id: str) -> queue.Queue[Message]:
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
    correlation_id: str | None = None,
    goal_id: int | None = None,
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
    correlation_id: str | None = None,
) -> Message | None:
    """Pull one message from ``agent_id``'s inbox.

    ``timeout`` 0 = non-blocking. >0 = block up to that many seconds.
    If ``correlation_id`` is given, filters for that id; non-matching
    messages are re-queued.
    """
    inbox = _get_inbox(agent_id)
    # monotonic: this is an elapsed-time deadline, so a wall-clock NTP/DST jump
    # mustn't make recv block past (or return before) the requested timeout.
    deadline = time.monotonic() + max(0.0, timeout)
    # Non-matching messages are held aside and put back AFTER we stop pulling,
    # never re-queued mid-drain. The old code did `put_nowait` immediately,
    # which (a) silently DROPPED a valid message if the inbox was momentarily
    # full, (b) reordered it to the tail, and (c) busy-looped re-popping the
    # same held messages until the deadline. Holding them locally avoids all
    # three: nothing is lost, FIFO order is preserved, and each message is
    # examined at most once per call.
    held: list[Message] = []
    found: Message | None = None
    try:
        while True:
            try:
                msg = inbox.get(
                    block=timeout > 0,
                    timeout=max(0.001, deadline - time.monotonic()),
                )
            except queue.Empty:
                break
            if correlation_id and msg.correlation_id != correlation_id:
                held.append(msg)
                # No mid-loop deadline break: get()'s own timeout terminates the
                # loop (non-blocking -> Empty once drained; blocking -> Empty at
                # the deadline). An early break here would, with the default
                # timeout=0, stop after the first non-matching message and miss
                # a match sitting behind it.
                continue
            found = msg
            break
    finally:
        # Restore FIFO order. The held (earlier-than-match) messages must go
        # back AHEAD of whatever is still queued, but Queue can't prepend — so
        # drain the remainder and re-add held + remainder in original order.
        # put_nowait can't overflow: we re-add at most the count we removed.
        if held:
            remaining: list[Message] = []
            while True:
                try:
                    remaining.append(inbox.get_nowait())
                except queue.Empty:
                    break
            for m in (*held, *remaining):
                try:
                    inbox.put_nowait(m)
                except queue.Full:  # pragma: no cover -- capacity invariant holds
                    log.warning("agent_bus: inbox full restoring held message for %s", agent_id)
    return found


def peek(agent_id: str) -> int:
    """Count messages waiting in ``agent_id``'s inbox."""
    inbox = _get_inbox(agent_id)
    return inbox.qsize()


def clear(agent_id: str | None = None) -> None:
    """Drop all messages. ``agent_id`` None = nuke every inbox."""
    with _inboxes_lock:
        if agent_id is None:
            _inboxes.clear()
            return
        _inboxes.pop(agent_id, None)


__all__ = ["Message", "send", "recv", "peek", "clear"]
