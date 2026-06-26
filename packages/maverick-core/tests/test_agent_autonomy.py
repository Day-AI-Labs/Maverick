"""Per-agent autonomy levels: rung mapping, per-risk overrides, onboarding
clamp, off-by-default, and the pack-schema + config binding."""
from __future__ import annotations

import pytest
from maverick.agent_autonomy import (
    AutonomyLevel,
    AutonomyProfile,
    clamp_down,
    parse_level,
    resolve,
)

# -- parsing ---------------------------------------------------------------

def test_parse_level_aliases():
    assert parse_level("auto") is AutonomyLevel.AUTO
    assert parse_level("autonomous") is AutonomyLevel.AUTO
    assert parse_level("human") is AutonomyLevel.SUGGEST
    assert parse_level("approve") is AutonomyLevel.REQUEST
    assert parse_level("read_only") is AutonomyLevel.OBSERVE


def test_parse_level_unknown_falls_through_to_default():
    assert parse_level("banana") is None
    assert parse_level("banana", AutonomyLevel.SUGGEST) is AutonomyLevel.SUGGEST
    assert parse_level(None) is None


def test_level_ordering():
    assert AutonomyLevel.OBSERVE.rank < AutonomyLevel.SUGGEST.rank
    assert AutonomyLevel.SUGGEST.rank < AutonomyLevel.REQUEST.rank
    assert AutonomyLevel.REQUEST.rank < AutonomyLevel.AUTO.rank


def test_clamp_down_floors_at_observe():
    assert clamp_down(AutonomyLevel.AUTO) is AutonomyLevel.REQUEST
    assert clamp_down(AutonomyLevel.REQUEST) is AutonomyLevel.SUGGEST
    assert clamp_down(AutonomyLevel.SUGGEST) is AutonomyLevel.OBSERVE
    assert clamp_down(AutonomyLevel.OBSERVE) is AutonomyLevel.OBSERVE
    assert clamp_down(AutonomyLevel.AUTO, 2) is AutonomyLevel.SUGGEST


# -- profile parsing -------------------------------------------------------

def test_profile_from_toml_defaults():
    p = AutonomyProfile.from_toml(None)
    assert p.default is AutonomyLevel.SUGGEST
    assert p.onboarding is True


def test_profile_from_toml_per_risk():
    p = AutonomyProfile.from_toml(
        {"default": "request", "low": "auto", "high": "human", "onboarding": False}
    )
    assert p.default is AutonomyLevel.REQUEST
    assert p.low is AutonomyLevel.AUTO
    assert p.high is AutonomyLevel.SUGGEST  # "human" alias
    assert p.medium is None
    assert p.onboarding is False
    assert p.level_for("low") is AutonomyLevel.AUTO
    assert p.level_for("medium") is AutonomyLevel.REQUEST  # falls to default
    assert p.level_for("high") is AutonomyLevel.SUGGEST


# -- resolution ------------------------------------------------------------

def test_disabled_always_suggests():
    """Off by default: any profile resolves to SUGGEST/require_human."""
    p = AutonomyProfile(default=AutonomyLevel.AUTO, onboarding=False)
    v = resolve(p, action="send_email", risk="low", levels_enabled=False)
    assert v.level is AutonomyLevel.SUGGEST
    assert v.decision == "require_human"
    assert v.execute_by == "human"


def test_enabled_auto_allows():
    p = AutonomyProfile(default=AutonomyLevel.AUTO, onboarding=False)
    v = resolve(p, action="send_email", risk="low", levels_enabled=True)
    assert v.level is AutonomyLevel.AUTO
    assert v.decision == "allow"
    assert v.autonomous is True


def test_request_requires_human_but_agent_executes():
    p = AutonomyProfile(default=AutonomyLevel.REQUEST, onboarding=False)
    v = resolve(p, risk="medium", levels_enabled=True)
    assert v.decision == "require_human"
    assert v.execute_by == "agent"
    assert v.needs_human is True


def test_observe_denies_actions():
    p = AutonomyProfile(default=AutonomyLevel.OBSERVE, onboarding=False)
    v = resolve(p, risk="high", levels_enabled=True)
    assert v.decision == "deny"
    assert v.execute_by == "none"


