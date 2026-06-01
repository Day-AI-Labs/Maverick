"""Regression tests for bug-hunt wave-2 fixes (core).

- browser SSRF guard must block decimal/hex IP encodings of internal hosts.
- context_compactor must never drop a system message.
- tree_of_thought._score_candidates must not crash on an empty list.
"""
from __future__ import annotations


class TestBrowserSSRF:
    def test_decimal_and_loopback_blocked_public_allowed(self):
        from maverick.tools.browser import _is_safe_browser_url
        # Decimal/octal-int encodings of 127.0.0.1 resolve to loopback but
        # do not parse via ipaddress.ip_address -- the old literal-only
        # check let them through.
        assert _is_safe_browser_url("http://2130706433/") is False
        assert _is_safe_browser_url("http://127.0.0.1/") is False
        assert _is_safe_browser_url("http://localhost/") is False
        assert _is_safe_browser_url("https://example.com/") is True


class TestCompactorPreservesSystem:
    def test_system_message_never_dropped(self):
        from maverick.context_compactor import compact
        # One system message + many low-relevance head turns + a tail. Force
        # a tiny budget so the culler would otherwise drop the system msg.
        msgs = [{"role": "system", "content": "CRITICAL SYSTEM RULES " * 50}]
        for i in range(20):
            msgs.append({"role": "user", "content": f"unrelated chatter {i} " * 20})
            msgs.append({"role": "assistant", "content": f"reply {i} " * 20})
        msgs.append({"role": "user", "content": "the current question"})
        res = compact(msgs, target_tokens=200, preserve_tail=2)
        roles = [m.get("role") for m in res.messages]
        assert "system" in roles, "system message was dropped"
        # And it is the same system content.
        sys_msgs = [m for m in res.messages if m.get("role") == "system"]
        assert sys_msgs and sys_msgs[0]["content"].startswith("CRITICAL SYSTEM RULES")


class TestToTScoreCandidatesEmpty:
    def test_empty_candidates_no_crash(self):
        from maverick.tree_of_thought import _score_candidates
        scores, winner, reason = _score_candidates(
            None, "goal", [], budget=None, model=None,
        )
        assert scores == []
        assert winner == 0
