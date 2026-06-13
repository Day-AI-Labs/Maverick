"""Tax preparation pipeline: uploaded documents -> first-pass draft return.

The flagship professional-services workflow. A client uploads source
documents; the ``tax_`` suite's agents classify and extract them; this
module is the DETERMINISTIC core they feed: typed source documents in,
standardized workpaper out, first-pass Form 1040 + state computation on
top, and a review package where **every number cites the document it came
from**.

Division of labor (the architecture's spine):

* **Agents** (tax_ packs) do the unstructured work at runtime -- chasing
  missing documents, OCR/extraction from PDFs, client communications --
  and feed structured :class:`SourceDoc` records into this module. The
  firm's professional tax engine (CCH Axcess / GoSystem, via the
  ``cch_axcess`` / ``gosystem_tax`` connectors) remains the authoritative
  computation and filing system; this first pass is the prep accelerant
  and cross-check in front of it.
* **This module** does everything that must be exactly right and provable:
  classification schemas, workpaper assembly, completeness checks, the
  TY2025 federal computation, the flat/no-tax state computation, and the
  review package. Pure functions, no LLM, unit-tested against
  hand-computed returns.
* **The CPA** reviews and signs. The draft is labeled as a first pass for
  preparer review; filing and certification are human acts (the same
  "agents draft; humans file and certify" discipline as the finance suite).

Scope of the v1 computation (stated, not hidden): Form 1040 with W-2 wages,
1099-INT interest, ordinary 1099-DIV dividends, the standard deduction, the
child tax credit, and federal withholding; plus state returns for no-tax
and flat-rate states (graduated states are flagged for the preparer / the
tax engine). Itemizing, Schedules C/D/E, retirement and benefit taxability,
and credits beyond the CTC are workpaper line items flagged FOR PREPARER
REVIEW rather than computed. Tax-year constants live in two tables
(``TY2025`` federal per the One Big Beautiful Bill Act; ``STATE_TY2025``)
and ship as content updates each season.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DISCLAIMER = (
    "FIRST-PASS DRAFT prepared by Maverick tax agents for preparer review. "
    "Not a filed return and not tax advice. A credentialed preparer must "
    "review, complete, and sign before filing."
)

DOC_TYPES = ("W-2", "1099-INT", "1099-DIV", "1099-NEC", "1099-B", "1099-R",
             "SSA-1099", "1099-G", "1098-T", "1098-E", "1098", "K-1",
             "PRIOR-RETURN", "UNKNOWN")

# Lexical signatures for deterministic classification of extracted text.
# Order matters: specific variants (1098-T/-E) before their generic prefix.
_DOC_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("W-2", ("w-2", "wage and tax statement", "wages, tips")),
    ("1099-INT", ("1099-int", "interest income")),
    ("1099-DIV", ("1099-div", "ordinary dividends")),
    ("1099-NEC", ("1099-nec", "nonemployee compensation")),
    ("1099-B", ("1099-b", "proceeds from broker")),
    ("1099-R", ("1099-r", "distributions from pensions")),
    ("SSA-1099", ("ssa-1099", "social security benefit")),
    ("1099-G", ("1099-g", "unemployment compensation",
                "certain government payments")),
    ("1098-T", ("1098-t", "tuition statement")),
    ("1098-E", ("1098-e", "student loan interest")),
    ("1098", ("1098", "mortgage interest")),
    ("K-1", ("schedule k-1", "k-1", "partner's share")),
    ("PRIOR-RETURN", ("form 1040", "u.s. individual income tax return")),
]

_MONEY_RE = re.compile(r"\$?([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
_STATE_TOKEN_RE = re.compile(r"\b([A-Z]{2})\b")
_REPORT_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_REPORT_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_REPORT_WHITESPACE_RE = re.compile(r"\s+")

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

STATE_CODES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
})

# TY2025 state constants for the states whose individual income tax is
# absent or a flat rate with a simple base. SEASON CONTENT: verify against
# each state's published TY2025 figures before a production season -- the
# preparer reviews every draft, and graduated/credit-structured states are
# deliberately NOT computed here (the professional tax engine owns those).
# "basis": what the flat rate applies to before the state deduction --
# federal AGI or federal taxable income.
STATE_TY2025: dict = {
    "year": 2025,
    "no_tax": frozenset({"AK", "FL", "NV", "NH", "SD", "TN", "TX", "WA", "WY"}),
    "flat": {
        "AZ": {"rate": .025, "basis": "agi",
               "deduction": {"single": 15750.0, "mfj": 31500.0, "hoh": 23625.0}},
        "CO": {"rate": .044, "basis": "federal_taxable",
               "deduction": {"single": 0.0, "mfj": 0.0, "hoh": 0.0}},
        "GA": {"rate": .0519, "basis": "agi",
               "deduction": {"single": 12000.0, "mfj": 24000.0, "hoh": 12000.0}},
        "ID": {"rate": .05695, "basis": "federal_taxable",
               "deduction": {"single": 0.0, "mfj": 0.0, "hoh": 0.0}},
        "IL": {"rate": .0495, "basis": "agi",
               "deduction": {"single": 2850.0, "mfj": 5700.0, "hoh": 2850.0}},
        "IN": {"rate": .03, "basis": "agi",
               "deduction": {"single": 1000.0, "mfj": 2000.0, "hoh": 1000.0}},
        "KY": {"rate": .04, "basis": "agi",
               "deduction": {"single": 3270.0, "mfj": 6540.0, "hoh": 3270.0}},
        "LA": {"rate": .03, "basis": "agi",
               "deduction": {"single": 12500.0, "mfj": 25000.0, "hoh": 12500.0}},
        "MI": {"rate": .0425, "basis": "agi",
               "deduction": {"single": 5800.0, "mfj": 11600.0, "hoh": 5800.0}},
        "NC": {"rate": .0425, "basis": "agi",
               "deduction": {"single": 12750.0, "mfj": 25500.0, "hoh": 19125.0}},
        "PA": {"rate": .0307, "basis": "agi",
               "deduction": {"single": 0.0, "mfj": 0.0, "hoh": 0.0}},
    },
}


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
    state: str = ""                  # W-2 box 15 state code
    state_withholding: float = 0.0   # W-2 box 17
    raw_excerpt: str = ""            # provenance snippet (bounded)


@dataclass
class Workpaper:
    """The standardized prep workpaper the agents assemble."""
    filing_status: str = "single"
    dependents_under_17: int = 0
    state: str = ""                  # resident state; "" = infer from docs
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

    @property
    def total_state_withholding(self) -> float:
        return sum(d.state_withholding for d in self.docs)


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


@dataclass
class StateDraft:
    """First-pass state computation (no-tax and flat-rate states only)."""
    state: str
    filing_status: str
    computed: bool                   # False = preparer/tax-engine completes
    rate: float = 0.0
    state_taxable: float = 0.0
    tax: float = 0.0
    withholding: float = 0.0
    balance: float = 0.0             # negative = refund (computed states only)
    open_items: list[str] = field(default_factory=list)


def classify(text: str) -> str:
    """Deterministic doc-type classification from extracted text."""
    t = (text or "").lower()
    for doc_type, needles in _DOC_SIGNATURES:
        if any(n in t for n in needles):
            return doc_type
    return "UNKNOWN"


def _amount_after(text: str, *labels: str) -> float:
    """First dollar amount AFTER a label on its line (case-insensitive).

    Extraction agents normally supply structured figures; this parser covers
    cleanly formatted text exports so the pipeline runs end to end without
    an LLM (and so the demo/tests are deterministic). Searching after the
    label keeps "Box 1 Wages: $85,000.00" from yielding the box number."""
    for line in (text or "").splitlines():
        low = line.lower()
        for lbl in labels:
            idx = low.find(lbl)
            if idx < 0:
                continue
            m = _MONEY_RE.search(line[idx + len(lbl):])
            if m:
                return float(m.group(1).replace(",", ""))
    return 0.0


def _state_code(text: str) -> str:
    """W-2 box 15 state code from a labeled line, validated against the
    real state-code set so an EIN fragment or stray initials never pass."""
    for line in (text or "").splitlines():
        low = line.lower()
        if "box 15" not in low and not low.lstrip().startswith("state"):
            continue
        for token in _STATE_TOKEN_RE.findall(line):
            if token in STATE_CODES:
                return token
    return ""


def _report_safe(value: object, *, fallback: str = "document") -> str:
    """Normalize untrusted text for one-line report fields.

    Source labels can originate from uploaded filenames. Unix filenames may
    contain newlines and terminal control bytes, so citations and open items
    must never render them verbatim into a preparer-facing package.
    """
    cleaned = _REPORT_ANSI_RE.sub(" ", str(value))
    cleaned = _REPORT_CONTROL_RE.sub(" ", cleaned)
    cleaned = _REPORT_WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned or fallback


def extract(text: str, *, label: str = "") -> SourceDoc:
    """Classify + pull the standard boxes from one document's text."""
    doc_type = classify(text)
    doc = SourceDoc(doc_type=doc_type,
                    label=_report_safe(label or doc_type, fallback=doc_type),
                    raw_excerpt=(text or "")[:160])
    if doc_type == "W-2":
        doc.wages = _amount_after(text, "wages, tips", "box 1")
        doc.federal_withholding = _amount_after(
            text, "federal income tax withheld", "box 2")
        doc.state = _state_code(text)
        doc.state_withholding = _amount_after(
            text, "state income tax", "box 17")
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


