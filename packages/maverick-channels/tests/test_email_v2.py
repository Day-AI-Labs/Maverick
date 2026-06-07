"""Email channel v2: threading + IMAP IDLE (ROADMAP 2028 H2)."""
from __future__ import annotations

from maverick_channels.email_v2 import (
    IdleSession,
    build_thread_tree,
    flatten_thread,
)


def _msg(mid, irt=None, refs=None, subject=""):
    return {"message_id": f"<{mid}>", "subject": subject,
            "in_reply_to": f"<{irt}>" if irt else "",
            "references": " ".join(f"<{r}>" for r in (refs or []))}


def test_reply_nests_under_parent():
    msgs = [_msg("a"), _msg("b", irt="a"), _msg("c", irt="b")]
    roots = build_thread_tree(msgs)
    assert len(roots) == 1
    assert roots[0].message_id == "<a>"
    assert roots[0].children[0].message_id == "<b>"
    assert roots[0].children[0].children[0].message_id == "<c>"


def test_references_fallback_when_no_in_reply_to():
    msgs = [_msg("a"), _msg("b", refs=["a"])]
    roots = build_thread_tree(msgs)
    assert len(roots) == 1
    assert roots[0].children[0].message_id == "<b>"


def test_orphan_reply_becomes_root():
    # parent <x> not present in the set
    msgs = [_msg("b", irt="x")]
    roots = build_thread_tree(msgs)
    assert len(roots) == 1 and roots[0].message_id == "<b>"


def test_multiple_threads_and_flatten():
    msgs = [_msg("a"), _msg("b", irt="a"), _msg("c")]
    roots = build_thread_tree(msgs)
    assert len(roots) == 2
    flat = flatten_thread(roots)
    depths = {node.message_id: depth for depth, node in flat}
    assert depths["<a>"] == 0 and depths["<b>"] == 1 and depths["<c>"] == 0


class _FakeTransport:
    def __init__(self, lines):
        self._lines = list(lines)
        self.sent = []

    def send(self, data):
        self.sent.append(data)

    def readline(self):
        return self._lines.pop(0) if self._lines else b""


def test_idle_detects_new_mail():
    t = _FakeTransport([b"+ idling\r\n", b"* 3 EXISTS\r\n"])
    assert IdleSession(t).wait_for_event() is True
    assert t.sent[0] == b"A001 IDLE\r\n"
    assert t.sent[-1] == b"DONE\r\n"  # politely ended


def test_idle_returns_false_on_server_end():
    t = _FakeTransport([b"+ idling\r\n", b"A001 OK IDLE terminated\r\n"])
    assert IdleSession(t).wait_for_event() is False


def test_idle_returns_false_on_eof():
    t = _FakeTransport([b"+ idling\r\n"])  # then EOF
    assert IdleSession(t).wait_for_event() is False