def test_per_risk_override_beats_default():
    p = AutonomyProfile(
        default=AutonomyLevel.AUTO, high=AutonomyLevel.SUGGEST, onboarding=False
    )
    assert resolve(p, risk="low", levels_enabled=True).decision == "allow"
    assert resolve(p, risk="high", levels_enabled=True).decision == "require_human"


def test_onboarding_clamps_one_rung():
    p = AutonomyProfile(default=AutonomyLevel.AUTO, onboarding=True)
    v = resolve(p, risk="low", levels_enabled=True)
    assert v.level is AutonomyLevel.REQUEST  # auto clamped down to request
    assert v.onboarding_clamped is True
    assert v.decision == "require_human"


def test_graduation_lifts_clamp():
    onboarding = AutonomyProfile(default=AutonomyLevel.AUTO, onboarding=True)
    graduated = AutonomyProfile(default=AutonomyLevel.AUTO, onboarding=False)
    assert resolve(onboarding, risk="low", levels_enabled=True).decision == "require_human"
    assert resolve(graduated, risk="low", levels_enabled=True).decision == "allow"


# -- pack schema binding ---------------------------------------------------

def test_domain_profile_parses_autonomy_block(tmp_path):
    from maverick.domain import load_domain

    pack = tmp_path / "demo.toml"
    pack.write_text(
        'name = "demo"\npersona = "x"\n'
        'allow_tools = ["read_file"]\n'
        "[autonomy]\ndefault = \"request\"\nhigh = \"human\"\nonboarding = false\n"
    )
    prof = load_domain(pack)
    assert prof.autonomy.default is AutonomyLevel.REQUEST
    assert prof.autonomy.high is AutonomyLevel.SUGGEST
    assert prof.autonomy.onboarding is False


def test_domain_profile_no_block_is_none_falls_to_suite_default(tmp_path):
    from maverick.agent_autonomy import default_profile_for, effective_profile
    from maverick.domain import load_domain

    pack = tmp_path / "bare.toml"
    pack.write_text('name = "bare"\npersona = "x"\nallow_tools = ["read_file"]\n')
    prof = load_domain(pack)
    assert prof.autonomy is None  # no explicit block
    # an unknown/legacy pack falls to STRICT (SUGGEST, supervised)
    assert effective_profile("bare", prof.autonomy).default is AutonomyLevel.SUGGEST
    assert default_profile_for("bare").default is AutonomyLevel.SUGGEST


def test_suite_default_tiers():
    """High-stakes suites -> STRICT (suggest); operational -> STANDARD (request)."""
    from maverick.agent_autonomy import default_profile_for

    assert default_profile_for("fin_ap_clerk").default is AutonomyLevel.SUGGEST  # finance
    assert default_profile_for("legal_contract").default is AutonomyLevel.SUGGEST  # legal
    ops = default_profile_for("cx_ticket_triage")  # customer_experience -> STANDARD
    assert ops.default is AutonomyLevel.REQUEST
    assert ops.low is AutonomyLevel.AUTO
    assert ops.high is AutonomyLevel.SUGGEST


# -- config override binding -----------------------------------------------

def test_client_override_layers_over_pack(monkeypatch):
    import maverick.agent_autonomy as aa

    pack = AutonomyProfile(default=AutonomyLevel.SUGGEST, onboarding=True)
    monkeypatch.setattr(
        aa, "effective_profile",
        lambda n, p: AutonomyProfile(default=AutonomyLevel.AUTO, onboarding=False),
        raising=True,
    )
    # decide() reads levels_enabled too; force it on.
    monkeypatch.setattr(aa, "levels_enabled", lambda: True, raising=True)
    v = aa.decide("fin_ap_clerk", pack, risk="low")
    assert v.decision == "allow"


def test_effective_profile_applies_config_override(monkeypatch):
    import maverick.agent_autonomy as aa

    monkeypatch.setattr(
        "maverick.config.get_workforce",
        lambda: {"levels": True, "agents": {"clerk": {"default": "auto", "onboarding": False}}},
    )
    pack = AutonomyProfile(default=AutonomyLevel.SUGGEST, onboarding=True)
    eff = aa.effective_profile("clerk", pack)
    assert eff.default is AutonomyLevel.AUTO
    assert eff.onboarding is False
    # an agent with no override keeps the pack profile
    assert aa.effective_profile("other", pack).default is AutonomyLevel.SUGGEST


