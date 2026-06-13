"""Tax preparation pipeline: docs in -> cited first-pass draft 1040 out.

The computation tests are checked against hand-computed TY2025 returns
(One Big Beautiful Bill Act figures) -- if a constant or the bracket math
drifts, these fail with the exact dollar delta. The suite tests hold the
tax_ packs to the same read-only safety envelope as every other suite.
"""
from __future__ import annotations

from click.testing import CliRunner
from maverick import tax_prep
from maverick.cli import main
from maverick.domain import builtin_dir, load_domains
from maverick.tax_prep import (
    SourceDoc,
    Workpaper,
    classify,
    compute_first_pass,
    extract,
    missing_items,
    render_review_package,
)

W2_TEXT = """Form W-2 Wage and Tax Statement 2025
Employer: Acme Corp  EIN 12-3456789
Box 1 Wages, tips, other compensation: $85,000.00
Box 2 Federal income tax withheld: $9,000.00
Box 15 State: PA  Employer's state ID: 1234-5678
Box 17 State income tax: $2,609.50
"""

INT_TEXT = """Form 1099-INT 2025
Payer: First Bank
Box 1 Interest income: $412.33
Box 4 Federal income tax withheld: $0.00
"""

NEC_TEXT = """Form 1099-NEC 2025
Payer: Gig Platform LLC
Box 1 Nonemployee compensation: $6,500.00
"""


class TestClassifyExtract:
    def test_classify_the_common_forms(self):
        assert classify(W2_TEXT) == "W-2"
        assert classify(INT_TEXT) == "1099-INT"
        assert classify(NEC_TEXT) == "1099-NEC"
        assert classify("Schedule K-1 Partner's Share of Income") == "K-1"
        assert classify("grocery receipt") == "UNKNOWN"

    def test_classify_the_flagged_only_forms(self):
        # Specific 1098 variants must NOT fall through to the mortgage 1098.
        assert classify("Form 1098-T Tuition Statement") == "1098-T"
        assert classify("Form 1098-E Student Loan Interest") == "1098-E"
        assert classify("Form 1098 Mortgage Interest Statement") == "1098"
        assert classify("Form 1099-R Distributions From Pensions") == "1099-R"
        assert classify("Form SSA-1099 Social Security Benefit") == "SSA-1099"
        assert classify("Form 1099-G Unemployment Compensation") == "1099-G"
        assert classify("Form 1099-B Proceeds From Broker") == "1099-B"

    def test_extract_w2_boxes_with_provenance(self):
        doc = extract(W2_TEXT, label="W-2 — Acme Corp")
        assert doc.doc_type == "W-2"
        assert doc.wages == 85000.0
        assert doc.federal_withholding == 9000.0
        assert doc.state == "PA"            # box 15, validated state code
        assert doc.state_withholding == 2609.50
        assert doc.raw_excerpt.startswith("Form W-2")

    def test_extract_interest_and_nec(self):
        assert extract(INT_TEXT).interest == 412.33
        assert extract(NEC_TEXT).nonemployee_comp == 6500.0


class TestFirstPassComputation:
    def test_single_w2_only_hand_computed(self):
        # Single, $85,000 wages, $9,000 withheld. Std deduction 15,750 ->
        # taxable 69,250. Tax: 1,192.50 + 4,386.00 + 22%*20,775 = 10,149.00.
        wp = Workpaper(filing_status="single", docs=[
            SourceDoc("W-2", "W-2 — Acme", wages=85000.0,
                      federal_withholding=9000.0),
        ])
        d = compute_first_pass(wp)
        assert d.taxable_income == 69250.0
        assert d.tax_before_credits == 10149.0
        assert d.balance == 1149.0  # owes
        assert d.open_items == []

    def test_mfj_with_kids_refund_hand_computed(self):
        # MFJ, $120,000 wages, $11,000 withheld, 2 kids. Std 31,500 ->
        # taxable 88,500. Tax: 2,385 + 12%*64,650 = 10,143. CTC 4,400 ->
        # 5,743 after credits; refund 5,257.
        wp = Workpaper(filing_status="mfj", dependents_under_17=2, docs=[
            SourceDoc("W-2", "W-2 — A", wages=70000.0,
                      federal_withholding=6000.0),
            SourceDoc("W-2", "W-2 — B", wages=50000.0,
                      federal_withholding=5000.0),
        ])
        d = compute_first_pass(wp)
        assert d.tax_before_credits == 10143.0
        assert d.child_tax_credit == 4400.0
        assert d.balance == -5257.0  # refund

    def test_ctc_phaseout_hand_computed(self):
        # MFJ, $412,500 income: $12,500 over the 400k start -> 13 units of
        # $50 = $650 off the $4,400 credit. Taxable 381,000 -> tax 77,134.
        wp = Workpaper(filing_status="mfj", dependents_under_17=2, docs=[
            SourceDoc("W-2", "W-2 — Exec", wages=412500.0),
        ])
        d = compute_first_pass(wp)
        assert d.tax_before_credits == 77134.0
        assert d.child_tax_credit == 4400.0 - 650.0

    def test_ctc_capped_at_tax_never_negative(self):
        wp = Workpaper(filing_status="hoh", dependents_under_17=3, docs=[
            SourceDoc("W-2", "W-2", wages=25000.0),
        ])
        d = compute_first_pass(wp)
        assert d.child_tax_credit == d.tax_before_credits
        assert d.tax_after_credits == 0.0

    def test_interest_and_dividends_roll_into_income(self):
        wp = Workpaper(filing_status="single", docs=[
            SourceDoc("W-2", "W-2", wages=50000.0),
            SourceDoc("1099-INT", "INT", interest=400.0),
            SourceDoc("1099-DIV", "DIV", ordinary_dividends=600.0),
        ])
        d = compute_first_pass(wp)
        assert d.total_income == 51000.0
        descs = [desc for desc, _, _ in d.lines]
        assert any("interest" in s.lower() for s in descs)
        assert any("dividends" in s.lower() for s in descs)


