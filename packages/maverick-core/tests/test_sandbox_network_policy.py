"""Per-tool network egress policy (ROADMAP 2028 H2)."""
from __future__ import annotations

from maverick.sandbox.network_policy import describe, host_allowed

_POLICY = {
    "http_fetch": {"allow_egress": ["api.github.com", "*.openai.com"]},
    "shell": {"deny_egress": ["*"]},
    "mixed": {"allow_egress": ["*.example.com"], "deny_egress": ["evil.example.com"]},
}


def test_no_policy_allows_all():
    assert host_allowed("anytool", "anywhere.com", {})
    assert host_allowed("anytool", "anywhere.com", _POLICY)  # tool not in policy


def test_allow_list_restricts():
    assert host_allowed("http_fetch", "api.github.com", _POLICY)
    assert host_allowed("http_fetch", "api.openai.com", _POLICY)  # glob
    assert not host_allowed("http_fetch", "evil.com", _POLICY)


def test_deny_all():
    assert not host_allowed("shell", "anything.com", _POLICY)


def test_deny_wins_over_allow():
    assert host_allowed("mixed", "good.example.com", _POLICY)
    assert not host_allowed("mixed", "evil.example.com", _POLICY)


def test_host_case_insensitive():
    assert host_allowed("http_fetch", "API.GitHub.com", _POLICY)


def test_trailing_root_dot_canonicalized_for_deny_rules():
    policy = {
        "http_fetch": {"deny_egress": ["pastebin.com", "*.example.com"]},
    }

    assert not host_allowed("http_fetch", "pastebin.com.", policy)
    assert not host_allowed("http_fetch", "evil.example.com.", policy)


def test_trailing_root_dot_canonicalized_for_allow_rules():
    policy = {
        "http_fetch": {"allow_egress": ["api.github.com.", "*.openai.com."]},
    }

    assert host_allowed("http_fetch", "api.github.com", policy)
    assert host_allowed("http_fetch", "api.openai.com.", policy)


def test_describe():
    assert "unrestricted" in describe("unknown", _POLICY)
    assert "allow=" in describe("http_fetch", _POLICY)
    assert "deny=" in describe("shell", _POLICY)
