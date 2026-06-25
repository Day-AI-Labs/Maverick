"""Specialist routing: lexical retrieval over the 1,118-pack roster.

The router is a deterministic pre-filter that narrows the roster to a relevant
shortlist for a task, so the orchestrator picks from ~10 candidates instead of
guessing a suite and browsing it. These tests are the routing BENCHMARK: a
labeled set of realistic task phrasings (no pack-name leakage) with the set of
acceptable specialists for each, asserting recall@10 -- the pre-filter goal --
and suite accuracy stay above a floor, so a future pack/persona edit can't
silently degrade routing.
"""
from __future__ import annotations

from maverick.domain import builtin_dir, load_domains, suite_for
from maverick.domain_router import DomainRouter, rank_specialists

_PACKS = load_domains(builtin_dir())
_ROUTER = DomainRouter(_PACKS)

# (task phrased as a user would, acceptable specialist set, expected suite).
# Multiple packs are acceptable on purpose: with 1,118 specialists several are
# legitimately right for one task, so exact top-1 would understate the router.
_CASES: list[tuple[str, set[str], str]] = [
    ("review this NDA and flag the liability cap and indemnity clauses",
     {"legal_contract_review", "legal_nda_desk"}, "legal"),
    ("do a three-way match on these invoices before we pay the vendor",
     {"finance_ap"}, "finance"),
    ("build a 13 week cash flow forecast",
     {"finance_cash13w", "finance_cashflow"}, "finance"),
    ("screen these resumes against the job rubric", {"hr_screening"}, "hr"),
    ("an employee filed a harassment complaint, help me investigate",
     {"hr_investigations", "hr_employee_relations", "hr_er_intake"}, "hr"),
    ("triage this inbound support ticket and suggest a reply",
     {"cx_triage", "cx_tech_support"}, "customer_experience"),
    ("a customer wants a refund outside policy", {"cx_refunds"}, "customer_experience"),
    ("write an outbound cold email sequence for these prospects",
     {"gtm_outbound_sdr", "gtm_sequencing"}, "sales_gtm"),
    ("our SOC 2 audit needs evidence collected",
     {"itgrc_soc2_evidence", "itgrc_evidence"}, "it_grc"),
    ("a vendor wants access to our data, assess the third party risk",
     {"itgrc_vendor_risk", "itgrc_vendor_monitoring"}, "it_grc"),
    ("investigate this security alert from the SIEM",
     {"itgrc_siem_triage", "sec_soc_triage", "itgrc_threat_detection"}, "it_grc"),
    ("plan the sprint and groom the backlog",
     {"pe_backlog", "pe_roadmap"}, "product_engineering"),
    ("review this pull request for bugs",
     {"pe_code_review", "pe_bug_triage"}, "product_engineering"),
    ("the production service is down, run the incident",
     {"pe_sre_incident_commander", "pe_release_chaos"}, "product_engineering"),
    ("prior authorization for an MRI from the payer", {"hc_prior_auth"}, "healthcare"),
    ("file a claim for water damage on a property policy",
     {"ins_fnol", "ins_claim_file"}, "insurance"),
    ("a wire transfer looks suspicious, check for AML",
     {"bank_aml_alerts", "bank_wire_review", "bank_sar_prep"}, "banking"),
    ("reconcile the month end general ledger close",
     {"finance_gl_close", "finance_close_driver"}, "finance"),
    ("draft a press release for the product launch", {"mkt_pr_comms", "gtm_pr"}, "marketing"),
    ("negotiate pricing on this supplier contract",
     {"proc_sourcing", "proc_should_cost", "gtm_negotiation"}, "procurement"),
    ("value this acquisition target",
     {"strat_valuation", "strat_ma_modeling", "strat_due_diligence"}, "strategy"),
    ("respond to an IRS notice for a client", {"tax_irs_notice"}, "tax"),
    ("schedule preventive maintenance on the line equipment",
     {"ops_maintenance_pm", "mfg_maintenance_pm"}, "operations"),
    ("a shipment is delayed, chase the carrier for an ETA",
     {"log_track_trace", "log_eta_comms"}, "logistics"),
    ("check this construction change order and pay application",
     {"con_pay_apps", "con_change_orders"}, "construction"),
]


def _metrics():
    n = len(_CASES)
    hit1 = rec10 = suite1 = 0
    for query, acceptable, suite in _CASES:
        ranked = [name for name, _ in _ROUTER.rank(query, k=10)]
        if ranked and ranked[0] in acceptable:
            hit1 += 1
        if any(name in acceptable for name in ranked):
            rec10 += 1
        if ranked and suite_for(ranked[0]) == suite:
            suite1 += 1
    return n, hit1, rec10, suite1


def test_recall_at_10_meets_the_prefilter_floor():
    # The pre-filter's job: a valid specialist is in the shortlist it surfaces.
    n, _, rec10, _ = _metrics()
    assert rec10 / n >= 0.80, f"recall@10 = {rec10}/{n}"


def test_top1_and_suite_accuracy_meet_floor():
    n, hit1, _, suite1 = _metrics()
    assert hit1 / n >= 0.50, f"hit@1 = {hit1}/{n}"
    assert suite1 / n >= 0.60, f"suite@1 = {suite1}/{n}"


def test_rank_is_deterministic_and_bounded():
    a = _ROUTER.rank("review this NDA", k=5)
    b = _ROUTER.rank("review this NDA", k=5)
    assert a == b              # pure / stable
    assert len(a) <= 5
    assert all(s > 0 for _, s in a)  # no zero-score padding


def test_offroster_query_returns_nothing():
    # A query with no roster vocabulary returns an empty shortlist, not noise.
    assert _ROUTER.rank("zzzqqq xqzptl", k=10) == []


def test_module_level_cache_matches_fresh_index():
    ranked = rank_specialists("draft a press release", k=5, domains=_PACKS)
    assert [n for n, _ in ranked][:3] == [
        n for n, _ in _ROUTER.rank("draft a press release", k=5)][:3]