def test_decide_off_by_default(monkeypatch):
    import maverick.agent_autonomy as aa

    monkeypatch.setattr("maverick.config.get_workforce", lambda: {"levels": False, "agents": {}})
    monkeypatch.delenv("MAVERICK_WORKFORCE_LEVELS", raising=False)
    p = AutonomyProfile(default=AutonomyLevel.AUTO, onboarding=False)
    assert aa.decide("x", p, risk="low").decision == "require_human"


# -- prompt rendering ------------------------------------------------------

def test_render_empty_when_disabled(monkeypatch):
    import maverick.agent_autonomy as aa

    monkeypatch.setattr(aa, "levels_enabled", lambda: False)
    assert aa.render_autonomy_prompt("x", AutonomyProfile(default=AutonomyLevel.AUTO)) == ""


def test_render_describes_each_tier_when_enabled(monkeypatch):
    import maverick.agent_autonomy as aa

    monkeypatch.setattr(aa, "levels_enabled", lambda: True)
    monkeypatch.setattr(aa, "effective_profile", lambda n, p: p)
    p = AutonomyProfile(default=AutonomyLevel.AUTO, high=AutonomyLevel.SUGGEST, onboarding=False)
    out = aa.render_autonomy_prompt("demo", p)
    assert "low-risk actions: execute it autonomously" in out
    assert "high-risk actions: prepare and stage it" in out
    assert "ONBOARDING" not in out


def test_render_flags_onboarding(monkeypatch):
    import maverick.agent_autonomy as aa

    monkeypatch.setattr(aa, "levels_enabled", lambda: True)
    monkeypatch.setattr(aa, "effective_profile", lambda n, p: p)
    out = aa.render_autonomy_prompt("demo", AutonomyProfile(default=AutonomyLevel.AUTO, onboarding=True))
    assert "ONBOARDING" in out
    # AUTO clamped to REQUEST under onboarding
    assert "after a human approves" in out


# -- dial-coupled governed action grant ------------------------------------

def _pack(tmp_path):
    from maverick.domain import load_domain

    p = tmp_path / "p.toml"
    p.write_text(
        'name = "fin_clerk"\npersona = "x"\n'
        'allow_tools = ["read_file", "sql_query"]\nmax_risk = "medium"\n'
    )
    return load_domain(p)


def test_action_grant_off_by_default(monkeypatch, tmp_path):
    from maverick.domain import domain_capability

    monkeypatch.delenv("MAVERICK_WORKFORCE_LEVELS", raising=False)
    monkeypatch.setattr("maverick.config.get_workforce", lambda: {"levels": False, "agents": {}})
    cap = domain_capability(_pack(tmp_path), None, "agent:fin_clerk")
    assert not cap.permits("email")          # read-only: no action bundle
    assert cap.max_risk == "medium"          # ceiling unchanged
    assert cap.permits("read_file")


def test_action_grant_when_levels_on(monkeypatch, tmp_path):
    from maverick.domain import domain_capability

    monkeypatch.setenv("MAVERICK_WORKFORCE_LEVELS", "1")
    monkeypatch.setattr("maverick.config.get_workforce", lambda: {"levels": True, "agents": {}})
    cap = domain_capability(_pack(tmp_path), None, "agent:fin_clerk")
    assert cap.permits("email")              # governed action bundle granted
    assert cap.permits("notify")
    assert cap.permits("calendar")
    assert cap.max_risk == "high"            # ceiling lifted; the dial now governs
    assert cap.permits("read_file")          # reads still fine


def test_action_grant_does_not_lift_existing_high_risk_tools(monkeypatch, tmp_path):
    from maverick.domain import domain_capability

    monkeypatch.setenv("MAVERICK_WORKFORCE_LEVELS", "1")
    monkeypatch.setattr("maverick.config.get_workforce", lambda: {"levels": True, "agents": {}})
    cap = domain_capability(_pack(tmp_path), None, "agent:fin_clerk")
    assert cap.permits("email")
    assert cap.permits("notify")
    assert cap.permits("calendar")
    assert cap.max_risk == "high"
    assert cap.permits("read_file")
    assert not cap.permits("sql_query")


