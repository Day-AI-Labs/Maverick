"""Department bundles: the specialist packs grouped into deployable teams."""
from __future__ import annotations

import pytest
from maverick import departments as dept
from maverick.domain import SUITE_PREFIXES, suite_for


def test_finance_is_a_department_with_finance_packs():
    d = dept.get_department("finance")
    assert d is not None
    assert d.title == "Finance"
    assert d.charter  # authored charter, non-empty
    assert d.headcount > 0
    # Every member resolves back to the finance suite.
    assert all(suite_for(name) == "finance" for name in d.members)
    # Roster is sorted and deduplicated.
    assert d.members == sorted(set(d.members))


def test_list_departments_covers_only_real_suites_sorted_by_title():
    depts = dept.list_departments()
    assert depts, "expected at least one populated department"
    titles = [d.title for d in depts]
    assert titles == sorted(titles)
    valid_suites = set(SUITE_PREFIXES.values())
    assert all(d.key in valid_suites for d in depts)
    # No empty departments are listed.
    assert all(d.headcount > 0 for d in depts)


def test_roster_returns_domain_profiles_for_the_team():
    profiles = dept.roster("finance")
    assert profiles
    names = {p.name for p in profiles}
    assert names == set(dept.get_department("finance").members)


def test_disabled_suite_drops_the_department():
    cfg = {"suites": {"finance": False}}
    keys = {d.key for d in dept.list_departments(cfg)}
    assert "finance" not in keys
    assert dept.get_department("finance", cfg) is None
    assert dept.roster("finance", cfg) == []


def test_unknown_suite_key_is_none():
    assert dept.get_department("not_a_suite") is None


def test_title_and_charter_fallback_for_unlabeled_suite():
    # A suite key with no SUITE_LABELS entry still gets a derived title.
    assert dept.department_title("some_new_suite") == "Some New Suite"
    assert dept.department_charter("some_new_suite") == ""


# --- deploy a department as a fleet (paid add-on) ---

def test_fleet_from_department_maps_packs_to_agents():
    d = dept.get_department("finance")
    fleet = dept.fleet_from_department(d, "user:alice")
    assert fleet.name == "dept-finance"
    assert fleet.owner == "user:alice"
    assert {a.name for a in fleet.agents} == set(d.members)
    # Every agent is scoped to the department's role and carries its charter line.
    assert all(a.role == "finance" for a in fleet.agents)
    assert any(a.description for a in fleet.agents)
    # Each agent is bound to its specialist pack (domain) for run-time capability.
    assert all(a.domain == a.name for a in fleet.agents)


def test_fleet_agent_domain_survives_serialization():
    from maverick.fleet import FleetAgent
    a = FleetAgent("finance_sox", "finance", "Reconcile", domain="finance_sox")
    assert FleetAgent.from_dict(a.to_dict()).domain == "finance_sox"
    # Backward compatible: a legacy agent dict with no domain reads as "".
    assert FleetAgent.from_dict({"name": "x", "role": "r"}).domain == ""


def test_deployed_agent_domain_narrows_capability():
    # The deployed agent's pack capability must only restrict the base grant.
    from maverick.capability import capability_from_config
    from maverick.domain import available_domains, domain_capability
    d = dept.get_department("finance")
    fleet = dept.fleet_from_department(d, "user:alice")
    agent = fleet.agents[0]
    prof = available_domains()[agent.domain]
    base = capability_from_config("agent:test", user_id="agent:test")
    bound = domain_capability(prof, base, "agent:test")
    # Bound grant can never permit a tool the pack denies.
    for denied in prof.deny_tools:
        assert denied in bound.deny_tools


def test_deploy_is_blocked_without_the_addon(monkeypatch):
    # Simulate a provisioned tenant whose plan lacks the entitlement.
    import maverick.billing as billing
    monkeypatch.setattr(billing, "feature_allowed", lambda feature, **kw: False)
    with pytest.raises(dept.EntitlementError) as exc:
        dept.deploy_department("finance", "user:alice", save=False)
    assert exc.value.feature == "departments"
    assert not dept.department_entitled("finance")


def test_deploy_allowed_per_department_grant(monkeypatch):
    import maverick.billing as billing
    # Only the per-department feature is granted, not the whole add-on.
    monkeypatch.setattr(billing, "feature_allowed",
                        lambda feature, **kw: feature == "department:finance")
    assert dept.department_entitled("finance")
    assert not dept.department_entitled("legal")
    fleet = dept.deploy_department("finance", "user:alice", save=False)
    assert fleet is not None and fleet.name == "dept-finance"


def test_deploy_saves_when_entitled(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MAVERICK_TENANT", raising=False)
    import maverick.billing as billing
    monkeypatch.setattr(billing, "feature_allowed", lambda feature, **kw: True)
    fleet = dept.deploy_department("finance", "user:alice")
    from maverick.fleet import load_fleet
    saved = load_fleet("dept-finance")
    assert saved is not None and saved.owner == "user:alice"
    assert {a.name for a in saved.agents} == {a.name for a in fleet.agents}


def test_deploy_unknown_department_is_none(monkeypatch):
    import maverick.billing as billing
    monkeypatch.setattr(billing, "feature_allowed", lambda feature, **kw: True)
    assert dept.deploy_department("not_a_dept", "user:alice", save=False) is None
