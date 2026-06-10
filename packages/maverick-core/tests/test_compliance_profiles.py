"""Tests for compliance mode profiles (HIPAA). Pure data + pure functions."""
from __future__ import annotations

from maverick import compliance_profiles as cp


def test_hipaa_profile_present_and_shaped():
    prof = cp.get_profile("HIPAA")  # case-insensitive
    assert prof is not None
    assert prof.key == "hipaa"
    assert "45 CFR" in prof.name
    assert cp.FLOOR_PII_REDACTION in prof.required_floors
    assert cp.FLOOR_ENCRYPTION_AT_REST in prof.required_floors


def test_hipaa_policy_requires_human_on_high_risk():
    pol = cp.compile_policy(["hipaa"])
    assert pol.require_human_min_risk == "high"


def test_unknown_profile_ignored():
    assert cp.get_profile("sox") is None
    pol = cp.compile_policy(["nope"])
    # empty policy: no enforcement
    assert pol.require_human_min_risk is None
    assert not pol.require_human_actions


def test_required_floors_union():
    floors = cp.required_floors(["hipaa", "unknown"])
    assert cp.FLOOR_EGRESS_LOCK in floors and cp.FLOOR_AUDIT_LOG in floors


def test_posture_report():
    out = cp.profile_posture(["hipaa"])
    assert "HIPAA" in out and "required floors:" in out
    assert "require-human at/above risk 'high'" in out
    assert cp.profile_posture([]) == "compliance profiles: none active"


def test_configured_profiles_reads_config(monkeypatch, tmp_path):
    import maverick.config as config_mod

    def _fake_load():
        return {"compliance": {"profiles": ["HIPAA", " ", "hipaa"]}}

    monkeypatch.setattr(config_mod, "load_config", _fake_load)
    assert cp.configured_profiles() == ["hipaa", "hipaa"]


def test_list_profiles():
    keys = {p.key for p in cp.list_profiles()}
    assert "hipaa" in keys


def test_from_config_unchanged_when_no_profiles(monkeypatch):
    """Default behavior is identical when [compliance] is unset."""
    import maverick.compliance_profiles as cpmod
    from maverick.governance import Policy

    monkeypatch.setattr(cpmod, "configured_profiles", lambda: [])
    pol = Policy.from_config()
    assert pol.require_human_min_risk is None
    assert not pol.require_human_actions


def test_from_config_hipaa_tightens_live_policy(monkeypatch):
    """[compliance] profiles=['hipaa'] folds require-human-on-high into the live policy."""
    import maverick.compliance_profiles as cpmod
    from maverick.governance import Decision, Policy, evaluate

    monkeypatch.setattr(cpmod, "configured_profiles", lambda: ["hipaa"])
    pol = Policy.from_config()
    assert pol.require_human_min_risk == "high"
    # A high-risk action now routes to a human under HIPAA mode.
    v = evaluate("shell", risk="high", policy=pol)
    assert v.decision == Decision.REQUIRE_HUMAN


def test_no_import_cycle():
    # Importing governance then compliance_profiles (and vice versa) must not cycle.
    import importlib
    importlib.import_module("maverick.governance")
    importlib.import_module("maverick.compliance_profiles")


def test_hipaa_required_floors_are_runtime_enforced(monkeypatch):
    """HIPAA-only config must fail closed instead of merely documenting floors."""
    import maverick.compliance_profiles as cpmod
    from maverick.audit.writer import _resolve_signing
    from maverick.crypto_at_rest import at_rest_enabled
    from maverick.enterprise import EgressBlocked, assert_provider_allowed, enterprise_enabled
    from maverick.privacy import anon_enabled

    monkeypatch.setattr(cpmod, "configured_profiles", lambda: ["hipaa"])
    for env in (
        "MAVERICK_ENTERPRISE",
        "MAVERICK_ENCRYPT_AT_REST",
        "MAVERICK_AUDIT_SIGN",
        "MAVERICK_ANON",
    ):
        monkeypatch.setenv(env, "0")

    assert enterprise_enabled() is True
    assert at_rest_enabled() is True
    assert _resolve_signing(False) is True
    assert anon_enabled() is True
    try:
        assert_provider_allowed("openai")
    except EgressBlocked:
        pass
    else:  # pragma: no cover - assertion path
        raise AssertionError("HIPAA egress lock allowed a cloud provider")