# -- graduation (onboarding -> trusted) ------------------------------------

def _approval(agent, status):
    return {"requested_by": f"agent:{agent}-0", "action": "email", "risk": "high",
            "status": status}


def test_graduation_needs_min_sample():
    from maverick.agent_autonomy import graduation_status

    hist = [_approval("clerk", "approved") for _ in range(5)]  # < min_sample (8)
    v = graduation_status("clerk", hist)
    assert v.graduated is False
    assert v.sample == 5


def test_graduation_on_clean_record():
    from maverick.agent_autonomy import graduation_status

    hist = [_approval("clerk", "approved") for _ in range(10)]
    v = graduation_status("clerk", hist)
    assert v.graduated is True
    assert v.approve_rate == 1.0
    assert v.sample == 10


def test_graduation_blocked_by_denials():
    from maverick.agent_autonomy import graduation_status

    hist = ([_approval("clerk", "approved") for _ in range(7)]
            + [_approval("clerk", "denied") for _ in range(3)])  # 70% < 90%
    v = graduation_status("clerk", hist)
    assert v.graduated is False


def test_graduation_filters_by_agent():
    from maverick.agent_autonomy import graduation_status

    hist = ([_approval("clerk", "approved") for _ in range(10)]
            + [_approval("other", "denied") for _ in range(10)])
    assert graduation_status("clerk", hist).graduated is True   # other's denials don't count
    assert graduation_status("other", hist).graduated is False


def test_graduation_candidates_sorted():
    from maverick.agent_autonomy import graduation_candidates

    hist = ([_approval("a", "approved") for _ in range(10)]
            + [_approval("b", "approved") for _ in range(4)])  # b under sample
    cands = graduation_candidates(hist, ["a", "b"])
    assert [c.name for c in cands] == ["a"]


def test_effective_profile_graduated_lifts_onboarding():
    from maverick.agent_autonomy import effective_profile

    pack = AutonomyProfile(default=AutonomyLevel.AUTO, onboarding=True)
    assert effective_profile("x", pack).onboarding is True
    assert effective_profile("x", pack, graduated=True).onboarding is False


def test_coerce_approvals_from_objects():
    """A list of Approval-like objects (not dicts) is read via __dict__."""
    from maverick.agent_autonomy import graduation_status

    class _A:
        def __init__(self):
            self.requested_by = "agent:clerk-0"
            self.action = "email"
            self.risk = "high"
            self.status = "approved"
    v = graduation_status("clerk", [_A() for _ in range(9)])
    assert v.graduated is True


# -- coordination floor (agents can always communicate) --------------------

def test_capability_permits_coordination_despite_narrow_allowlist():
    """A specialist with a narrow allowlist and a low risk ceiling still keeps
    the workforce control-plane (spawn/bus/delegate), even under enforcement."""
    from maverick.capability import COORDINATION_TOOLS, Capability

    cap = Capability(
        principal="agent:fin_clerk-0",
        allow_tools=frozenset({"read_file", "sql_query"}),
        max_risk="low",  # spawn_specialist is high-risk, yet must still pass
    )
    for t in COORDINATION_TOOLS:
        assert cap.permits(t), f"{t} should be permitted (coordination floor)"
    assert cap.permits("read_file")
    assert not cap.permits("email")  # non-coordination, not in allowlist


def test_coordination_floor_respects_deny():
    """deny_tools still wins -- an operator can revoke a coordination tool."""
    from maverick.capability import Capability

    cap = Capability(
        principal="x", allow_tools=frozenset({"read_file"}),
        deny_tools=frozenset({"spawn_swarm"}),
    )
    assert not cap.permits("spawn_swarm")
    assert cap.permits("spawn_specialist")  # others still permitted


def test_domain_agent_coordinates_under_enforcement():
    from pathlib import Path

    import maverick.domain as d
    from maverick.capability import COORDINATION_TOOLS
    from maverick.domain import domain_capability, load_domains

    packs = load_domains(Path(d.__file__).parent / "domains")
    # any read-only specialist with a narrow allowlist
    name = next(iter(packs))
    cap = domain_capability(packs[name], None, f"agent:{name}-0")
    assert all(cap.permits(t) for t in COORDINATION_TOOLS)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