# Doc types whose tax treatment needs preparer judgment: classified and
# carried on the workpaper, never guessed into the computation.
_PREPARER_DOC_ITEMS = {
    "1099-NEC": "self-employment income requires Schedule C + SE tax "
                "-- PREPARER MUST COMPLETE",
    "K-1": "K-1 pass-through requires Schedule E -- PREPARER MUST COMPLETE",
    "1099-B": "broker proceeds require Schedule D / Form 8949 basis work "
              "-- PREPARER MUST COMPLETE",
    "1099-R": "retirement distribution: taxable amount and rollover "
              "treatment -- PREPARER MUST COMPLETE",
    "SSA-1099": "social security benefits: taxability worksheet "
                "-- PREPARER MUST COMPLETE",
    "1099-G": "government payments (unemployment / state refund): "
              "taxability -- PREPARER MUST COMPLETE",
    "1098": "mortgage interest -- evaluate itemizing vs the standard "
            "deduction",
    "1098-T": "tuition statement -- evaluate education credits",
    "1098-E": "student loan interest -- evaluate the deduction",
}


def missing_items(wp: Workpaper) -> list[str]:
    """Completeness check: what a preparer would chase before computing."""
    items: list[str] = []
    if wp.filing_status not in FILING_STATUSES:
        items.append(f"filing status {wp.filing_status!r} is not supported "
                     f"(supported: {', '.join(FILING_STATUSES)})")
    if not wp.docs:
        items.append("no source documents provided")
    for d in wp.docs:
        label = _report_safe(d.label)
        if d.doc_type == "UNKNOWN":
            items.append(f"unclassified document: {label} -- needs "
                         "preparer identification")
        flag = _PREPARER_DOC_ITEMS.get(d.doc_type)
        if flag:
            items.append(f"{label}: {flag}")
        if d.doc_type == "W-2" and d.wages <= 0:
            items.append(f"{label}: W-2 with no box-1 wages extracted -- "
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
            lines.append(("Wages (1040 line 1a)", d.wages,
                          _report_safe(d.label)))
        if d.interest:
            lines.append(("Taxable interest (line 2b)", d.interest,
                          _report_safe(d.label)))
        if d.ordinary_dividends:
            lines.append(("Ordinary dividends (line 3b)",
                          d.ordinary_dividends, _report_safe(d.label)))
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


def infer_state(wp: Workpaper) -> str:
    """Resident state: the workpaper's explicit state, else the single state
    on the W-2s (multiple states = preparer call, so return "")."""
    if wp.state:
        return wp.state.upper()
    seen = {d.state for d in wp.docs if d.state}
    return next(iter(seen)) if len(seen) == 1 else ""


def compute_state_first_pass(wp: Workpaper, state: str, *,
                             federal: Draft1040 | None = None,
                             constants: dict = STATE_TY2025) -> StateDraft:
    """First-pass state computation for no-tax and flat-rate states.

    Graduated and credit-structured states are NOT estimated here -- a wrong
    state estimate is worse than an explicit handoff, so those come back
    ``computed=False`` with the withholding tallied and the open item naming
    the authoritative path (the preparer / the firm's tax engine via the
    CCH Axcess / GoSystem connectors).
    """
    state = (state or "").upper()
    status = wp.filing_status if wp.filing_status in FILING_STATUSES else "single"
    withholding = round(sum(
        d.state_withholding for d in wp.docs
        if not d.state or d.state == state), 2)
    open_items: list[str] = []
    other = sorted({d.state for d in wp.docs if d.state and d.state != state})
    if other:
        open_items.append(
            f"withholding reported for other state(s) {', '.join(other)} -- "
            "multi-state allocation PREPARER MUST COMPLETE")

    if state not in STATE_CODES:
        return StateDraft(
            state=state or "??", filing_status=status, computed=False,
            withholding=withholding,
            open_items=open_items + [
                "resident state not determined -- set it on the workpaper "
                "(or --state) so the state return can be drafted"])

    if state in constants["no_tax"]:
        return StateDraft(state=state, filing_status=status, computed=True,
                          withholding=withholding,
                          balance=round(-withholding, 2),
                          open_items=open_items)

    flat = constants["flat"].get(state)
    if flat is None:
        return StateDraft(
            state=state, filing_status=status, computed=False,
            withholding=withholding,
            open_items=open_items + [
                f"{state} has a graduated/credit-structured income tax -- "
                "first pass not computed; PREPARER MUST COMPLETE (or compute "
                "in the firm's tax engine via the cch_axcess / gosystem_tax "
                "connector)"])

    if flat["basis"] == "federal_taxable":
        if federal is None:
            federal = compute_first_pass(wp)
        base = federal.taxable_income
    else:  # "agi" -- equal to total income in the v1 scope (no adjustments)
        base = wp.total_wages + wp.total_interest + wp.total_dividends
    taxable = max(0.0, base - flat["deduction"][status])
    tax = round(taxable * flat["rate"], 2)
    open_items.append(
        f"{state} credits, exemptions beyond the standard amount, and any "
        "local/municipal tax are not computed -- PREPARER MUST REVIEW")
    return StateDraft(
        state=state, filing_status=status, computed=True,
        rate=flat["rate"], state_taxable=round(taxable, 2), tax=tax,
        withholding=withholding, balance=round(tax - withholding, 2),
        open_items=open_items,
    )


def _render_state(out: list[str], sd: StateDraft) -> None:
    out += ["", f"DRAFT {sd.state} STATE RETURN (TY{STATE_TY2025['year']}) "
                "— first pass",
            "-" * 52]
    if not sd.computed:
        out.append("  Not computed in the first pass (see open items).")
        out.append(f"State withholding    : ${sd.withholding:,.2f}")
        return
    if sd.rate:
        out.append(f"State taxable income : ${sd.state_taxable:,.2f}")
        out.append(f"State tax (flat {sd.rate * 100:.2f}%)"
                   f" : ${sd.tax:,.2f}")
    else:
        out.append("  No state individual income tax.")
    out.append(f"State withholding    : ${sd.withholding:,.2f}")
    if sd.balance < 0:
        out.append(f"EST. STATE REFUND    : ${-sd.balance:,.2f}")
    else:
        out.append(f"EST. STATE BALANCE   : ${sd.balance:,.2f}")


def render_review_package(draft: Draft1040,
                          state: StateDraft | None = None) -> str:
    """The preparer-facing review package: draft + provenance + open items."""
    out = [DISCLAIMER, "",
           f"DRAFT FORM 1040 (TY{TY2025['year']}) — first pass",
           "=" * 52,
           f"Filing status        : {draft.filing_status.upper()}"]
    for desc, amount, source in draft.lines:
        desc = _report_safe(desc, fallback="line")
        source = _report_safe(source)
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
    if state is not None:
        _render_state(out, state)
    open_items = list(draft.open_items)
    if state is not None:
        open_items += [f"[{state.state}] {i}" for i in state.open_items]
    if open_items:
        out.append("")
        out.append("OPEN ITEMS FOR PREPARER (must be resolved before filing):")
        out += [f"  - {_report_safe(item, fallback='open item')}"
                for item in open_items]
    return "\n".join(out)


__all__ = [
    "DISCLAIMER", "DOC_TYPES", "TY2025", "STATE_TY2025", "STATE_CODES",
    "FILING_STATUSES",
    "SourceDoc", "Workpaper", "Draft1040", "StateDraft",
    "classify", "extract", "missing_items", "compute_first_pass",
    "infer_state", "compute_state_first_pass", "render_review_package",
]
