"""Read-seat rollout across the non-finance suites. Each suite's data-touching
packs get low-risk, GET-only vendor read connectors wired in (the same recipe as
finance), so every suite -- GTM, legal, ops, HR, IT-GRC, product/eng, strategy --
can pull from its real systems while staying read-only."""
from __future__ import annotations

from maverick.capability import Capability
from maverick.domain import builtin_dir, domain_capability, load_domains
from maverick.safety.tool_risk import tool_risk
from maverick.tools.enterprise_connectors import READ_CONNECTOR_NAMES

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


def _parent() -> Capability:
    return Capability(principal="agent:supervisor-0", max_risk="high")


def test_each_suite_pack_reaches_its_read_seat():
    d = load_domains(builtin_dir())
    parent = _parent()
    for pack, seat in _SAMPLES.items():
        cap = domain_capability(d[pack], parent, f"agent:{pack}-1")
        assert cap.permits(seat), f"{pack} cannot reach read seat {seat}"
        assert tool_risk(seat) == "low", f"{seat} must be low"


def test_read_seats_low_while_write_seats_stay_high():
    for seat in set(_SAMPLES.values()):
        assert tool_risk(seat) == "low"
        assert tool_risk(seat[: -len("_read")]) == "high"


def test_rollout_covers_all_seven_non_finance_suites():
    d = load_domains(builtin_dir())
    reads = set(READ_CONNECTOR_NAMES)
    suites: dict[str, int] = {}
    for name, prof in d.items():
        if name.startswith("finance"):
            continue
        if reads & set(prof.allow_tools):
            suites[name.split("_")[0]] = suites.get(name.split("_")[0], 0) + 1
    assert set(suites) >= {"gtm", "legal", "ops", "hr", "itgrc", "pe", "strat"}, suites
    assert sum(suites.values()) >= 100, suites  # the rollout reaches breadth
