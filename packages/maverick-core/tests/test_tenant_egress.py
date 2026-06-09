"""Per-tenant egress policy plane (ROADMAP platform spine)."""
from __future__ import annotations

from maverick import tenant_egress as te


def test_no_policy_allows_all():
    assert te.host_allowed("example.com", policy={}) is True
    assert te.host_allowed("example.com", policy=None, tenant=None) is True


def test_deny_wins():
    pol = {"allow": ["*"], "deny": ["169.254.169.254", "*.evil.test"]}
    assert te.host_allowed("169.254.169.254", policy=pol) is False
    assert te.host_allowed("api.evil.test", policy=pol) is False
    assert te.host_allowed("api.good.test", policy=pol) is True


def test_nonempty_allow_restricts():
    pol = {"allow": ["api.acme.com", "*.acme-internal.net"]}
    assert te.host_allowed("api.acme.com", policy=pol) is True
    assert te.host_allowed("db.acme-internal.net", policy=pol) is True
    assert te.host_allowed("api.other.com", policy=pol) is False


def test_per_tenant_override_beats_default(monkeypatch):
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", lambda: {
        "egress": {"deny": ["metadata.internal"]},
        "tenancy": {"egress": {"acme": {"allow": ["api.acme.com"]}}},
    })
    # acme is restricted to its allow-list.
    assert te.host_allowed("api.acme.com", tenant="acme") is True
    assert te.host_allowed("api.other.com", tenant="acme") is False
    # beta has no override -> the default plane (deny metadata, else allow).
    assert te.host_allowed("metadata.internal", tenant="beta") is False
    assert te.host_allowed("anything.com", tenant="beta") is True


def test_egress_allowed_composes_tenant_and_tool(monkeypatch):
    import maverick.config as cfg
    # Tenant plane allows api.acme.com; tool policy denies it -> blocked (AND).
    monkeypatch.setattr(cfg, "load_config", lambda: {
        "tenancy": {"egress": {"acme": {"allow": ["api.acme.com", "api.ok.com"]}}},
        "sandbox": {"tool": {"http_fetch": {"deny_egress": ["api.acme.com"]}}},
    })
    assert te.egress_allowed("http_fetch", "api.acme.com", tenant="acme") is False
    # api.ok.com passes both layers.
    assert te.egress_allowed("http_fetch", "api.ok.com", tenant="acme") is True
    # A host the tenant plane forbids is blocked even if the tool allows it.
    assert te.egress_allowed("http_fetch", "api.other.com", tenant="acme") is False


def test_describe(monkeypatch):
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", lambda: {
        "tenancy": {"egress": {"acme": {"allow": ["api.acme.com"], "deny": ["*"]}}}
    })
    s = te.describe(tenant="acme")
    assert "allow=" in s and "deny=" in s


def test_http_fetch_uses_tenant_egress(monkeypatch):
    # The http_fetch chokepoint composes the tenant plane: a denied host is refused.
    import maverick.config as cfg
    monkeypatch.setattr(cfg, "load_config", lambda: {
        "egress": {"deny": ["blocked.test"]},
    })
    from maverick.tools.http_fetch import http_fetch
    out = http_fetch().fn({"url": "https://blocked.test/data"})
    assert isinstance(out, str) and "egress policy blocks" in out
