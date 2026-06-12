"""Tax preparation pipeline: uploaded documents -> first-pass draft return.

The flagship professional-services workflow. A client uploads source
documents; the ``tax_`` suite's agents classify and extract them; this
module is the DETERMINISTIC core they feed: typed source documents in,
standardized workpaper out, first-pass Form 1040 computation on top, and a
review package where **every number cites the document it came from**.

Division of labor (the architecture's spine):

* **Agents** (tax_ packs) do the unstructured work at runtime -- chasing
  missing documents, OCR/extraction from PDFs, client communications --
  and feed structured :class:`SourceDoc` records into this module.
* **This module** does everything that must be exactly right and provable:
  classification schemas, workpaper assembly, completeness checks, the
  TY2025 federal computation, and the review package. Pure functions,
  no LLM, unit-tested against hand-computed returns.
* **The CPA** reviews and signs. The draft is labeled as a first pass for
  preparer review; filing and certification are human acts (the same
  "agents draft; humans file and certify" discipline as the finance suite).

Scope of the v1 computation (stated, not hidden): Form 1040 with W-2 wages,
1099-INT interest, ordinary 1099-DIV dividends, the standard deduction, the
child tax credit, and federal withholding. Itemizing, Schedule C/E, capital
gains, and state returns are workpaper line items flagged FOR PREPARER
REVIEW rather than computed. Tax-year constants live in one table
(``TY2025``, per the One Big Beautiful Bill Act figures) and ship as
content updates each season.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DISCLAIMER = (
    "FIRST-PASS DRAFT prepared by Maverick tax agents for preparer review. "
    "Not a filed return and not tax advice. A credentialed preparer must "
    "review, complete, and sign before filing."
)

DOC_TYPES = ("W-2", "1099-INT", "1099-DIV", "1099-NEC", "1098", "K-1",
             "PRIOR-RETURN", "UNKNOWN")

# Lexical signatures for deterministic classification of extracted text.
_DOC_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("W-2", ("w-2", "wage and tax statement", "wages, tips")),
    ("1099-INT", ("1099-int", "interest income")),
    ("1099-DIV", ("1099-div", "ordinary dividends")),
    ("1099-NEC", ("1099-nec", "nonemployee compensation")),
    ("1098", ("1098", "mortgage interest")),
    ("K-1", ("schedule k-1", "k-1", "partner's share")),
    ("PRIOR-RETURN", ("form 1040", "u.s. individual income tax return")),
]

_MONEY_RE = re.compile(r"\$?([0-9][0-9,]*(?:\.[0-9]{1,2})?)")

# TY2025 federal constants (One Big Beautiful Bill Act, enacted July 2025).
# One table per tax year; updating next season is a content release.
TY2025 = {
    "year": 2025,
    "standard_deduction": {"single": 15750.0, "mfj": 31500.0, "hoh": 23625.0},
    "brackets": {  # (top of bracket, rate); top bracket open-ended
        "single": [(11925, .10), (48475, .12), (103350, .22), (197300, .24),
                   (250525, .32), (626350, .35), (None, .37)],
        "mfj": [(23850, .10), (96950, .12), (206700, .22), (394600, .24),
                (501050, .32), (751600, .35), (None, .37)],
        "hoh": [(17000, .10), (64850, .12), (103350, .22), (197300, .24),
                (250525, .32), (626350, .35), (None, .37)],
    },
    "ctc_per_child": 2200.0,
    "ctc_phaseout_start": {"single": 200000.0, "mfj": 400000.0,
                           "hoh": 200000.0},
}

FILING_STATUSES = ("single", "mfj", "hoh")


@dataclass
class SourceDoc:
    """One classified source document with its extracted figures."""
    doc_type: str
    label: str                       # e.g. "W-2 — Acme Corp"
    wages: float = 0.0               # W-2 box 1
    federal_withholding: float = 0.0  # W-2 box 2 / 1099 box 4
    interest: float = 0.0            # 1099-INT box 1
    ordinary_dividends: float = 0.0  # 1099-DIV box 1a
    nonemployee_comp: float = 0.0    # 1099-NEC box 1 (flagged, not computed)
    raw_excerpt: str = ""            # provenance snippet (bounded)


@dataclass
class Workpaper:
    """The standardized prep workpaper the agents assemble."""
    filing_status: str = "single"
    dependents_under_17: int = 0
    docs: list[SourceDoc] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def total_wages(self) -> float:
        return sum(d.wages for d in self.docs)

    @property
    def total_interest(self) -> float:
        return sum(d.interest for d in self.docs)

    @property
    def total_dividends(self) -> float:
        return sum(d.ordinary_dividends for d in self.docs)

    @property
    def total_withholding(self) -> float:
        return sum(d.federal_withholding for d in self.docs)


@dataclass
class Draft1040:
    """First-pass federal return: line values + provenance + open items."""
    filing_status: str
    total_income: float
    standard_deduction: float
    taxable_income: float
    tax_before_credits: float
    child_tax_credit: float
    tax_after_credits: float
    federal_withholding: float
    balance: float                   # negative = refund
    open_items: list[str] = field(default_factory=list)
    lines: list[tuple[str, float, str]] = field(default_factory=list)
    # (line description, amount, source citation)


def classify(text: str) -> str:
    """Deterministic doc-type classification from extracted text."""
    t = (text or "").lower()
    for doc_type, needles in _DOC_SIGNATURES:
        if any(n in t for n in needles):
            return doc_type
    return "UNKNOWN"


def _amount_after(text: str, *labels: str) -> float:
    """First dollar amount on a line containing any label (case-insensitive).

    Extraction agents normally supply structured figures; this parser covers
    cleanly formatted text exports so the pipeline runs end to end without
    an LLM (and so the demo/tests are deterministic)."""
    for line in (text or "").splitlines():
        low = line.lower()
        for lbl in labels:
            idx = low.find(lbl)
            if idx < 0:
                continue
            # Search AFTER the label so "Box 1 Wages: $85,000.00" yields the
            # amount, not the box number.
            m = _MONEY_RE.search(line[idx + len(lbl):])
            if m:
                return float(m.group(1).replace(",", ""))
    return 0.0


def extract(text: str, *, label: str = "") -> SourceDoc:
    """Classify + pull the standard boxes from one document's text."""
    doc_type = classify(text)
    doc = SourceDoc(doc_type=doc_type, label=label or doc_type,
                    raw_excerpt=(text or "")[:160])
    if doc_type == "W-2":
        doc.wages = _amount_after(text, "wages, tips", "box 1")
        doc.federal_withholding = _amount_after(
            text, "federal income tax withheld", "box 2")
    elif doc_type == "1099-INT":
        doc.interest = _amount_after(text, "interest income", "box 1")
        doc.federal_withholding = _amount_after(
            text, "federal income tax withheld", "box 4")
    elif doc_type == "1099-DIV":
        doc.ordinary_dividends = _amount_after(
            text, "ordinary dividends", "box 1a")
        doc.federal_withholding = _amount_after(
            text, "federal income tax withheld", "box 4")
    elif doc_type == "1099-NEC":
        doc.nonemployee_comp = _amount_after(
            text, "nonemployee compensation", "box 1")
    return doc