class TestStateFirstPass:
    def _wp(self, state="", wages=85000.0, state_wh=2609.50, status="single"):
        from maverick.tax_prep import Workpaper as WP
        return WP(filing_status=status, state=state, docs=[
            SourceDoc("W-2", "W-2 — Acme", wages=wages,
                      state="PA" if not state else state,
                      state_withholding=state_wh),
        ])

    def test_pa_flat_hand_computed(self):
        # PA: flat 3.07% on income, no standard deduction.
        # 85,000 * .0307 = 2,609.50 -- exactly the withholding: zero balance.
        from maverick.tax_prep import compute_state_first_pass, infer_state
        wp = self._wp()
        assert infer_state(wp) == "PA"      # auto-detected from W-2 box 15
        sd = compute_state_first_pass(wp, "PA")
        assert sd.computed and sd.tax == 2609.50 and sd.balance == 0.0

    def test_az_flat_with_federal_matching_deduction(self):
        # AZ: 2.5% after the federal-matching std deduction.
        # (85,000 - 15,750) * .025 = 1,731.25.
        from maverick.tax_prep import compute_state_first_pass
        sd = compute_state_first_pass(self._wp(state="AZ"), "AZ")
        assert sd.computed and sd.state_taxable == 69250.0
        assert sd.tax == 1731.25

    def test_co_taxes_federal_taxable_income(self):
        # CO: 4.4% of federal taxable income: 69,250 * .044 = 3,047.00.
        from maverick.tax_prep import compute_state_first_pass
        sd = compute_state_first_pass(self._wp(state="CO"), "CO")
        assert sd.computed and sd.tax == 3047.00

    def test_no_tax_state_refunds_any_withholding(self):
        from maverick.tax_prep import compute_state_first_pass
        sd = compute_state_first_pass(self._wp(state="TX", state_wh=100.0), "TX")
        assert sd.computed and sd.tax == 0.0 and sd.balance == -100.0

    def test_graduated_state_is_an_explicit_handoff_not_a_guess(self):
        from maverick.tax_prep import compute_state_first_pass
        sd = compute_state_first_pass(self._wp(state="CA"), "CA")
        assert sd.computed is False
        assert sd.withholding == 2609.50    # the known figure still tallied
        joined = "\n".join(sd.open_items)
        assert "PREPARER MUST COMPLETE" in joined
        assert "cch_axcess" in joined and "gosystem_tax" in joined

    def test_multi_state_withholding_flagged(self):
        from maverick.tax_prep import Workpaper as WP
        from maverick.tax_prep import compute_state_first_pass
        wp = WP(filing_status="single", docs=[
            SourceDoc("W-2", "W-2 — A", wages=50000.0, state="PA",
                      state_withholding=1535.0),
            SourceDoc("W-2", "W-2 — B", wages=20000.0, state="NJ",
                      state_withholding=400.0),
        ])
        sd = compute_state_first_pass(wp, "PA")
        assert sd.withholding == 1535.0     # NJ's 400 not credited to PA
        assert any("NJ" in i and "multi-state" in i for i in sd.open_items)

    def test_unknown_state_asks_for_it(self):
        from maverick.tax_prep import compute_state_first_pass
        wp = self._wp()
        wp.docs[0].state = ""
        sd = compute_state_first_pass(wp, "")
        assert sd.computed is False
        assert any("resident state not determined" in i for i in sd.open_items)


