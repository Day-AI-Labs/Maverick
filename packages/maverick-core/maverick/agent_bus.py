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
import os
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

# An inbox is created lazily for any agent/recipient id that send/recv/peek
# touches and is never removed by the agents themselves. In a long-running
# process (e.g. `maverick serve`) every goal mints fresh per-run agent ids, and
# `send_to_agent` lets the model address arbitrary never-existing recipients,
# so without a bound `_inboxes` grows one Queue per distinct id for the whole
# process lifetime. Cap the registry and, when over it, evict EMPTY inboxes
# (an empty queue holds no undelivered messages, so dropping it loses nothing —
# a later touch just re-creates it). Non-empty inboxes are kept regardless so a
# pending message is never silently dropped here.
try:
    _MAX_INBOXES = max(64, int(os.environ.get("MAVERICK_AGENT_BUS_MAX_INBOXES", "4096") or "4096"))
except ValueError:
    _MAX_INBOXES = 4096


def _evict_empty_inboxes_locked() -> None:
    """Drop empty inboxes when over the cap. Caller holds ``_inboxes_lock``."""
    if len(_inboxes) <= _MAX_INBOXES:
        return
    for aid in [aid for aid, q in _inboxes.items() if q.empty()]:
        del _inboxes[aid]
        if len(_inboxes) <= _MAX_INBOXES:
            break


def _get_inbox(agent_id: str) -> queue.Queue[Message]:
    """Get-or-create the inbox for an agent."""
    with _inboxes_lock:
        q = _inboxes.get(agent_id)
        if q is None:
            if len(_inboxes) >= _MAX_INBOXES:
                _evict_empty_inboxes_locked()
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
    if correlation_id is None:
        try:
            return inbox.get(block=timeout > 0, timeout=max(0.0, timeout))
        except queue.Empty:
            return None

    # monotonic: this is an elapsed-time deadline, so a wall-clock NTP/DST jump
    # mustn't make recv block past (or return before) the requested timeout.
    deadline = time.monotonic() + max(0.0, timeout)

    # Scan the queue in place while holding Queue's mutex instead of pulling
    # non-matching messages into an unbounded side buffer. This preserves FIFO
    # for skipped messages, avoids temporary capacity expansion under producer
    # floods, and lets the explicit deadline check below cap total wait time
    # even when non-matching messages keep arriving.
    with inbox.not_empty:
        while True:
            for idx, msg in enumerate(inbox.queue):
                if msg.correlation_id == correlation_id:
                    del inbox.queue[idx]
                    inbox.not_full.notify()
                    return msg

            now = time.monotonic()
            if timeout <= 0 or now >= deadline:
                return None

            inbox.not_empty.wait(deadline - now)


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
