# Finance agent suite — the Office of the CFO, governed by construction

**Status:** design / roadmap. Companion to [`agent-factory.md`](agent-factory.md)
(how the factory emits sealed domain agents) and
[`../enterprise/architecture.md`](../enterprise/architecture.md) (the three-layer
control plane). This doc enumerates the **finance domain agents** — what each
one does (its job description), what it must be **connected to** to do that job,
and the **controls** that wrap it. We already ship the privacy/compliance and
security domains; finance is the next, and highest-stakes, tower.

> **Why finance is different from the domains we've shipped.** A privacy agent
> that hallucinates produces a bad memo. A finance agent that posts a wrong
> journal entry, releases a duplicate payment, or moves cash mis-states the
> books and can be a *crime* (SOX §906). The product is therefore **not the
> agents** — competent finance models are commodity — it is the **governance
> wrapper**: segregation of duties, maker-checker, dollar-threshold approvals,
> and a tamper-evident book of record, all enforced by the platform rather than
> trusted to the model. Lightwork already owns those primitives. This suite is
> the proof that the control plane was built for exactly this.

The cardinal rule, inherited verbatim from the existing
[`finance.toml`](../../packages/maverick-core/maverick/domains/finance.toml)
persona and applied to **every** agent below:

> *You may research and analyze freely, but you must NEVER place a trade, move
> money, post to the ledger, or change a system of record without explicit human
> confirmation in the same turn.*

---

## Contents