class TestMissingItems:
    def test_out_of_scope_docs_become_preparer_open_items(self):
        wp = Workpaper(filing_status="single", docs=[
            SourceDoc("1099-NEC", "NEC — Gig", nonemployee_comp=6500.0),
            SourceDoc("K-1", "K-1 — Fund LP"),
            SourceDoc("1098", "1098 — Mortgage Co"),
            SourceDoc("UNKNOWN", "mystery.txt"),
        ])
        joined = "\n".join(missing_items(wp))
        assert "Schedule C" in joined and "Schedule E" in joined
        assert "itemizing" in joined
        assert "unclassified" in joined

    def test_judgment_docs_are_flagged_never_computed(self):
        wp = Workpaper(filing_status="single", docs=[
            SourceDoc("1099-R", "R — Fidelity"),
            SourceDoc("SSA-1099", "SSA"),
            SourceDoc("1099-G", "G — State"),
            SourceDoc("1099-B", "B — Broker"),
            SourceDoc("1098-T", "T — University"),
        ])
        joined = "\n".join(missing_items(wp))
        for needle in ("rollover", "taxability worksheet", "unemployment",
                       "Schedule D", "education credits"):
            assert needle in joined, needle
        # and none of them leak into the federal computation
        assert compute_first_pass(wp).total_income == 0.0

    def test_empty_and_bad_status_flagged(self):
        items = missing_items(Workpaper(filing_status="married"))
        joined = "\n".join(items)
        assert "no source documents" in joined
        assert "not supported" in joined


class TestReviewPackage:
    def test_package_has_disclaimer_citations_and_open_items(self):
        wp = Workpaper(filing_status="single", docs=[
            SourceDoc("W-2", "W-2 — Acme", wages=85000.0,
                      federal_withholding=12000.0),
            SourceDoc("1099-NEC", "NEC — Gig", nonemployee_comp=2000.0),
        ])
        text = render_review_package(compute_first_pass(wp))
        assert text.startswith(tax_prep.DISCLAIMER)
        assert "[W-2 — Acme]" in text          # provenance citation
        assert "ESTIMATED REFUND" in text       # 12k withheld > 10,149 tax
        assert "OPEN ITEMS FOR PREPARER" in text
        assert "PREPARER MUST COMPLETE" in text


class TestTaxSuitePacks:
    def test_roster_present_and_sealed(self):
        packs = {k: v for k, v in load_domains(builtin_dir()).items()
                 if k.startswith("tax_")}
        assert len(packs) >= 19, f"expected >=19 tax packs, found {len(packs)}"
        for name, p in packs.items():
            assert p.max_risk == "low", f"{name}: risk={p.max_risk!r}"
            assert len(p.persona.strip()) >= 200, f"{name}: thin persona"
            assert p.compartment.startswith("tax_"), name
            cap = p.capability(f"agent:{name}")
            assert "shell" in p.deny_tools and "write_file" in p.deny_tools
            for dangerous in ("shell", "write_file", "code_exec"):
                assert cap.permits(dangerous) is False, f"{name}: {dangerous}"
            if name == "tax_law_watch":   # inverse seal, asserted below
                assert cap.permits("read_file") is False, name
                continue
            assert cap.permits("read_file") is True, name
            # Client-data packs: taxpayer data never leaves -- no web egress.
            assert p.knowledge_sources == ["tax"], name
            for egress in ("web_search", "browser"):
                assert cap.permits(egress) is False, f"{name}: {egress}"

    def test_law_watch_has_the_inverse_seal(self):
        # The one pack with web access is the one pack with NO client data:
        # it monitors IRS/state guidance against the firm's tax-law library,
        # and never touches the client-document corpus.
        p = load_domains(builtin_dir())["tax_law_watch"]
        cap = p.capability("agent:tax_law_watch")
        assert cap.permits("web_search") is True
        assert cap.permits("knowledge_search") is True
        assert cap.permits("read_file") is False
        assert "read_file" in p.deny_tools
        assert p.knowledge_sources == ["tax_law"]   # not the client corpus
        assert "constants" in p.persona and "signed" in p.persona

    def test_suite_registered_with_discipline(self):
        from maverick.domain import suite_for
        from maverick.domain_discipline import discipline_for
        assert suite_for("tax_workpaper_assembler") == "tax"
        block = discipline_for("tax_workpaper_assembler")
        assert "Tax preparation discipline" in block
        assert "never" in block.lower()