def missing_items(wp: Workpaper) -> list[str]:
    """Completeness check: what a preparer would chase before computing."""
    items: list[str] = []
    if wp.filing_status not in FILING_STATUSES:
        items.append(f"filing status {wp.filing_status!r} is not supported "
                     f"(supported: {', '.join(FILING_STATUSES)})")
    if not wp.docs:
        items.append("no source documents provided")
    for d in wp.docs:
        if d.doc_type == "UNKNOWN":
            items.append(f"unclassified document: {d.label} -- needs "
                         "preparer identification")
        if d.doc_type == "1099-NEC":
            items.append(f"{d.label}: self-employment income requires "
                         "Schedule C + SE tax -- PREPARER MUST COMPLETE")
        if d.doc_type == "K-1":
            items.append(f"{d.label}: K-1 pass-through requires Schedule E "
                         "-- PREPARER MUST COMPLETE")
        if d.doc_type == "1098":
            items.append(f"{d.label}: mortgage interest -- evaluate "
                         "itemizing vs the standard deduction")
        if d.doc_type == "W-2" and d.wages <= 0:
            items.append(f"{d.label}: W-2 with no box-1 wages extracted -- "
                         "verify the document")
    return items


def _bracket_tax(taxable: float, brackets: list[tuple]) -> float:
    tax, lower = 0.0, 0.0
    for top, rate in brackets:
        if top is None or taxable <= top:
            tax += (taxable - lower) * rate
            return max(0.0, tax)
        tax += (top - lower) * rate
        lower = float(top)
    return max(0.0, tax)  # pragma: no cover -- open bracket returns above


