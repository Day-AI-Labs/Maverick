"""Read-seat rollout across the non-finance suites.

The connector seats remain registered so high-trust workflows can still opt into
suite data, but GET-only access to arbitrary enterprise API paths is not treated
as low confidentiality risk by default. Identity, HR, security, CI/CD, legal,
customer, and BI systems fail closed as high risk unless an operator deliberately
adds an exact risk override.
"""
from __future__ import annotations

from maverick.capability import Capability
from maverick.domain import builtin_dir, domain_capability, load_domains
from maverick.safety.tool_risk import tool_risk
from maverick.tools.enterprise_connectors import READ_CONNECTOR_NAMES, READ_CONNECTOR_RISKS

# one representative (pack -> read seat) per suite
_SAMPLES = {
    "gtm_outbound_sdr": "salesloft_read",
    "legal_contract_drafting": "ironclad_read",
    "ops_transportation": "flexport_read",
    "hr_recruiting_ops": "greenhouse_read",
    "itgrc_vuln_mgmt": "qualys_read",
    "pe_cicd": "jenkins_read",
    "strat_competitive_intel": "crunchbase_read",
}

_SENSITIVE_EXAMPLES = {
    "bamboohr_read",
    "cyberark_read",
    "okta_read",
    "splunk_read",
    "crowdstrike_read",
    "jenkins_read",
}


def test_each_suite_pack_lists_its_read_seat_but_low_ceiling_blocks_it():
    d = load_domains(builtin_dir())
    low_parent = Capability(principal="agent:low-risk-channel-0", max_risk="low")
    for pack, seat in _SAMPLES.items():
        assert seat in d[pack].allow_tools, f"{pack} no longer declares read seat {seat}"
        cap = domain_capability(d[pack], low_parent, f"agent:{pack}-1")
        assert not cap.permits(seat), f"{pack} must not reach high-risk read seat {seat}"
        assert tool_risk(seat) == "high", f"{seat} must not bypass low-risk ceilings"


def test_pam_domain_does_not_grant_cyberark_read_under_low_risk_ceiling():
    d = load_domains(builtin_dir())
    parent = Capability(principal="agent:supervisor-0", max_risk="high")
    cap = domain_capability(d["itgrc_pam"], parent, "agent:itgrc_pam-1")
    assert "cyberark_read" in d["itgrc_pam"].allow_tools
    assert tool_risk("cyberark_read") == "high"
    assert not cap.permits("cyberark_read")


def test_sensitive_read_seats_are_high_while_write_seats_stay_high():
    for seat in _SENSITIVE_EXAMPLES:
        assert seat in READ_CONNECTOR_NAMES
        assert READ_CONNECTOR_RISKS[seat] == "high"
        assert tool_risk(seat) == "high"
        assert tool_risk(seat[: -len("_read")]) == "high"


def test_rollout_covers_all_seven_non_finance_suites_without_low_risk_bypass():
    d = load_domains(builtin_dir())
    reads = set(READ_CONNECTOR_NAMES)
    suites: dict[str, int] = {}
    for name, prof in d.items():
        if name.startswith("finance"):
            continue
        if reads & set(prof.allow_tools):
            suites[name.split("_")[0]] = suites.get(name.split("_")[0], 0) + 1
    assert set(suites) >= {"gtm", "legal", "ops", "hr", "itgrc", "pe", "strat"}, suites
    assert sum(suites.values()) >= 100, suites  # the rollout still reaches breadth
