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

    def test_extract_w2_boxes_with_provenance(self):
        doc = extract(W2_TEXT, label="W-2 — Acme Corp")
        assert doc.doc_type == "W-2"
        assert doc.wages == 85000.0
        assert doc.federal_withholding == 9000.0
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
        assert len(packs) >= 18, f"expected >=18 tax packs, found {len(packs)}"
        for name, p in packs.items():
            assert p.max_risk == "low", f"{name}: risk={p.max_risk!r}"
            assert len(p.persona.strip()) >= 200, f"{name}: thin persona"
            assert p.knowledge_sources == ["tax"], name
            assert p.compartment.startswith("tax_"), name
            cap = p.capability(f"agent:{name}")
            assert cap.permits("read_file") is True, name
            # Taxpayer data never leaves: no shell/write, no web egress.
            for dangerous in ("shell", "write_file", "code_exec",
                              "web_search", "browser"):
                assert "shell" in p.deny_tools and "write_file" in p.deny_tools
                assert cap.permits(dangerous) is False, f"{name}: {dangerous}"

    def test_suite_registered_with_discipline(self):
        from maverick.domain import suite_for
        from maverick.domain_discipline import discipline_for
        assert suite_for("tax_workpaper_assembler") == "tax"
        block = discipline_for("tax_workpaper_assembler")
        assert "Tax preparation discipline" in block
        assert "never" in block.lower()


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
        assert out.read_text(encoding="utf-8").startswith(tax_prep.DISCLAIMER)

    def test_empty_folder_is_an_open_item_not_a_crash(self, tmp_path):
        res = CliRunner().invoke(main, [
            "--db", str(tmp_path / "x.db"), "tax", "prepare", str(tmp_path),
        ])
        assert res.exit_code == 0, res.output
        assert "no source documents provided" in res.output