class TestTaxEngineConnectors:
    """CCH Axcess + Thomson Reuters GoSystem: the firm's authoritative tax
    engines. Write connectors exist (confirm-gated, high risk); the tax_
    packs get GET-only LOW read seats for return/e-file status."""

    def _tools(self):
        from maverick.tools.enterprise_connectors import enterprise_connectors
        return {t.name: t for t in enterprise_connectors()}

    def test_registered_with_read_seats(self):
        from maverick.tools.enterprise_connectors import (
            ENTERPRISE_CONNECTOR_NAMES,
            READ_CONNECTOR_NAMES,
            READ_CONNECTOR_RISKS,
        )
        for vendor in ("cch_axcess", "gosystem_tax"):
            assert vendor in ENTERPRISE_CONNECTOR_NAMES
            assert f"{vendor}_read" in READ_CONNECTOR_NAMES
            assert READ_CONNECTOR_RISKS[f"{vendor}_read"] == "low"

    def test_read_seats_are_get_only_and_low_risk(self):
        from maverick.safety.tool_risk import tool_risk
        tools = self._tools()
        for vendor in ("cch_axcess", "gosystem_tax"):
            seat = tools[f"{vendor}_read"]
            assert seat.input_schema["properties"]["op"]["enum"] == ["get"]
            assert tool_risk(f"{vendor}_read") == "low"
            out = seat.fn({"op": "post", "path": "/api/x", "confirm": True})
            assert "read-only" in out
            # the write connector stays auto-classified high (submission/
            # modification of returns never reachable from a low pack)
            assert tool_risk(vendor) == "high"

    def test_missing_creds_fail_loudly_naming_the_envs(self, monkeypatch):
        for env in ("CCH_AXCESS_BASE_URL", "CCH_AXCESS_TOKEN"):
            monkeypatch.delenv(env, raising=False)
        out = self._tools()["cch_axcess"].fn({"op": "get", "path": "/api/x"})
        assert "ERROR" in out
        assert "CCH_AXCESS_BASE_URL" in out and "CCH_AXCESS_TOKEN" in out

    def test_cch_subscription_key_prompted_by_the_wizard_catalog(self):
        from maverick.tools.enterprise_connectors import connector_catalog
        entry = next(e for e in connector_catalog() if e["name"] == "cch_axcess")
        assert ("CCH_AXCESS_SUBSCRIPTION_KEY", True) in entry["env"]

    def test_status_packs_can_reach_the_read_seats(self):
        packs = load_domains(builtin_dir())
        for name in ("tax_efile_status", "tax_prior_year_compare",
                     "tax_season_ops", "tax_intake_checklist"):
            cap = packs[name].capability(f"agent:{name}")
            assert cap.permits("cch_axcess_read") is True, name
            assert cap.permits("gosystem_tax_read") is True, name
            assert cap.permits("cch_axcess") is False, name   # write seat
            assert cap.permits("gosystem_tax") is False, name


class TestTaxPrepareCli:
    def test_docs_folder_to_review_package(self, tmp_path):
        (tmp_path / "w2_acme.txt").write_text(W2_TEXT, encoding="utf-8")
        (tmp_path / "int_bank.txt").write_text(INT_TEXT, encoding="utf-8")
        (tmp_path / "nec_gig.txt").write_text(NEC_TEXT, encoding="utf-8")
        out = tmp_path / "review.txt"
        res = CliRunner().invoke(main, [
            "--db", str(tmp_path / "x.db"), "tax", "prepare", str(tmp_path),
            "--filing-status", "single", "--out", str(out),
        ])
        assert res.exit_code == 0, res.output
        assert "DRAFT FORM 1040" in res.output
        assert "[w2_acme.txt]" in res.output          # cited to the upload
        assert "Schedule C" in res.output              # NEC flagged, not computed
        # State auto-detected from W-2 box 15 and computed (PA flat).
        assert "DRAFT PA STATE RETURN" in res.output
        assert "State tax (flat 3.07%)" in res.output
        assert out.read_text(encoding="utf-8").startswith(tax_prep.DISCLAIMER)

    def test_state_override_beats_autodetect(self, tmp_path):
        (tmp_path / "w2.txt").write_text(W2_TEXT, encoding="utf-8")
        res = CliRunner().invoke(main, [
            "--db", str(tmp_path / "x.db"), "tax", "prepare", str(tmp_path),
            "--state", "CA",
        ])
        assert res.exit_code == 0, res.output
        assert "DRAFT CA STATE RETURN" in res.output
        assert "PREPARER MUST COMPLETE" in res.output  # graduated: handed off

    def test_empty_folder_is_an_open_item_not_a_crash(self, tmp_path):
        res = CliRunner().invoke(main, [
            "--db", str(tmp_path / "x.db"), "tax", "prepare", str(tmp_path),
        ])
        assert res.exit_code == 0, res.output
        assert "no source documents provided" in res.output
