"""Email channel v2: message threading + IMAP IDLE (push instead of poll).

Two additions over the poll-only :class:`~maverick_channels.email.EmailChannel`,
both dependency-free (stdlib only):

  * **Threading** — reconstruct a conversation tree from ``Message-ID`` /
    ``In-Reply-To`` / ``References`` headers (the JWZ approach, simplified), so a
    reply is grouped under the message it answers instead of arriving as an
    orphan. ``build_thread_tree`` / ``flatten_thread`` are pure and unit-tested.
  * **IDLE** — ``IdleSession`` drives the IMAP IDLE command over an injected
    connection (``send(bytes)`` + ``readline() -> bytes``), returning as soon as
    the server pushes an ``EXISTS``/``RECENT`` notification (new mail) rather
    than sleeping a fixed poll interval. The state machine is unit-tested against
    a fake transport — no live IMAP account needed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_MSGID_RE = re.compile(r"<[^>]+>")


def _ids(value: str | None) -> list[str]:
    """Extract ``<message-id>`` tokens from a header value."""
    return _MSGID_RE.findall(value or "")


def _first_id(value: str | None) -> str:
    ids = _ids(value)
    return ids[0] if ids else ""


@dataclass
class ThreadNode:
    message_id: str
    message: dict
    children: list[ThreadNode] = field(default_factory=list)


def _parent_of(msg: dict) -> str:
    """The message-id this message replies to: In-Reply-To, else last Reference."""
    irt = _first_id(msg.get("in_reply_to"))
    if irt:
        return irt
    refs = _ids(msg.get("references"))
    return refs[-1] if refs else ""


def build_thread_tree(messages: list[dict]) -> list[ThreadNode]:
    """Group ``messages`` into conversation trees.

    Each message is a dict with at least ``message_id`` and optionally
    ``in_reply_to`` / ``references``. Returns root nodes (messages with no known
    parent in the set), each with nested ``children`` ordered by appearance. A
    reply whose parent isn't present becomes its own root (orphan), so no message
    is dropped.
    """
    nodes: dict[str, ThreadNode] = {}
    order: list[str] = []
    for m in messages:
        mid = _first_id(m.get("message_id")) or m.get("message_id") or ""
        if not mid:
            continue
        nodes[mid] = ThreadNode(message_id=mid, message=m)
        order.append(mid)

    roots: list[ThreadNode] = []
    for mid in order:
        node = nodes[mid]
        parent_id = _parent_of(node.message)
        parent = nodes.get(parent_id) if parent_id else None
        if parent is not None and parent is not node:
            parent.children.append(node)
        else:
            roots.append(node)
    return roots


def flatten_thread(roots: list[ThreadNode]) -> list[tuple[int, ThreadNode]]:
    """Depth-first ``(depth, node)`` list of a thread tree (for rendering)."""
    out: list[tuple[int, ThreadNode]] = []

    def walk(node: ThreadNode, depth: int) -> None:
        out.append((depth, node))
        for child in node.children:
            walk(child, depth + 1)

    for root in roots:
        walk(root, 0)
    return out


class IdleSession:
    """Drive one IMAP IDLE wait over an injected transport.

    ``transport`` needs ``send(data: bytes)`` and ``readline() -> bytes`` (an
    ``imaplib`` connection's socket file satisfies this). ``wait_for_event``
    issues IDLE, waits for an untagged ``EXISTS``/``RECENT`` (new mail) or the
    transport signalling EOF/timeout, then sends ``DONE``. Returns True iff new
    mail was announced.
    """

    def __init__(self, transport, *, tag: str = "A001"):
        self.transport = transport
        self.tag = tag

    def wait_for_event(self, *, max_lines: int = 1000) -> bool:
        self.transport.send(f"{self.tag} IDLE\r\n".encode())
        new_mail = False
        for _ in range(max_lines):
            raw = self.transport.readline()
            if not raw:
                break  # EOF / connection closed
            line = raw.decode("utf-8", errors="replace").strip()
            up = line.upper()
            if "EXISTS" in up or "RECENT" in up:
                new_mail = True
                break
            if up.startswith(f"{self.tag} ") and ("OK" in up or "BAD" in up):
                break  # server ended IDLE itself
        # Politely end IDLE.
        try:
            self.transport.send(b"DONE\r\n")
        except Exception:  # pragma: no cover -- transport already gone
            pass
        return new_mail


__all__ = ["ThreadNode", "build_thread_tree", "flatten_thread", "IdleSession"]
