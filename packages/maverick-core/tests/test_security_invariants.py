"""Cross-cutting security invariants — a single regression tripwire.

Each of these encodes a security contract that a red-team pass established and
that must NOT silently regress. They are deliberately fast, pure-function
assertions co-located so a reviewer can see the guarantees in one screen:

  * inbound signature verifiers FAIL CLOSED with no secret;
  * the sandbox child env is stripped of credential-shaped vars;
  * the SSRF guard refuses non-public addresses;
  * external MCP tool names are charset-validated before registration.

If you change one of these behaviours, you are changing a security guarantee
— update the contract deliberately, don't just make the test pass.
"""
from __future__ import annotations

import hashlib
import hmac
import socket

import pytest

# --- inbound webhook signature verifiers must fail closed ------------------

def test_github_app_signature_fails_closed_without_secret():
    from maverick.github_app import verify_signature
    assert verify_signature(b"{}", "sha256=whatever", None) is False
    assert verify_signature(b"{}", None, "") is False
    # Sanity: a correct signature with a secret still verifies.
    body = b'{"x":1}'
    sig = "sha256=" + hmac.new(b"s", body, hashlib.sha256).hexdigest()
    assert verify_signature(body, sig, "s") is True


def test_issue_webhook_signature_fails_closed_without_secret():
    from maverick.issue_webhooks import verify_signature
    assert verify_signature(b"{}", "deadbeef", None) is False
    assert verify_signature(b"{}", None, "s") is False


def test_outbound_webhook_verifier_rejects_unprefixed():
    from maverick.webhooks import verify_signature
    assert verify_signature(b"{}", "deadbeef", "s") is False  # no sha256= prefix
    assert verify_signature(b"{}", "", "s") is False


# --- sandbox child env must not carry credentials --------------------------

def test_scrub_env_strips_secret_shaped_vars():
    from maverick.sandbox.local import scrub_env
    src = {
        "ANTHROPIC_API_KEY": "sk-ant-secret",
        "GITHUB_TOKEN": "ghp_secret",
        "STRIPE_SECRET": "x",
        "DATABASE_URL": "postgres://u:p@h/db",
        "PATH": "/usr/bin",
        "HOME": "/home/u",
        "PLAIN_SETTING": "keep",
    }
    out = scrub_env(src)
    assert "ANTHROPIC_API_KEY" not in out
    assert "GITHUB_TOKEN" not in out
    assert "STRIPE_SECRET" not in out
    assert "DATABASE_URL" not in out  # connection string w/ embedded creds
    # Non-secret operational vars survive.
    assert out["PATH"] == "/usr/bin"
    assert out["HOME"] == "/home/u"
    assert out["PLAIN_SETTING"] == "keep"


# --- SSRF guard must refuse non-public addresses ---------------------------

def _fake_getaddrinfo(*ips):
    def _inner(host, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]
    return _inner


def test_ssrf_guard_refuses_loopback_and_metadata(monkeypatch):
    from maverick.tools._ssrf import BlockedHost, resolve_pinned_ip
    for ip in ("127.0.0.1", "169.254.169.254", "10.0.0.5", "::1"):
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(ip))
        with pytest.raises(BlockedHost):
            resolve_pinned_ip("attacker.test")
    # A public address resolves fine.
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    assert resolve_pinned_ip("example.com") == "93.184.216.34"


# --- external MCP tool names must be validated -----------------------------

def test_mcp_tool_names_are_validated():
    from types import SimpleNamespace

    from maverick.mcp_tools import tools_from_mcp
    client = SimpleNamespace(
        spec=SimpleNamespace(name="srv"),
        tools=[
            {"name": "ok_tool", "description": "d", "inputSchema": {}},
            {"name": "inject\nname", "description": "d", "inputSchema": {}},
            {"name": "evil__shadow", "description": "d", "inputSchema": {}},
        ],
        call_tool=None,
    )
    names = {t.name for t in tools_from_mcp(client)}
    assert names == {"mcp_srv__ok_tool"}