def compute_first_pass(wp: Workpaper, *, constants: dict = TY2025) -> Draft1040:
    """The first-pass federal computation, every line cited to its source.

    Deterministic and intentionally conservative: anything outside the
    supported scope lands in ``open_items`` for the preparer instead of
    being guessed at.
    """
    status = wp.filing_status if wp.filing_status in FILING_STATUSES else "single"
    lines: list[tuple[str, float, str]] = []
    for d in wp.docs:
        if d.wages:
            lines.append(("Wages (1040 line 1a)", d.wages, d.label))
        if d.interest:
            lines.append(("Taxable interest (line 2b)", d.interest, d.label))
        if d.ordinary_dividends:
            lines.append(("Ordinary dividends (line 3b)",
                          d.ordinary_dividends, d.label))
    total_income = wp.total_wages + wp.total_interest + wp.total_dividends
    std = constants["standard_deduction"][status]
    taxable = max(0.0, total_income - std)
    tax = round(_bracket_tax(taxable, constants["brackets"][status]), 2)

    # Child tax credit with the 5% phaseout, capped at tax (nonrefundable
    # portion only -- the additional CTC is an open item for the preparer).
    ctc = constants["ctc_per_child"] * wp.dependents_under_17
    over = max(0.0, total_income - constants["ctc_phaseout_start"][status])
    if over:
        ctc = max(0.0, ctc - (int((over + 999) // 1000) * 50.0))
    ctc = min(ctc, tax)

    withholding = wp.total_withholding
    after_credits = max(0.0, tax - ctc)
    draft = Draft1040(
        filing_status=status,
        total_income=round(total_income, 2),
        standard_deduction=std,
        taxable_income=round(taxable, 2),
        tax_before_credits=tax,
        child_tax_credit=round(ctc, 2),
        tax_after_credits=round(after_credits, 2),
        federal_withholding=round(withholding, 2),
        balance=round(after_credits - withholding, 2),
        open_items=missing_items(wp) + list(wp.notes),
        lines=lines,
    )
    return draft


def render_review_package(draft: Draft1040) -> str:
    """The preparer-facing review package: draft + provenance + open items."""
    out = [DISCLAIMER, "",
           f"DRAFT FORM 1040 (TY{TY2025['year']}) — first pass",
           "=" * 52,
           f"Filing status        : {draft.filing_status.upper()}"]
    for desc, amount, source in draft.lines:
        out.append(f"  {desc:<34} ${amount:>12,.2f}   [{source}]")
    out += [
        f"Total income         : ${draft.total_income:,.2f}",
        f"Standard deduction   : ${draft.standard_deduction:,.2f}",
        f"Taxable income       : ${draft.taxable_income:,.2f}",
        f"Tax (before credits) : ${draft.tax_before_credits:,.2f}",
        f"Child tax credit     : ${draft.child_tax_credit:,.2f}",
        f"Tax after credits    : ${draft.tax_after_credits:,.2f}",
        f"Federal withholding  : ${draft.federal_withholding:,.2f}",
    ]
    if draft.balance < 0:
        out.append(f"ESTIMATED REFUND     : ${-draft.balance:,.2f}")
    else:
        out.append(f"ESTIMATED BALANCE DUE: ${draft.balance:,.2f}")
    if draft.open_items:
        out.append("")
        out.append("OPEN ITEMS FOR PREPARER (must be resolved before filing):")
        out += [f"  - {item}" for item in draft.open_items]
    return "\n".join(out)


__all__ = [
    "DISCLAIMER", "DOC_TYPES", "TY2025", "FILING_STATUSES",
    "SourceDoc", "Workpaper", "Draft1040",
    "classify", "extract", "missing_items", "compute_first_pass",
    "render_review_package",
]
