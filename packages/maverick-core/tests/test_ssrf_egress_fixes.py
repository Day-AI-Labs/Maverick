"""Bug-hunt fixes: SSRF punycode pin-bypass, GraphQL egress gap, and the
MAVERICK_ENTERPRISE truthy-word fail-open."""
from __future__ import annotations

import httpx
import pytest

# --- SSRF: IDN/punycode host must still be pinned (no rebinding bypass) -------

def test_request_host_matches_reconciles_idn_forms():
    from maverick.tools._ssrf import _request_host_matches
    req = httpx.Request("GET", "https://xn--e1afmkfd.xn--p1ai/x")  # punycode URL
    # httpx decodes url.host to Unicode; the validated host is the punycode form.
    assert _request_host_matches(req, "xn--e1afmkfd.xn--p1ai")
    assert not _request_host_matches(req, "evil.example.com")


def test_pinned_transport_refuses_mismatched_host():
    from maverick.tools._ssrf import BlockedHost, _PinnedTransport

    class _Inner:
        def handle_request(self, r):
            raise AssertionError("must not reach the inner transport on a mismatch")

    t = _PinnedTransport("good.example.com", "good.example.com", "1.2.3.4", _Inner())
    with pytest.raises(BlockedHost):
        t.handle_request(httpx.Request("GET", "https://evil.example.com/x"))


# --- enterprise: env truthy-word must not silently disable -------------------

def test_enterprise_recognizes_affirmatives_and_negatives(monkeypatch):
    from maverick import enterprise
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})
    for v in ("1", "true", "on", "yes", "enable", "enabled", "y", "t"):
        monkeypatch.setenv("MAVERICK_ENTERPRISE", v)
        assert enterprise.enterprise_enabled() is True, v
    for v in ("0", "false", "off", "no", "disable", "disabled"):
        monkeypatch.setenv("MAVERICK_ENTERPRISE", v)
        assert enterprise.enterprise_enabled() is False, v


def test_enterprise_ambiguous_env_falls_through_to_config(monkeypatch):
    from maverick import enterprise
    # An unrecognized env value must NOT silently disable the control: config decides.
    monkeypatch.setattr("maverick.config.load_config",
                        lambda *a, **k: {"enterprise": {"mode": True}})
    monkeypatch.setenv("MAVERICK_ENTERPRISE", "enabled-for-prod")
    assert enterprise.enterprise_enabled() is True


# --- GraphQL connector honours the enterprise tool-egress lock ---------------

def test_graphql_connector_egress_blocked_under_enterprise(monkeypatch):
    monkeypatch.delenv("MAVERICK_ENTERPRISE", raising=False)
    monkeypatch.setattr("maverick.config.load_config", lambda *a, **k: {})
    monkeypatch.setenv("ACME_GQL_URL", "https://acme.invalid/graphql")
    monkeypatch.setenv("ACME_GQL_TOKEN", "tok")
    from maverick.tools._rest_connector import make_graphql_tool
    tool = make_graphql_tool(name="acmegql", base_url_env="ACME_GQL_URL",
                             token_env="ACME_GQL_TOKEN", description="x")

    monkeypatch.setenv("MAVERICK_ENTERPRISE", "1")
    out = tool.fn({"query": "{ me { id } }"})
    assert out.startswith("ERROR:") and "enterprise mode" in out