1. [How a finance agent maps onto Lightwork](#1-how-a-finance-agent-maps-onto-maverick)
2. [The finance control model (read this first)](#2-the-finance-control-model-read-this-first)
3. [Per-client customization — the dials](#3-per-client-customization--the-dials)
4. [The roster — seven towers of the CFO's office](#4-the-roster--seven-towers-of-the-cfos-office)
   - [Tower 1 — Controllership (record-to-report)](#tower-1--controllership-record-to-report)
   - [Tower 2 — FP&A (plan-to-perform)](#tower-2--fpa-plan-to-perform)
   - [Tower 3 — Treasury (cash-to-capital)](#tower-3--treasury-cash-to-capital)
   - [Tower 4 — Tax](#tower-4--tax)
   - [Tower 5 — Risk, Controls & Assurance](#tower-5--risk-controls--assurance)
   - [Tower 6 — Procurement & Vendor](#tower-6--procurement--vendor)
   - [Tower 7 — External & Investor Reporting](#tower-7--external--investor-reporting)
   - [Vertical packs (optional, enabled per client)](#vertical-packs-optional-enabled-per-client)
5. [The Finance Controller — supervisor & router (Layer A)](#5-the-finance-controller--supervisor--router-layer-a)
6. [Compliance-regime packs for finance (Layer B)](#6-compliance-regime-packs-for-finance-layer-b)
7. [Finance assessment templates (extend the assessment engine)](#7-finance-assessment-templates-extend-the-assessment-engine)
8. [Integrations catalog — what to connect, build order](#8-integrations-catalog--what-to-connect-build-order)
9. [Build sequence](#9-build-sequence)
10. [Honest caveats](#10-honest-caveats)

---

## 1. How a finance agent maps onto Lightwork

Every agent in this doc is **one domain pack** —
a [`DomainProfile`](../../packages/maverick-core/maverick/domain.py) emitted by
the agent factory, exactly like `finance.toml`/`legal.toml`/`privacy_compliance.toml`.
Nothing here needs a new agent abstraction; it needs new *packs* plus the
finance-specific connectors and policy packs. Each field of the pack is a control
surface:

| Pack field | What it controls for a finance agent |
|---|---|
| `compartment` | The Rung-2 **seal boundary**. Each finance function is its own compartment so a poisoned invoice that compromises AP can be quarantined without touching payroll or treasury (`maverick.quarantine`). |
| `persona` | The job description + the "never move money without a human" guardrail in the system prompt. |
| `allow_tools` / `deny_tools` | The **capability envelope** — becomes an attenuating [`Capability`](../../packages/maverick-core/maverick/capability.py). This is the technical substrate for **segregation of duties**: an agent literally cannot call a tool outside its grant, and a child agent can only ever *narrow* it. |
| `max_risk` | Risk ceiling. Money-moving tools (`stripe`, `plaid`, payment/trade tools) are classified **high** in [`tool_risk.py`](../../packages/maverick-core/maverick/safety/tool_risk.py); a `max_risk = "medium"` pack drops them from the registry entirely. |
| `allow_hosts` | Egress allow-list — pins the agent to its system-of-record vendor (e.g. `*.netsuite.com`) and nothing else. |
| `mcp_servers` | The external systems the agent connects to (ERP, payroll, bank). |
| `knowledge_sources` | The business's own docs — accounting policy manual, chart of accounts, delegation-of-authority matrix, contracts. |

On top of the pack, three already-shipped layers do the governance:

- **Layer A — oversight control plane** ([`governance.py`](../../packages/maverick-core/maverick/governance.py)):
  every consequential action is evaluated to `ALLOW` / `DENY` / `REQUIRE_HUMAN`
  and the verdict is written to the audit chain. This is **maker-checker**.
- **Consent / HITL** ([`safety/consent.py`](../../packages/maverick-core/maverick/safety/consent.py)):
  the `REQUIRE_HUMAN` gate resolves through the approvals queue / dashboard — the
  **four-eyes** sign-off, with a recorded decision.
- **Signed audit** ([`audit/`](../../packages/maverick-core/maverick/audit/)):
  an Ed25519 **Merkle-chained, append-only** log — the SOX-grade, tamper-evident
  **book of record** for every journal entry, approval, and override.

---

## 2. The finance control model (read this first)

These are **cross-cutting** controls that wrap *every* agent in the roster (§4);
§3 is how a client *tunes* them. They are the substance of the product. Each maps
to a primitive we already own; the few that need building are flagged *gap*.

### 2.1 Segregation of Duties (SoD) — the cardinal control

The classic rule: the four incompatible duties — **authorize, record, custody,
reconcile** — must never sit with one party. We enforce it structurally, not by
policy PDF: **each duty is a separate compartment + a separate principal with a
non-overlapping capability**, and the deny-set blocks the other side.

| Incompatible duty | Owning agent(s) | Enforcement |
|---|---|---|
| **Record** (enter invoice, draft JE) | AP, AR, GL/Close | `allow_tools` includes *draft/stage* tools only; `deny_tools` includes *post/release/pay*. |
| **Authorize** (approve invoice, approve JE) | Finance Controller (human-gated) | Approval is a `require_human` action — never an agent's own tool. |
| **Custody** (release payment, move cash) | Treasury/Payments | A *distinct* compartment; money tools are `high` risk → `require_human`. |
| **Reconcile** (match bank to ledger) | Account Reconciliation (1.11), Internal Audit | Read-only capability over *both* sides; cannot post the adjustments it finds. |

Because `Capability.attenuate()` is **narrow-only by construction**, a sub-agent
the GL agent spawns can never acquire a payment tool the GL agent itself lacks —
the "agent exceeded its permissions" failure mode is closed at the type level.

> *Gap to build:* an **SoD conflict linter** — a static check over the roster's
> packs that fails if any single compartment's `allow_tools` spans two
> incompatible duties (e.g. both `ap_stage_invoice` and `payments_release`). Lives
> next to the pack loader; it's the finance analogue of the capability tests.

### 2.2 Maker-checker / four-eyes / authorization matrix

| Control | How |
|---|---|
| **Any money movement requires a human** | `[governance] require_human_min_risk = "high"`. Payment, payroll-run, and trade tools are already `high`-risk, so they pause for sign-off automatically — the EU AI Act Art 14 gate, reused as the finance approval gate. |
| **Specific actions always pause** regardless of amount | `[governance] require_human_actions = ["post_journal_entry", "release_payment", "run_payroll", "vendor_master_change", "place_trade", "wire_transfer"]`. |
| **Hard prohibitions** (an analyst can *never* post) | `deny_tools` on the pack **and** `[governance] deny_actions` — defence in depth. |
| **Dollar-threshold / delegation-of-authority (DoA) tiers** | *gap* — see 2.3. |

### 2.3 Amount-aware authorization (the one real gap)

Today `governance.evaluate()` decides on **action name** and **risk floor**, not
on a **dollar amount**. Real finance approval matrices are tiered ("< $5k auto,
$5k–50k manager, > $50k CFO + board"). We need an **amount-aware policy
extension**: the tool call carries an `amount`/`currency`, and the policy gains
`require_human_above` / `deny_above` thresholds (per action, per currency),
evaluated alongside the existing risk floor. This is a small, surgical addition
to the `Policy`/`Verdict` types and is the single most important finance-specific
build. Until it lands, use `require_human_actions` to pause *all* money movement.

### 2.4 Immutable book of record (SOX §404 evidence)

Every tool call, every governance verdict, and every consent decision is already
written to the **Ed25519 Merkle-chained** audit log and is **offline-verifiable**
(`maverick audit verify`). For finance this *is* the audit trail an external
auditor relies on: who/what/when for every JE, approval, and override, tamper-
evident by cryptography rather than by database permissions. Turn on
`[audit] sign = true` and retention; it exceeds the SOX/Art-12 append-only baseline.

### 2.5 Read-only-by-default for systems of record

Mirroring `finance.toml`: every pack's `allow_tools` is read/analyze by default;
all *write* tools to the ERP/bank/payroll are either absent or `require_human`.
Agents **draft** journal entries, payment batches, and filings; **humans post,
release, and file.**

### 2.6 The other standing controls (all already owned)

| Control | Primitive |
|---|---|
| **Period-end / books-closed lock** | A governance pack that `deny_actions`-lists all posting tools once the period is locked (a "close-lock" regime pack, 2.x). |
| **Least privilege per finance role** | RBAC roles (`role_for_principal`) narrow the controller/AP-clerk/treasurer principals; child agents attenuate further. |
| **Data residency / egress lock** | `allow_hosts` per pack + enterprise egress lock pins LLM calls to local/self-hosted providers (GLBA, PCI). |
| **Encryption at rest** | AES-256-GCM seals world-DB + memory (bank details, payroll PII, contracts). |
| **Budget caps** | Long-running close/forecast/audit runs respect `Budget` (CLAUDE.md rule 3). |
| **Blast-radius containment** | Compartment seals quarantine a single finance function on a detected threat. |
| **Kill switch** | `~/.maverick/HALT` aborts every running finance goal. |
| **Sanctions / AML / KYC screening** | A screening tool every payment + vendor-onboarding path must pass (OFAC SDN, PEP) — *connector to build*, see §8. |
| **PCI-DSS** | Card PANs never stored; the secret/PII detector redacts them from logs; expense/AR agents touch tokens, not pans. |

### 2.7 Manual JEs, materiality & management override

Two of the highest-risk areas in any audit, both addressed structurally.
**Manual / top-side journal entries** are the #1 SOX hot spot — each is staged
with its supporting evidence and an *independent* human posts it (never the
preparer); late, post-close, round-dollar, and above-materiality entries are
auto-flagged. **Management override of controls** is the #1 fraud risk (SAS 99) —
the immutable Merkle audit chain makes it *detectable* by construction: nothing
reaches the ledger without a recorded, signed entry attributable to a principal,
so an override leaves evidence rather than a gap. **Materiality** is a client dial
(§3.5) that scales flux thresholds and review scope. Finance models run in
**sandboxed compute** over versioned, audited inputs rather than opaque
spreadsheets — closing the classic end-user-computing (EUC) gap.

### 2.8 Controls over autonomous agents are now in ICFR scope

A second-order point that is also a differentiator: once the "user" recording or
paying is an **agent**, the platform's own **access** (capabilities), **change**
(versioned packs + signed grants), and **operations** (budget, kill switch, audit)
controls *become* the SOX **IT general controls** over the financial-reporting
system. The evidence the platform emits for free — capability grants, the signed
audit chain, governance verdicts — is the ITGC evidence an auditor would otherwise
assemble by hand (see the `itgc` assessment template, §7).

---

## 3. Per-client customization — the dials

No two finance orgs want the same posture: a Series-B startup wants speed and will
auto-pay small invoices; a regulated bank wants every entry double-checked. The
suite is **one set of agents tuned per client through configuration, not forks** —
riding knobs the platform already has (`config.toml`, per-tenant workspaces,
tenant-dir packs that *win* over built-ins, RBAC roles, the governance `Policy`,
consent modes). Eight axes:

### 3.1 The automation ladder (per action class)

The headline dial the customer asked for. Every *action class* an agent can take
is bound to one of five levels; a client sets a default and overrides per action.

| Level | Behaviour | Maps to (existing primitive unless noted) |
|---|---|---|
| **L0 Observe** | Analyze & recommend only; no tool that writes to any system. | read-only `Capability` (no stage/post tools) |
| **L1 Draft** *(default for systems of record)* | Agent stages/prepares; a human posts/releases. | stage tool allowed; post/release on `deny_tools` + `require_human` |
| **L2 Approve (maker-checker)** | Agent prepares **and** executes, but only after explicit per-action human sign-off. | action in `require_human_actions`; consent `ask`/`dashboard` |
| **L3 Auto-under-threshold** | Executes autonomously below a configured amount/risk; above it, drops to L2. | amount-aware `require_human_above` *(the §2.3 build)* |
| **L4 Straight-through** | Executes within policy + budget; humans review after the fact (sampling). | `allow` + post-hoc audit sampling; low-risk, high-volume only |

The same agent runs at different levels per action: an AP agent can be **L3** for
3-way-matched invoices under $1k, **L2** for everything else, and its vendor-bank-
change action is **hard-floored** at L2 no matter what the client sets (§3.2).

### 3.2 Hard floors — what no client config can switch off

Customization must not let a client foot-gun into an uncontrolled state. A small
set of actions are **always ≥ L2 (human)** regardless of tier — the profile
compiler *refuses to build* a config that lowers them:

- wires/ACH above a platform floor, and **any** vendor/employee **bank-detail change**;
- the payroll run and payroll bank changes;
- period close, posting to a **locked** period, and chart-of-accounts changes;
- tax remittance and any statutory/SEC **filing**;
- anything that fails **sanctions/OFAC** screening (a hard **deny**, not a gate).

These are the finance analogue of the platform's "deny wins," enforced in code,
not left to per-client discipline.

### 3.3 Approval thresholds & delegation-of-authority (DoA)

The amount tiers behind L2/L3. Per action, per currency: dollar bands → how many
approvers and which role — the classic approval matrix as config, compiled to the
amount-aware policy (§2.3). Supports single-approver, **dual approval (four-eyes)**,
and board-tier, plus escalation and approver-of-record routing.

### 3.4 Enabled modules — towers, agents, verticals

The roster is a **menu**. A client enables the towers/agents it needs and the
**vertical packs** for its industry (§4). A 40-person SaaS shop runs
Controllership-lite + FP&A + the SaaS-metrics vertical and skips Consolidations,
Transfer Pricing, SEC, and Statutory. Built-in packs ship in the wheel; a client's
own/edited packs live in its tenant `domains/` dir and **win** over built-ins (the
existing loader precedence), so any agent can be re-personated or re-scoped without
a fork.

### 3.5 Accounting framework & policy choices

The numbers themselves are configurable: **GAAP vs IFRS**, fiscal-year end,
functional/reporting currency, **materiality** thresholds (which drive flux and
review scope, §2.7), capitalization threshold, depreciation methods, revenue
policies, and the chart of accounts. These live in `[finance]` config plus the
client's uploaded **accounting policy manual** (a knowledge source every agent cites).

### 3.6 Segregation-of-duties strictness

Large orgs enforce SoD hard; a five-person finance team physically cannot separate
every duty and relies on **compensating controls**. So SoD is itself a dial:
`enforce` (the linter blocks conflicts) vs `warn` (conflicts allowed but flagged,
and the affected actions are force-raised to L2 human review as the compensating
control). **Hard-floor** conflicts (§3.2) always block regardless.

### 3.7 Connectors, residency & data handling

Which **ERP / bank / payroll / tax** systems back each agent (`mcp_servers` per
pack), the **egress region** (residency — pin LLM calls to the client's
jurisdiction), encryption-at-rest on/off, retention periods, and per-agent
**budget/quotas**. All existing knobs, scoped per tenant.

### 3.8 The Finance Operating Profile (one bundle)

All of the above is one named, versioned object that onboarding (intake) produces
and the **wizard** edits (rule 6) — the finance analogue of a compliance-regime
pack. It compiles to capabilities + governance policy + consent config; it is
signed and audited, so *"what was this client allowed to automate, and who
approved that posture?"* is itself an audit-trail question.

```toml
# ~/.maverick/<tenant>/config.toml  — per client; tenant packs win over built-ins
[finance]
framework = "us_gaap"               # us_gaap | ifrs
fiscal_year_end = "12-31"
functional_currency = "USD"
materiality = 50000                 # drives flux / review thresholds
capitalization_threshold = 2500
enabled_towers    = ["controllership", "fpa", "treasury", "tax", "assurance"]
enabled_verticals = ["saas_metrics"]                   # opt-in industry module
regimes = ["sox", "us_gaap", "pci_dss", "aml_ofac"]    # strictest-wins union

[finance.automation]                # automation level per action class
default                 = "draft"           # L1
"ap.match_invoice"      = "auto_threshold"  # L3
"ap.release_payment"    = "approve"         # L2 (and hard-floored)
"gl.post_journal_entry" = "approve"         # L2
"fpa.build_report"      = "straight_through" # L4 (read-only output)

[finance.thresholds]                # amount-aware DoA (compiles to §2.3)
"ap.release_payment" = [
  { up_to = 1000,       approvers = 0 },                      # auto under $1k (L3)
  { up_to = 50000,      approvers = 1, role = "controller" },
  { up_to = 1000000000, approvers = 2, role = "cfo" },        # dual approval
]

[finance.sod]
mode = "enforce"                    # enforce (block) | warn (compensating controls)

[finance.approvals]
timeout = "fail_closed"            # finance never fail-opens an approval
```

> *Build note:* the **profile compiler** (profile → `Capability` + `Policy` +
> consent config, with hard-floor validation) and the **amount-aware policy**
> (§2.3) are the only two new mechanisms this customization layer needs; the rest
> is existing config. Both are small and belong with `governance.py`.

---

## 4. The roster — seven towers of the CFO's office

~43 agents (38 base + 5 council-added) across seven functional towers (each a sealed compartment), plus
optional **vertical packs** (end of §4) a client switches on for its industry. For
each: **Job** (what it does), **Connects to** (systems/knowledge), **Capability**
(envelope + the high-risk actions it may *only draft*), and **Controls** (beyond
the standing set in §2).

> **Assumption flagged:** the user's list said "FA". In finance "FA" most often =
> **Fixed Assets** (asset accounting), so that's agent 1.5 below. If "FA" meant
> *Financial Accounting* (the GL function) that's 1.1, and *Financial Analyst* is
> covered by FP&A (2.1). All three interpretations are in the roster.

A representative high-stakes pack in each tower is given as full TOML; the rest as
spec rows (same schema). Tool names marked `‹build›` are connectors that don't
exist yet (see §8); they follow the existing `verb_noun` tool convention.

---

### Tower 1 — Controllership (record-to-report)

The books. Highest concentration of SoD and SOX exposure.

#### 1.1 General Ledger & Close Agent
- **Job:** Owns the month/quarter/year-end close. Drafts and stages journal
  entries (accruals, prepaids, reclasses), runs reconciliations (balance-sheet
  account recs, bank rec), performs **flux/variance analysis** on the trial
  balance, maintains the chart of accounts, and assembles the close checklist
  and binder. Produces the draft financial statements (BS, P&L, cash flow).
- **Connects to:** ERP/GL (NetSuite, SAP, Oracle, QuickBooks, Xero) `‹build›`;
  close tools (BlackLine, FloQast) `‹build›`; `knowledge_search` over the
  **accounting policy manual + chart of accounts + close calendar**.
- **Capability:** read GL/sub-ledgers, `stage_journal_entry` (draft only).
  **Denies** `post_journal_entry`, `close_period` — those are `require_human`.
- **Controls:** SoD vs. AP/AR (records, can't authorize/pay); flux thresholds
  trigger a finding, not a posting; period-lock regime; every draft JE carries a
  source-document citation or it's flagged unverified.

```toml
# packages/maverick-core/maverick/domains/finance_gl_close.toml
name = "finance_gl_close"
compartment = "finance_controllership"   # shares a seal sector with AP/AR/FA
description = "General-ledger maintenance and the period-end close."

persona = """You are the General Ledger & Close specialist. Be precise with
debits/credits, tie every entry to a source document, and show your working.
You DRAFT and stage journal entries and reconciliations for a human accountant
to review and post -- you NEVER post to the ledger, close a period, or change the
chart of accounts yourself. Flag anything you cannot tie out as 'unverified'
rather than forcing a balance."""

allow_tools = [
    "read_file", "knowledge_search", "web_search",
    "gl_read_trial_balance", "gl_read_subledger", "gl_read_journal",
    "stage_journal_entry", "reconcile_accounts", "flux_analysis",
]
deny_tools = ["post_journal_entry", "close_period", "edit_chart_of_accounts"]
max_risk = "medium"
allow_hosts = ["*.netsuite.com", "*.sap.com"]
mcp_servers = ["ERP_NetSuite"]            # ‹build›
knowledge_sources = ["finance_accounting_policy", "finance_close"]
authoring = "manual"
```

#### 1.2 Accounts Payable (AP) Agent
- **Job:** Procure-to-pay. Ingests vendor invoices (OCR/email), performs the
  **3-way match** (PO ↔ receipt ↔ invoice), codes the GL account/cost center,
  catches duplicate invoices and price/quantity variances, and **stages** payment
  batches. Does **not** release payment.
- **Connects to:** AP/spend (Bill.com, Coupa, Tipalti, Ramp) `‹build›`; ERP for
  PO/receipt; vendor master (read); `Gmail`/`Google_Drive` for invoice intake.
- **Capability:** read PO/receipt/invoice, `stage_payment_batch` (draft). Denies
  `release_payment`, `vendor_master_change`.
- **Controls:** **SoD vs. Treasury** (AP records, Treasury has custody);
  duplicate-payment and ghost-vendor checks on every batch; OFAC screen on payee;
  invoices are ingested through the **shield** (a malicious invoice PDF is the
  canonical RAG-poisoning vector compartments defend against).

#### 1.3 Accounts Receivable (AR) & Collections Agent
- **Job:** Order-to-cash. Generates draft invoices, applies cash receipts to open
  invoices, runs the **AR aging**, drafts dunning/collections sequences, and flags
  credit risk and bad-debt candidates.
- **Connects to:** ERP/billing (Stripe, Chargebee, NetSuite) `‹build›`; bank feed
  for receipts (Plaid/Modern Treasury) `‹build›`; CRM (read) for customer context.
- **Capability:** read AR, `draft_invoice`, `propose_cash_application`. Denies
  `send_invoice`, `write_off_balance` (human-gated).
- **Controls:** SoD vs. cash-receipt custody; write-offs always `require_human`;
  collections messages to customers are `require_human` (outbound comms risk).

#### 1.4 Payroll Agent
- **Job:** Gross-to-net. Validates time/attendance and pay changes, computes
  gross-to-net (taxes, benefits, **garnishments**, 401k), reconciles the payroll
  register to the GL, drafts the payroll journal, and prepares (not files) payroll
  **tax deposits and returns** (941/W-2 equivalents). Flags off-cycle and ghost
  employees.
- **Connects to:** payroll/HCM (Workday, ADP, Gusto, Rippling, Paychex) `‹build›`;
  ERP for the payroll JE; tax tables/knowledge.
- **Capability:** read HCM/payroll, `stage_payroll_run`, `reconcile_payroll`.
  **Denies** `run_payroll`, `release_payroll_payment`, `edit_employee_bank_details`.
- **Controls:** **highest-PII compartment** — encryption at rest mandatory; SoD
  (cannot both edit bank details *and* run payroll); `run_payroll` is always
  `require_human` with the register diff shown; off-cycle runs flagged.

```toml
# packages/maverick-core/maverick/domains/finance_payroll.toml
name = "finance_payroll"
compartment = "finance_payroll"          # its own seal sector (PII isolation)
description = "Payroll preparation, gross-to-net, and payroll-tax drafting."

persona = """You are the Payroll specialist. Compute gross-to-net precisely, cite
the tax table/benefit rule behind every number, and reconcile the register to the
ledger before anything goes out. You PREPARE and stage payroll runs and payroll-
tax filings for a human to approve and release -- you NEVER run payroll, release a
payment, file a return, or edit an employee's bank details yourself. Treat all
employee data as confidential; never echo SSNs or full bank numbers."""

allow_tools = [
    "read_file", "knowledge_search",
    "hcm_read_employee", "payroll_read_register", "payroll_read_timesheet",
    "stage_payroll_run", "reconcile_payroll", "draft_payroll_tax",
]
deny_tools = [
    "run_payroll", "release_payroll_payment",
    "edit_employee_bank_details", "file_tax_return",
]
max_risk = "medium"
allow_hosts = ["*.workday.com", "*.adp.com", "*.gusto.com"]
mcp_servers = ["HCM_Workday"]            # ‹build›
knowledge_sources = ["finance_payroll_policy", "finance_tax_tables"]
authoring = "manual"
```

#### 1.5 Fixed Assets (FA) Agent
- **Job:** Asset accounting. Maintains the fixed-asset register, applies the
  **capitalization policy**, computes **depreciation/amortization** schedules
  (straight-line/DDB), handles additions/transfers/disposals, runs **impairment**
  indicators (ASC 360), and reconciles the FA sub-ledger to the GL. Tracks
  **leases** under ASC 842 (ROU assets / lease liabilities) unless split out.
- **Connects to:** ERP FA module / asset system `‹build›`; lease system; capex
  approvals; knowledge: cap policy, useful-life schedule.
- **Capability:** read FA register, `draft_depreciation_schedule`,
  `stage_asset_entry`. Denies `post_journal_entry`, `dispose_asset`.
- **Controls:** capitalize-vs-expense threshold enforced from policy; disposals
  `require_human`; impairment raises a finding for the Controller.

#### 1.6 Revenue Recognition Agent
- **Job:** ASC 606 / IFRS 15. Reads customer contracts, runs the **5-step model**
  (identify contract → performance obligations → transaction price → allocate →
  recognize), builds deferred-revenue and revenue-waterfall schedules, handles
  SSP allocation, variable consideration, and contract mods.
- **Connects to:** CRM/CPQ + billing (Salesforce, Stripe, Chargebee) `‹build›`;
  contract repository (`Google_Drive`); ERP for the rev JE; knowledge: rev-rec policy.
- **Capability:** read contracts/billing, `draft_revrec_schedule`,
  `stage_deferred_revenue`. Denies posting.
- **Controls:** every recognition decision cites the contract clause; judgmental
  calls (SSP, variable consideration) flagged for human review; ties to AR.

#### 1.7 Intercompany & Consolidations Agent
- **Job:** Multi-entity consolidation. Drafts **intercompany eliminations**,
  performs **FX translation** (CTA), allocations, and minority-interest, and
  produces consolidated statements across the entity tree.
- **Connects to:** consolidation tool (Oracle FCCS, OneStream) / multi-book ERP
  `‹build›`; FX rate source; knowledge: legal-entity structure.
- **Capability:** read all entity ledgers, `draft_elimination`, `draft_translation`.
  Denies posting to any entity book.
- **Controls:** intercompany must net to zero or it's a finding; cross-entity reads
  respect tenancy; translation rates sourced, not invented.

#### 1.8 Expense & T&E Agent
- **Job:** Audits expense reports and corporate-card transactions against the
  **T&E policy**, flags out-of-policy/duplicate/personal spend, reconciles the
  card statement, and drafts the expense accrual.
- **Connects to:** Concur/Expensify/Ramp/Brex `‹build›`; card feed; policy knowledge.
- **Capability:** read expenses/card, `flag_policy_violation`, `draft_accrual`.
  Denies `approve_expense`, `reimburse`.
- **Controls:** reimbursement `require_human`; PCI — card tokens only; SoD vs. AP.

#### 1.9 Cost Accounting & Inventory / COGS Agent
- **Job:** Standard- and actual-costing, BOM/routing **cost roll-ups**, inventory
  valuation (FIFO/LIFO/weighted-avg), WIP, **manufacturing variances** (purchase-
  price, material-usage, labor, overhead absorption), landed cost, lower-of-cost-or-
  NRV, **excess-&-obsolete reserves**, and cycle-count/shrinkage reconciliation
  feeding COGS. *(Essential for any company with physical product — the single
  biggest omission from a generic roster.)*
- **Connects to:** ERP inventory/cost module + MRP/manufacturing + WMS `‹build›`;
  procurement (for PPV); knowledge: cost policy + standard-cost book.
- **Capability:** read inventory/cost/production, `draft_cost_roll`,
  `variance_analysis`, `draft_inventory_adjustment`. Denies posting revaluations.
- **Controls:** write-downs/revaluations and cycle-count adjustments
  `require_human`; SoD vs. warehouse custody; ties to GL.

#### 1.10 Lease Accounting Agent (ASC 842 / IFRS 16)
- **Job:** Lease **classification** (finance vs operating), ROU-asset & lease-
  liability schedules, discount-rate (IBR) determination, remeasurement on
  modifications, short-term/low-value elections, **embedded-lease** detection, and
  disclosures. (Split out from Fixed Assets — material and judgmental enough to
  stand alone.)
- **Connects to:** lease system (LeaseQuery, Visual Lease) `‹build›`, contract repo,
  ERP for the lease JE, rate sources; knowledge: lease policy.
- **Capability:** read leases, `draft_lease_schedule`, `classify_lease`. Denies posting.
- **Controls:** classification judgment flagged for review; modifications gated;
  ties to FA (1.5) / GL.

#### 1.11 Account Reconciliation Agent
- **Job:** The independent **"reconcile" duty** named in §2.1. Reconciles balance-
  sheet accounts (bank, subledger-to-GL, intercompany, suspense/clearing),
  validates and ages reconciling items, certifies completeness, and flags stale/
  unreconciled balances — prepared for *independent* human review.
- **Connects to:** GL + all subledgers + bank feeds (read **both** sides), recon
  tool (BlackLine) `‹build›`; knowledge: recon standards.
- **Capability:** read both sides + `draft_reconciliation`, `flag_recon_exception`.
  **Denies `post_adjustment`** — a found difference goes *back* to the recorder.
- **Controls:** independence is the whole point — it cannot post the adjustments it
  finds, closing the SoD loop; aged/stale items escalate.

#### 1.12 Financial Master-Data & CoA Governance Agent
- **Job:** Integrity of **financial master data** — chart of accounts, cost/profit
  centers, dimensions, legal entities, currencies, bank master. Dedup, validate,
  enforce mapping standards (local↔group CoA), and control changes.
- **Connects to:** ERP master data / MDM `‹build›`; knowledge: CoA design + mapping policy.
- **Capability:** read master data, `propose_master_change`, `validate_mapping`.
  **Denies `edit_chart_of_accounts`** and master commits.
- **Controls:** master data drives *every* report → all changes gated
  `require_human`; SoD vs. transaction recording; full change audit.

---

### Tower 2 — FP&A (plan-to-perform)

Lower write-risk (FP&A rarely touches the ledger) but high **decision-influence**
risk — bad numbers steer real spending. `max_risk = "low"` for most.

#### 2.1 FP&A / Management Reporting Agent
- **Job:** Budget vs. actuals, **variance analysis** with narrative, board/management
  reporting packs, KPI and unit-economics dashboards, headcount planning support.
- **Connects to:** EPM/planning (Anaplan, Adaptive, Pigment) `‹build›`; ERP actuals
  (read); BI (read); knowledge: the operating plan.
- **Capability:** read actuals/plan, `build_variance_report`, `build_board_pack`.
  No write tools.
- **Controls:** every figure cites its source query; assumptions stated explicitly;
  read-only — cannot change the plan of record.

```toml
# packages/maverick-core/maverick/domains/finance_fpa.toml
name = "finance_fpa"
compartment = "finance_fpa"
description = "Budgeting, variance analysis, and management reporting."

persona = """You are the FP&A specialist. Tie every number to its source query,
state your assumptions and drivers explicitly, and separate fact (actuals) from
estimate (forecast). You produce analysis and draft reporting packs for a human
owner; you do not change the plan of record or any ledger. When the data does not
support a conclusion, say so rather than smoothing the story."""

allow_tools = [
    "read_file", "knowledge_search", "web_search",
    "epm_read_plan", "gl_read_actuals", "bi_read_metric",
    "build_variance_report", "build_board_pack",
]
deny_tools = ["epm_write_plan", "post_journal_entry"]
max_risk = "low"
mcp_servers = ["EPM_Adaptive"]           # ‹build›
knowledge_sources = ["finance_operating_plan", "finance_kpi_defs"]
authoring = "manual"
```

#### 2.2 Forecasting Agent
- **Job:** Driver-based revenue/expense/headcount forecasts, **scenario & sensitivity**
  modeling (base/upside/downside), rolling re-forecasts, and model-vs-actual
  backtesting. Surfaces the drivers and their elasticities.
- **Connects to:** EPM (read/scenario), ERP actuals, market data (FRED, web).
- **Capability:** read + `build_forecast_scenario` (sandboxed compute). No plan writes.
- **Controls:** scenarios are labeled estimates; methodology + confidence stated;
  compute runs sandboxed (rule 4); backtest error reported, not hidden.

#### 2.3 Cash-Flow & Liquidity Forecasting Agent
- **Job:** The **13-week cash forecast**, working-capital analysis (DSO/DPO/DIO,
  cash-conversion cycle), and liquidity runway/burn. Bridges AR, AP, and payroll
  timing into a cash view.
- **Connects to:** bank feeds (Plaid/Modern Treasury) `‹build›`, AP/AR sub-ledgers,
  payroll calendar.
- **Capability:** read cash/AP/AR, `build_cashflow_forecast`. No money movement.
- **Controls:** feeds Treasury (2.x) but cannot itself sweep/transfer; runway
  assumptions explicit.

#### 2.4 CapEx & Capital-Planning Agent
- **Job:** Capital **budgeting and appraisal** — business cases, ROI/NPV/IRR/
  payback, the capital-request workflow, capex-vs-opex classification guidance, and
  budget-vs-actual capex tracking with **post-investment review**. (Distinct from
  Fixed Assets, which accounts for the asset *after* the spend.)
- **Connects to:** EPM/capital-planning, procurement (capex POs), FA, ERP actuals;
  knowledge: capital policy + hurdle rates.
- **Capability:** read + `build_capital_case`, `track_capex`. Denies approving capital.
- **Controls:** capital approval `require_human` per DoA tier (§3.3); ROI
  assumptions stated; hands approved assets to FA (1.5).

#### 2.5 Workforce & Headcount-Cost Planning Agent
- **Job:** People-cost planning — **position/headcount plans**, compensation
  modeling (salary, bonus, benefits, payroll tax, equity), hiring-plan phasing,
  attrition, and reconciliation of plan to HRIS actuals. (People cost is the
  largest line of opex for most firms; it deserves its own model.)
- **Connects to:** HRIS/HCM (read) `‹build›`, EPM, payroll actuals; knowledge: comp
  bands + org structure.
- **Capability:** read HRIS/plan + `build_headcount_plan`, `model_comp`. No writes.
- **Controls:** **high-PII** — read-only over HRIS, encryption at rest, compensation
  data restricted by least privilege; feeds FP&A (2.1).

---

### Tower 3 — Treasury (cash-to-capital)

**Custody** of cash. The money-movement tower — every write is `high`-risk and
`require_human`. This is where the existing `finance.toml`/IBKR pattern lives.

#### 3.1 Treasury & Cash Management Agent
- **Job:** Daily cash positioning across bank accounts, **proposes** sweeps/funding
  between accounts, monitors **debt covenants**, manages bank-account admin info,
  and forecasts short-term liquidity. **Proposes** wires/ACH; never sends them.
- **Connects to:** TMS (Kyriba) / banking aggregation (Modern Treasury, Plaid),
  bank portals `‹build›`; debt schedule knowledge.
- **Capability:** `bank_read_balance`, `bank_read_transactions`, `propose_transfer`.
  **Denies** `wire_transfer`, `release_payment`, `ach_send`.
- **Controls:** **strict SoD vs. AP** (AP stages payee invoices, Treasury moves
  cash, neither approves); every transfer proposal is `require_human` with dual
  approval for amounts over the DoA threshold (2.3); covenant breach → finding +
  alert.

```toml
# packages/maverick-core/maverick/domains/finance_treasury.toml
name = "finance_treasury"
compartment = "finance_treasury"         # custody — isolated from controllership
description = "Cash positioning, liquidity, and treasury operations."

persona = """You are the Treasury specialist. Know the cash position to the dollar
across every account, cite the bank source for each balance, and watch debt
covenants. You PROPOSE transfers, sweeps, and fundings for a human treasurer to
approve and release -- you NEVER send a wire, release a payment, or move cash
yourself. Surface a covenant breach or a negative-balance risk immediately."""

allow_tools = [
    "read_file", "knowledge_search", "web_search",
    "bank_read_balance", "bank_read_transactions", "covenant_check",
    "propose_transfer", "build_cashflow_forecast",
]
deny_tools = ["wire_transfer", "ach_send", "release_payment"]
max_risk = "medium"                       # read/propose only; money tools are high → dropped
allow_hosts = ["*.moderntreasury.com", "*.kyriba.com"]
mcp_servers = ["Treasury_ModernTreasury"]  # ‹build›
knowledge_sources = ["finance_debt_schedule", "finance_treasury_policy"]
authoring = "manual"
```

#### 3.2 Investments / Portfolio Agent
- **Job:** Manages the corporate investment portfolio (money-market, T-bills,
  fixed income) per the **Investment Policy Statement** — researches, prices,
  proposes allocations and rebalances, monitors yield/duration/credit limits.
  This is the existing `finance.toml`, specialized.
- **Connects to:** **`Interactive_Brokers_IBKR` (exists today)** — `search_contracts`,
  `get_price_snapshot/history`, `get_account_summary/positions`; Bloomberg `‹build›`.
- **Capability:** all IBKR **read** tools + `propose_trade`. **Denies**
  `create_order_instruction`, `delete_order_instruction` (verbatim from finance.toml).
- **Controls:** trades `require_human` in the same turn; IPS limits (concentration,
  credit quality, duration) enforced as findings; egress pinned to `*.interactivebrokers.com`.

#### 3.3 FX & Hedging Agent
- **Job:** Quantifies currency exposure (transaction + translation), proposes hedges,
  and supports **hedge-accounting** documentation (ASC 815) — effectiveness testing,
  designation memos.
- **Connects to:** ERP exposure data, FX rates, IBKR/bank FX `‹build›`.
- **Capability:** read exposure/rates, `propose_hedge`. Denies executing FX trades.
- **Controls:** hedge execution `require_human`; effectiveness tests cite the method.

#### 3.4 Capital Markets & Debt Agent
- **Job:** Maintains debt/lease schedules, computes interest and amortization,
  tests **covenant compliance**, models refinancing/issuance scenarios, tracks
  the maturity ladder.
- **Connects to:** debt register, bank/agent statements, market rates.
- **Capability:** read debt data, `model_refinancing`, `covenant_check`. No execution.
- **Controls:** covenant breaches escalate; any issuance/draw is `require_human`.

---

### Tower 4 — Tax

Preparation and analysis; **filing and payment are always human.**

#### 4.1 Tax Provision Agent
- **Job:** ASC 740 / IAS 12. Computes the current and deferred tax provision,
  builds the **effective-tax-rate** reconciliation, tracks deferred-tax assets/
  liabilities and valuation allowances, and drafts the tax footnote.
- **Connects to:** ERP/trial balance, tax-provision tool (ONESOURCE, Corptax) `‹build›`,
  prior returns (knowledge).
- **Capability:** read TB/prior tax, `compute_tax_provision`, `draft_tax_footnote`.
  Denies posting/filing.
- **Controls:** positions cite authority; uncertain positions (FIN 48/UTP) flagged;
  ties to the GL provision JE (drafted, human-posted).

#### 4.2 Tax Compliance & Filing Prep Agent
- **Job:** Prepares (not files) income, **sales & use / VAT / GST**, and other
  returns; validates **nexus** and taxability; reconciles tax collected vs. remitted;
  assembles filing workpapers and the calendar.
- **Connects to:** sales-tax engine (Avalara, Vertex, Sovos) `‹build›`, ERP, jurisdiction
  rules (knowledge).
- **Capability:** read transactions/tax, `prepare_return`, `validate_nexus`.
  **Denies** `file_return`, `remit_tax`.
- **Controls:** filing + remittance always `require_human`; jurisdiction rules
  cited; deadline misses escalate.

#### 4.3 Transfer Pricing Agent
- **Job:** Tests intercompany pricing for **arm's-length** compliance, maintains
  OECD BEPS documentation (master file / local file / **CbCR**), and models TP
  adjustments.
- **Connects to:** intercompany ledger, benchmarking data `‹build›`, TP policy (knowledge).
- **Capability:** read IC data, `tp_benchmark`, `draft_tp_documentation`. No posting.
- **Controls:** method + comparables cited; adjustments routed to Consolidations
  (1.7) as drafts.

---

### Tower 5 — Risk, Controls & Assurance

The "second and third lines of defense." These agents **watch the other agents**
(and the humans) — and crucially, they have **read-only** capability over the
domains they assure, never the ability to fix what they find (independence).

#### 5.1 SOX / Internal Controls (ICFR) Agent
- **Job:** Maintains the **Risk-Control Matrix (RCM)**, maps controls to COSO
  components and SOX assertions, **tests control operating effectiveness** (pulls
  samples, checks evidence), tracks **deficiencies/remediation**, and drafts
  §302/§404 support. Monitors **SoD conflicts** across the live roster (2.1) and
  **ITGCs** (access, change, ops) — directly relevant since the "users" are agents.
- **Connects to:** GRC (AuditBoard, Workiva) `‹build›`; the **Lightwork audit chain
  itself** (the agents' own activity is auditable evidence); RCM (knowledge).
- **Capability:** **read-only** across all finance compartments + audit log;
  `test_control`, `log_deficiency`, `run_assessment` (SOX template, §7).
- **Controls:** independence — cannot modify any controlled process; testing is
  sampled and evidence-cited; deficiencies are findings for a human control owner.

```toml
# packages/maverick-core/maverick/domains/finance_sox.toml
name = "finance_sox"
compartment = "finance_assurance"        # independent of the towers it tests
description = "SOX / ICFR control testing, SoD monitoring, and deficiency tracking."

persona = """You are the SOX & Internal Controls specialist. Map every control to
its COSO component and SOX assertion, test operating effectiveness against
sampled evidence, and cite the evidence for every conclusion. You are independent:
you TEST and REPORT, and you raise deficiencies for a human control owner to
remediate -- you NEVER post entries, approve transactions, or 'fix' a control you
are testing. 'Unverified' is the honest result when the evidence is missing; never
mark a control effective without seeing the evidence."""

allow_tools = [
    "read_file", "knowledge_search",
    "gl_read_journal", "audit_log_read", "sod_conflict_scan",
    "test_control", "log_deficiency", "run_assessment",
]
deny_tools = [
    "post_journal_entry", "release_payment", "run_payroll",
    "stage_journal_entry", "edit_chart_of_accounts",
]
max_risk = "low"
mcp_servers = ["GRC_AuditBoard"]         # ‹build›
knowledge_sources = ["finance_rcm", "finance_coso_policy"]
authoring = "manual"
```

#### 5.2 Internal Audit Agent
- **Job:** Risk-based **audit planning**, fieldwork, workpaper drafting, and
  findings/recommendations across financial and operational areas. Follows up on
  remediation. Independent (third line).
- **Connects to:** all finance systems (read), GRC, audit log, prior workpapers.
- **Capability:** read-only everywhere + `draft_workpaper`, `log_finding`.
- **Controls:** independence (no operational capability); risk-ranked; evidence-cited.

#### 5.3 External-Audit / PBC Liaison Agent
- **Job:** Manages the **prepared-by-client (PBC)** list, pulls and packages
  requested evidence for external auditors, tracks open items, and drafts responses
  to audit queries.
- **Connects to:** all systems (read), document repository, the signed audit chain
  (offer auditors `maverick audit verify` as tamper-evidence).
- **Capability:** read + `assemble_evidence_package`. **Denies** any external send
  (sharing with auditors is `require_human` — data leaves the building).
- **Controls:** every package is human-released; data minimization in what's shared.

#### 5.4 Fraud Detection Agent
- **Job:** Hunts financial fraud — **ghost vendors/employees**, duplicate & split
  payments, **AP/payroll fraud**, channel stuffing, expense abuse. Applies forensic
  techniques (**Benford's Law**, **Beneish M-score**, **Altman Z-score**), vendor-
  bank-change detection, and round-dollar/just-under-threshold patterns.
- **Connects to:** AP/AR/payroll/GL (read), vendor & employee master (read),
  bank-change feeds; case-management `‹build›`.
- **Capability:** read everything in finance + `run_fraud_model`, `open_case`.
  No mutation.
- **Controls:** outputs are **risk-ranked leads**, never accusations or actions;
  cases routed to a human investigator; high false-positive cost acknowledged —
  evidence and base rates stated with every flag.

#### 5.5 Anomaly Detection Agent
- **Job:** Continuous, unsupervised monitoring of the transaction streams for
  **statistical outliers** — unusual amounts/timing/counterparties, new GL-account
  usage, post-close entries, **manual JE spikes**, weekend/after-hours postings.
  Complements 5.4 (anomaly = "weird"; fraud = "weird *and* motivated").
- **Connects to:** GL/AP/AR transaction feeds (read/stream), the audit log.
- **Capability:** read/stream + `flag_anomaly`. No mutation.
- **Controls:** tuned to a reviewable alert volume (budget-bounded); every alert
  carries the baseline it deviated from; feeds SOX/IA, not auto-blocking.

#### 5.6 Financial Risk / ERM Agent
- **Job:** Maintains the **enterprise risk register** and **KRIs** for financial
  risks (liquidity, credit, market, concentration, operational), quantifies
  exposure, and drafts risk reporting for the audit/risk committee.
- **Connects to:** treasury, AR/credit, market data, the risk register (knowledge).
- **Capability:** read + `update_risk_register` (draft), `build_risk_report`.
- **Controls:** read-only over operations; risk ratings methodology-cited.

#### 5.7 Credit Risk Agent
- **Job:** Sets/recommends customer **credit limits**, scores creditworthiness,
  monitors the AR portfolio for deterioration, and drafts bad-debt/allowance
  (CECL) estimates.
- **Connects to:** AR sub-ledger, credit bureaus (D&B, Experian) `‹build›`, payment history.
- **Capability:** read + `score_credit`, `propose_credit_limit`. Denies setting limits.
- **Controls:** limit changes `require_human`; **FCRA**-style fairness if consumer
  credit data is used (routes to the privacy/compliance domain's bias checks).

#### 5.8 AML / Financial-Crime Agent
- **Job:** **Customer/counterparty-side** financial-crime controls (for clients that
  move customer money — fintech, marketplace, lender, bank): KYC/CDD/EDD, customer
  **sanctions & PEP** screening, **transaction monitoring** for money-laundering
  typologies, alert triage, and **SAR/STR** drafting + CTR thresholds. Distinct from
  internal occupational fraud (5.4): AML is about *counterparties* laundering; fraud
  is about *loss to the company*.
- **Connects to:** payments/transaction ledger, KYC/identity at onboarding,
  screening (OFAC, Dow Jones, ComplyAdvantage) `‹build›`, case management, regulator
  portals; knowledge: the BSA/AML program + typologies.
- **Capability:** read transactions/customers + `screen_sanctions`,
  `run_aml_monitoring`, `open_case`, `draft_sar`. **Denies `file_sar`** and customer
  block/unblock (human).
- **Controls:** SAR filing is a legal **human** act; customer blocking gated; alert
  base rates stated; independent of the business line; its own regulated compartment.

---

### Tower 6 — Procurement & Vendor

The front of procure-to-pay; **master-data integrity** is the control story.

#### 6.1 Procurement & Spend-Analysis Agent
- **Job:** Builds the **spend cube**, finds savings/consolidation, checks contract
  compliance and maverick (off-contract) spend, supports sourcing and PO drafting.
- **Connects to:** P2P (Coupa, Ariba) `‹build›`, ERP spend, contract repository.
- **Capability:** read spend/contracts, `analyze_spend`, `draft_po`. Denies PO approval.
- **Controls:** PO issuance `require_human`; SoD vs. AP and vendor master.

#### 6.2 Vendor Master & Vendor-Risk Agent
- **Job:** Vendor onboarding & **master-data integrity** — dedup, validate bank
  details (the #1 payment-fraud vector), **OFAC/sanctions + PEP screening**,
  W-9/W-8 collection, and ongoing vendor risk. Bridges to the existing
  `vendor_risk` assessment template.
- **Connects to:** vendor master/ERP, sanctions/KYB (OFAC, Dow Jones, ComplyAdvantage)
  `‹build›`, tax-ID validation.
- **Capability:** read vendor data, `screen_sanctions`, `validate_bank_details`,
  `run_assessment` (vendor_risk). **Denies** `vendor_master_change`,
  `approve_vendor`.
- **Controls:** **bank-detail changes always `require_human`** (intercepts business-
  email-compromise fraud); sanctions hit blocks onboarding; SoD vs. AP (whoever
  onboards a vendor can't pay it).

---

### Tower 7 — External & Investor Reporting

Where numbers leave the building — every output is human-certified.

#### 7.1 Financial / SEC Reporting Agent
- **Job:** Drafts the financial statements + footnotes, the **10-K/10-Q** (MD&A,
  risk factors), and the **XBRL** tagging; ties the filing to the trial balance;
  runs disclosure checklists.
- **Connects to:** consolidation output, Workiva/SEC EDGAR `‹build›`, prior filings
  (knowledge), accounting-standards library.
- **Capability:** read consolidated data, `draft_filing`, `tag_xbrl`,
  `run_disclosure_checklist`. **Denies** `file_with_sec` (always human).
- **Controls:** every disclosure cites its standard + source figure; **§302/§906
  certification is a human act** the agent only supports; filing `require_human`.

#### 7.2 Investor-Relations / Earnings Support Agent
- **Job:** Drafts earnings releases, board/investor decks, and **Reg-G-compliant
  non-GAAP** reconciliations; prepares Q&A; ensures consistency with the filing.
- **Connects to:** reporting outputs, market data, prior IR materials (knowledge).
- **Capability:** read + `draft_earnings_materials`. **Denies** any publish/send.
- **Controls:** **Reg FD** — no selective disclosure; non-GAAP reconciled to GAAP;
  all external release `require_human`; forward-looking statements flagged.

#### 7.3 Equity & Stock-Based-Comp Agent *(optional / venture-backed)*
- **Job:** Cap-table maintenance, **ASC 718** stock-comp expense (options/RSUs,
  vesting, forfeitures), dilution and **409A** support, ESPP accounting.
- **Connects to:** cap-table system (Carta, Pulley) `‹build›`, payroll (for ESPP/RSU
  tax), ERP for the comp JE.
- **Capability:** read cap table, `compute_sbc_expense`, `draft_sbc_entry`. No posting.
- **Controls:** ties to payroll-tax on RSU vesting; 409A is human-owned.

#### 7.4 Statutory & Local-GAAP Reporting Agent
- **Job:** Per-jurisdiction **statutory financial statements** (distinct from the
  consolidated group US-GAAP/IFRS view), GAAP-to-local-GAAP/stat adjustments, local
  filing requirements, and per-entity audit support — for multinationals that file
  local books in every country of operation.
- **Connects to:** per-entity ledgers, a statutory-reporting tool + local filing
  portals `‹build›`; knowledge: local-GAAP rules + the entity filing calendar.
- **Capability:** read entity ledgers + `draft_statutory_accounts`,
  `map_gaap_to_local`. Denies filing (human).
- **Controls:** local rules cited; filing `require_human`; ties to Consolidations
  (1.7) and Master-Data mapping (1.12).

---

### Vertical packs (optional, enabled per client)

The seven towers fit a generic company. **Industry verticals change the roster
materially**, so they ship as opt-in modules a client switches on (§3.4) — not as
generic agents bent out of shape:

| Vertical pack | For | Adds |
|---|---|---|
| **Project / Job Costing & WIP** | construction, agencies, prof-services | percentage-of-completion, project P&L, WIP schedules, milestone billing |
| **SaaS Revenue Ops & Unit Economics** | SaaS / subscription | ARR/MRR/NRR, churn, CAC/LTV, cohorts, usage billing, deferred-rev waterfall |
| **Fund & Grant Accounting** | nonprofit, government, research | restricted vs unrestricted funds, grant compliance, fund-balance reporting |
| **Regulatory Capital & Financial Reporting** | banks, broker-dealers, insurers | Call Reports / FR Y-9C / FINREP-COREP, Basel / Solvency II capital, liquidity |
| **Profitability & Cost Allocation (ABC)** | any multi-product/segment firm | product/customer/segment profitability, activity-based allocations |
| **Insurance & Risk Financing** | any (corporate insurance program) | coverage, claims, premiums, captives |
| **ESG / Sustainability Finance** | EU / large / public | CSRD-ESRS, ISSB (IFRS S1/S2), carbon accounting, EU Taxonomy |
| **Unclaimed Property / Escheatment** | US multistate | multistate escheatment compliance (also attaches to Tax, 4.2) |

Healthcare revenue cycle, real-estate property accounting, and oil-&-gas joint-
interest billing/depletion are further verticals on the same opt-in model.

---

### Council-added agents (from the adversarial review)

Five seats the adversarial-council pass surfaced as missing; folded into the roster under the
same SoD + maker-checker + audit discipline. Full skills in [`agent-skills-catalog.md`](agent-skills-catalog.md).

#### +1 Treasury Payments / Disbursements Agent  *(Tower 3 — the custody node)*
- **Job:** Execute/release **approved** payments; positive-pay, sanctions-at-payment, payment-rail ops — the literal **custody** node of the four-way SoD the model assumed but never staffed.
- **Connects to:** Kyriba / Modern Treasury / bank portals `‹build›`; Fedwire / ACH-NACHA / RTP / SWIFT-ISO 20022.
- **Capability:** read approved batches + `propose_settlement`. **Denies** `release_payment`/`wire` (always `require_human`); sealed from AP (records) and the GL.
- **Status:** **Partial** (governance gate shipped; rails + amount-aware DoA to build).

#### +2 Model Risk Management / Validation Agent (SR 11-7)  *(Tower 5)*
- **Job:** Independently validate the suite's models (CECL, VaR, ASC 718, forecasting, anomaly ML) — conceptual soundness, backtesting, outcome analysis.
- **Connects to:** model owners' outputs (read), `pandas_query`/`sql_query`.
- **Capability:** read-only + `validate_model`, `log_model_finding`. Independent of model owners.
- **Status:** **Gap**.

#### +3 Pension & Benefits-Accounting Agent  *(Tower 1)*
- **Job:** DB/OPEB obligation, actuarial gain/loss, funded status; 401(k) Form 5500 + plan-audit support.
- **Connects to:** actuary/benefits data, HRIS, the GL.
- **Capability:** read + `draft_pension_entry`. No posting.
- **Status:** **Gap** (ASC 715/712).

#### +4 ESG Controllership Agent  *(Tower 1/7)*
- **Job:** The controllership/data side of sustainability (external disclosure stays with Strategy 7.3) — GHG Scope 1/2/3 data, CSRD/ESRS controls, assurance-readiness over non-financial data.
- **Connects to:** the finance ESG vertical, ops data, ESG platforms `‹build›`.
- **Capability:** read + `collect_esg_data`, `draft_esg_controls`.
- **Status:** **Gap** (deconflict with Strategy 7.3).

#### +5 Government-Contract & Cost-Accounting Agent  *(Tower 1, vertical)*
- **Job:** For gov contractors — FAR Part 31, CAS, DCAA incurred-cost & indirect-rate work.
- **Connects to:** the gov-contract ERP, DCAA submission portals `‹build›`.
- **Capability:** read + `draft_indirect_rates`, `prepare_incurred_cost`. Filing human.
- **Status:** **Gap** (vertical).

---

## 5. The Finance Controller — supervisor & router (Layer A)

Above the towers sits one **Finance Controller agent** = the finance instance of
the **oversight control plane** (architecture §Layer A). It is not another
specialist; it is the router + supervisor:

- **Routes** an incoming finance task to the right tower agent(s), respecting
  compartment seals (a close task fans out to GL, FA, Payroll, Tax-provision; their
  results consolidate).
- **Owns the maker-checker queue** — it is the human-facing surface where every
  `REQUIRE_HUMAN` verdict (post, pay, run payroll, trade, file) lands for
  sign-off, with the diff/evidence attached.
- **Enforces SoD across the fleet** — it holds the parent capability; each tower
  agent is spawned with an *attenuated* grant, so the roster's separation is
  guaranteed by construction, not by configuration discipline.
- **Carries the period-lock and DoA policy** (the governance `Policy` / regime
  packs in §2.2–2.6).

This is the "controller of controllers." It maps 1:1 onto the **Fleet + supervisor**
abstraction the enterprise architecture already calls for (Layer C), specialized
to finance.

---

## 6. Compliance-regime packs for finance (Layer B)

Same pattern as the EU-AI-Act / NIST packs: each regime compiles to a governance
`Policy` + an **evidence mapping** surfaced by a posture report (generalize
`compliance_report()` / `collect_soc2_evidence()` to a `finance status` view).

| Regime pack | What it asserts | Compiles to |
|---|---|---|
| **SOX (§302/§404/§409/§906)** | ICFR exists & is tested; mgmt certifies; tamper-evident records; SoD | `require_human` on all postings/payments; SoD linter (2.1); signed audit = the record; SOX assessment template (§7). |
| **COSO 2013** | 5 components / 17 principles of internal control | the RCM + control tests (5.1) mapped to principles. |
| **US GAAP / IFRS** | recognition & disclosure standards (606, 842, 740, 718, 805) | persona + knowledge packs per standard; rev-rec/lease/tax/SBC agents cite the clause. |
| **PCI-DSS** | cardholder data protection | secret/PII redaction; no-PAN-storage; tokenization at AR/expense. |
| **GLBA / data residency** | financial-privacy safeguards | egress lock + encryption at rest + tenancy. |
| **AML / BSA / OFAC** | sanctions & suspicious-activity controls | mandatory `screen_sanctions` on every payment + vendor path; flags route to a human (SAR is a human act). |
| **SEC (Reg S-X / S-K / FD / G)** | public-reporting form & fairness | reporting tower (7.x); all external release `require_human`; non-GAAP reconciled. |
| **IRS / state & local tax** | filing & remittance obligations | tax tower (4.x); `file_return`/`remit_tax` always human; deadline calendar. |

Strictest-wins union, exactly like the existing regime engine — a US public
company enables SOX + GAAP + SEC + PCI + AML; a private EU company swaps in
IFRS + GDPR residency.

---

## 7. Finance assessment templates (extend the assessment engine)

The [`assessment.py`](../../packages/maverick-core/maverick/assessment.py) engine
already turns a structured questionnaire into scored findings + a risk rating, and
new types are **added by appending to `TEMPLATES`, not by writing code**. Add the
finance set — each becomes a `run_assessment` capability for the agent that owns it:

| New template `type` | Owner agent | Framework | Sample questions (risk answer) |
|---|---|---|---|
| `sox_control` | SOX (5.1) | SOX §404 / COSO | "Is this control's operating effectiveness evidenced for the period?" (no→high); "Is there an SoD conflict in the responsible roles?" (yes→high). |
| `fraud_risk` | Fraud (5.4) | ACFE / SAS 99 | "Can one person both create and approve a vendor?" (yes→high); "Are vendor bank-detail changes reviewed?" (no→high). |
| `itgc` | SOX (5.1) | COBIT / SOX ITGC | "Is access to the posting tool least-privileged and logged?" (no→high) — *maps directly onto Lightwork's own capability + audit evidence.* |
| `credit_risk` | Credit (5.7) | CECL / internal | "Is the customer past terms > 90 days?" (yes→high). |
| `close_readiness` | GL/Close (1.1) | internal | "Are all balance-sheet accounts reconciled?" (no→high). |

The conversational **finance assessor** is then the existing
`build_assessment_agent` pattern with these templates — no new agent machinery.

---

## 8. Integrations catalog — what to connect, build order

Per CLAUDE.md rule 5, **every** connector below ships with a config knob, and per
rule 6 the **installer wizard** gets a toggle for it. Tools follow the existing
`verb_noun` convention and the read-only-by-default split (mutating tools land on
`deny_tools` / `require_human`).

| System class | Vendors | MCP server | Status | Used by |
|---|---|---|---|---|
| **Brokerage / market** | Interactive Brokers | `Interactive_Brokers_IBKR` | **✅ exists** | Investments (3.2), Forecasting |
| **Docs / email / calendar** | Google, Gmail | `Google_Drive`, `Gmail`, `Google_Calendar` | **✅ exists** | invoice/contract intake, close calendar |
| **ERP / GL** | NetSuite, SAP, Oracle, QuickBooks, Xero | `ERP_*` | ◻ build (P1) | Controllership (all of T1) |
| **Banking / payments** | Plaid, Modern Treasury, SWIFT, bank APIs | `Bank_*`, `Treasury_*` | ◻ build (P1) | Treasury, Cash, AP/AR |
| **Payroll / HCM** | Workday, ADP, Gusto, Rippling | `HCM_*` | ◻ build (P1) | Payroll (1.4) |
| **AP / spend** | Bill.com, Coupa, Ramp, Tipalti | `AP_*` | ◻ build (P2) | AP (1.2), Procurement (6.1) |
| **AR / billing** | Stripe, Chargebee, NetSuite | `Billing_*` | ◻ build (P2) | AR (1.3), Rev-rec (1.6) |
| **EPM / planning** | Anaplan, Adaptive, Pigment | `EPM_*` | ◻ build (P2) | FP&A, Forecasting |
| **Close / recon** | BlackLine, FloQast | `Close_*` | ◻ build (P2) | GL/Close (1.1) |
| **Tax** | Avalara, Vertex, ONESOURCE, Corptax | `Tax_*` | ◻ build (P3) | Tax tower (T4) |
| **GRC / SOX** | AuditBoard, Workiva | `GRC_*` | ◻ build (P3) | SOX, IA (T5) |
| **SEC / reporting** | Workiva, EDGAR | `SEC_*` | ◻ build (P3) | Reporting (T7) |
| **Sanctions / KYB** | OFAC SDN, Dow Jones, ComplyAdvantage | `Screening_*` | ◻ build (P1 — gates payments) | Vendor (6.2), AP, Treasury |
| **Cap table** | Carta, Pulley | `Equity_*` | ◻ build (P4) | Equity/SBC (7.3) |
| **Credit bureau** | D&B, Experian | `Credit_*` | ◻ build (P4) | Credit (5.7) |

**Knowledge sources** (uploaded docs, per-domain RAG, shield-scanned on ingest):
accounting policy manual, chart of accounts, **delegation-of-authority matrix**,
close calendar, debt schedule, IPS, T&E policy, rev-rec policy, RCM, tax positions,
legal-entity structure, prior filings.

---

## 9. Build sequence

Smallest safe loop first; controls before reach (the privacy/compliance order).

1. **Control substrate for money (do this first).**
   - Amount-aware authorization in `governance.py` (the §2.3 gap): `amount`/`currency`
     on tool calls, `require_human_above` / `deny_above` thresholds.
   - The **Finance Operating Profile** compiler (§3.8): profile → capability +
     policy + consent config, with **hard-floor** validation (§3.2) and the L0–L4
     automation tiers (§3.1).
   - **SoD conflict linter** over packs (§2.1).
   - `sanctions_screen` connector (gates every payment/vendor path).
   - Finance assessment templates (§7) — pure data, lands immediately.
2. **Tower 1 (Controllership) + the Finance Controller** on top of one ERP
   connector + banking read. GL/Close, AP, AR, Payroll, FA, Cost/Inventory,
   Reconciliation, Master-Data. Maker-checker queue live; profiles drive automation.
3. **Tower 3 (Treasury)** reusing the IBKR pattern; **Tower 2 (FP&A)** (low-risk,
   high-value, read-only — a fast win).
4. **Tower 5 (Risk/Controls)** — SOX/IA/Fraud/Anomaly reading the now-rich audit
   trail and ledgers. **Tower 4 (Tax)**.
5. **Tower 6 (Procurement)** + **Tower 7 (Reporting)** + **AML** (5.8); regime
   packs (§6) and the `finance status` posture report; **red-team** an attack
   crossing a sealed compartment (poisoned invoice → AP, prove payroll/treasury
   are immune).
6. **Wizard + dashboard** (rule 6): domain toggles, connector setup, the
   profile / automation-tier editor, and the live maker-checker / approvals surface.
7. **Vertical packs** (§4) per target market — SaaS metrics, project costing, fund
   accounting — on the same opt-in pack model, last.

---

## 10. Honest caveats

- **Lightwork supplies the controls and the evidence; it does not certify the
  books.** Agents *draft*; humans *post, pay, file, and certify*. No agent
  attests to ICFR, signs a §302 certification, or files with the SEC/IRS — those
  are human acts the suite supports and audit-trails. (Same liability line as the
  compliance domain's "control coverage, not legal advice.")
- **Accounting/tax judgment needs a CPA.** Rev-rec, tax positions, impairment,
  valuation allowances, and non-GAAP measures are judgmental; the agents cite the
  standard and flag the judgment for a qualified human, and mark anything they
  cannot tie to evidence **unverified** rather than guessing (the assessor's
  `unknown` discipline).
- **Connectors are the long pole, and each is a write-risk.** Every mutating
  finance API (post, pay, file) must land behind `require_human` *and* a deny-list
  *and* (where relevant) sanctions screening — defence in depth, because a single
  wrong call here mis-states the books.
- **SoD is only real if the packs are disjoint.** The whole model depends on no
  compartment holding two incompatible duties; the SoD linter (2.1) must gate CI,
  or the separation silently rots.
- **The amount-threshold gap is load-bearing.** Until §2.3 ships, "maker-checker"
  means *every* money movement pauses for a human (correct but heavy); the
  threshold tiers (§3.3) are what make it operable at scale.
- **Automation tiers are a loaded gun.** L3/L4 trade oversight for speed; the hard
  floors (§3.2) are the backstop, but a client that pushes tiers high inherits the
  residual risk. Default conservative (L1) and let a client ratchet up per action
  with evidence — never ship a high-automation default.
- **The generic roster is not industry-complete.** A bank needs regulatory-capital
  reporting, a construction firm needs project/WIP costing, a nonprofit needs fund
  accounting. Enable the right **vertical pack** (§4) rather than stretching a
  generic agent past what it was scoped and tested for.
