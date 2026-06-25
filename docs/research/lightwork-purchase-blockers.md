# Lightwork — Exhaustive Purchase-Blocker Audit

> **Question:** What would prevent someone from buying Lightwork?
> **Scope:** the whole funnel — *find sales → clear security/legal/procurement → sign → pay → onboard*.
> **Method:** 8 parallel audits across the marketing site, pricing/packaging docs,
> commercialization research, enterprise legal/compliance surface, billing/licensing
> code, engineering-readiness code, deployment/onboarding, and branding. Each finding
> is cited to `file:line`. Code claims were spot-verified against source.
> **Lightwork** = the commercial name for the **Maverick** codebase, by **Daybreak Labs**.

## How to read this

Severity reflects impact on *closing a sale*, not code quality:

- **Critical** — a hard stop: the deal cannot close (or money cannot change hands) until fixed.
- **High** — fails a standard security/procurement review or seriously deters a buyer.
- **Medium** — adds friction, confusion, or risk a buyer will raise.
- **Low** — polish; noticed by careful buyers.

Many issues were independently surfaced by multiple audits; they are merged here and
cited to the strongest evidence.

---

## A. Path to purchase — can a buyer even buy?

1. **The demo/“request access” form sends nothing.** `pitch/site/app.js:8` — `var ACCESS_KEY = "";`.
   Every "Book a demo" / "Request access" CTA on every page falls back to a `mailto:` link
   because the Web3Forms key was never set. The entire inbound lead-capture funnel is inert. **Critical.**
2. **No published pricing anywhere a buyer can self-serve.** No pricing on `pitch/site/index.html`,
   `product.html`, `second-shift.html`, `fleet-governance.html`, `daybreak-forge.html`; all CTAs are
   "contact us." Buyers who pre-qualify on budget cannot, and move on. **High.**
3. **No Terms of Service / MSA / EULA on the site or in the repo.** Footer links only `privacy.html`;
   no `docs/enterprise/legal/` MSA exists. Procurement cannot start contract review. **Critical.**
4. **No published Data Processing Agreement (DPA) on the buying surface.** Only a privacy page;
   GDPR/CCPA buyers need a DPA before evaluation. **Critical.**
5. **No public security whitepaper / Trust Center — everything is "available on request."**
   `pitch/site/security.html:47,164`, `index.html:249`. Security reviews can't begin without outreach;
   "no page = filtered in triage" (`docs/research/commercialization/07-trust-certifications-roadmap.md:40`). **High.**
6. **Unfilled `[FILL: …]` placeholders on public/buyer-facing pages.** e.g. `pitch/MANIFESTO.html:276`
   `[ FILL: contact ]`; `pitch/ONE-PAGER.md:5,76,79,81`; `pitch/SEED-DECK.md` and all `pitch/AUDIENCE-*.md`
   ship template fill-ins (deal terms, customer name, traction, raise amount). Signals "not ready." **High.**
7. **"Private alpha" stamped in every site footer** (`index.html`, `product.html`, `company.html`,
   `security.html`, `privacy.html`, and all product pages). "Alpha" auto-fails enterprise procurement
   committees. **High.**
8. **No customer references, logos, case studies, or ROI proof** anywhere on the site. No social proof
   for a trust-gated buyer. **High.**
9. **Founder bios flagged as a pre-launch TODO.** `pitch/site/README.md` lists "replace the founder-bio
   placeholder in company.html." Co-founder lineup is also inconsistent: `company.html:71-82` shows two
   co-founders while `ONE-PAGER.md` lists one. **Medium.**
10. **Privacy claim vs. analytics mismatch.** `privacy.html` says "no cookies," but a Cloudflare beacon
    token is hardcoded in `index.html:18`. Savvy buyers notice. **Low.**

---

## B. Pricing & packaging coherence

11. **Pricing is explicitly "directional … not validated."** `docs/product-portfolio.md:6-9` and
    `pitch/PRODUCT-LINE.md:4-5`: "Re-confirm against design partners before any external use." Every
    number ($18K–$500K+) is a self-flagged hypothesis. **Critical.**
12. **Three competing tier/edition naming systems.** Platform tiers are **Basic/Gold/Platinum**
    (`docs/product-portfolio.md:13`); the commercialization doc uses **Community/Team/Enterprise**
    (`02-packaging-pricing-editions.md:135-137`); `docs/enterprise/editions.md:6` ships only
    **Community(planned)/Enterprise**; the code uses **free/pro/enterprise** (`billing.py:159-167`).
    A buyer cannot tell what they are buying. **Critical.**
13. **Cross-document price contradiction on the entry enterprise tier.** Platinum floor is "$200K"
    (`product-portfolio.md:77`, `PRODUCT-LINE.md:65`) vs Enterprise floor "$120K"
    (`02-packaging-pricing-editions.md:137`). An $80K swing depending on which doc sales reads. **Critical.**
14. **Code plan features don't map to the marketing capability matrix.** `billing.py:159-167` defines
    free/pro/enterprise feature sets that don't correspond to the Basic/Gold/Platinum capability table.
    Sales promises and code entitlements diverge. **Medium.**
15. **Outcome-based pricing is undefined.** "Per completed unit / DSAR / return / ticket"
    (`product-portfolio.md:205`) with no rate ever published. Cannot be quoted or forecast. **High.**
16. **Tax pack has two incompatible models** ("$60K/yr each" *and* "per-return or per-seat"),
    neither priced (`product-portfolio.md:202`). CPA-firm buyer cannot price it. **High.**
17. **Fleet Governance pricing ambiguous** — "$75K standalone, or included at Platinum"
    (`product-portfolio.md:218`): does Platinum's $200K already include it, or is it additive? **High.**
18. **Corporate-function bundle math doesn't add up** — "$25K each … bundle 13 for ~$150K"
    but 13×$25K = $325K and "$300K+ à la carte" (`product-portfolio.md:203`). No stated discount. **Medium.**
19. **Annual-only; no monthly/pilot pricing** even though the research says an annual-commit option is
    strategically required (`02-packaging-pricing-editions.md:120-122`). Blocks short paid pilots. **Medium.**
20. **Platinum range is a 2.5× spread ($200K→$500K+)** with no stated drivers; effectively
    "call for a quote" (`product-portfolio.md:77`). **Medium.**
21. **Pricing model states only what *not* to meter** ("don't meter the audit log, don't charge
    per-agent," `product-portfolio.md:288-290`) without stating what *is* metered. Opaque. **High.**

---

## C. Commercial entity, IP & positioning

22. **No commercial entity (C-corp).** `11-execution-plan.md:39` — needed to sign LOIs/contracts/certs;
    a buyer cannot contract with an individual. **Critical.**
23. **Trademark on "Lightwork" is unregistered/unguarded.** `11-execution-plan.md:39`,
    `01-licensing-and-relicensing.md:32-35` — "without the mark you have no enforceable lever over a fork."
    Certs attach to a name. **High.**
24. **MIT license is irrevocable for shipped versions.** `01-licensing-and-relicensing.md:12-21` — anyone
    can `pip download maverick-agent==0.1.6` and fork forever; relicensing only governs future commits. **Medium.**
25. **Current public positioning repels the target buyer.** "No paid tier, no telemetry, MIT, building a
    founder brand" (`06-gtm-icp-and-sales-motion.md:139-151`): "no paid tier" signals "no company to stand
    behind it"; "no telemetry" is incoherent for a governance product. **High.**
26. **The "trust paradox."** An AI-agent company selling AI-agent governance is "the single biggest
    objection" (`06-gtm-icp-and-sales-motion.md:152-157`). **High.**
27. **The "~70% compliant" claim is self-described as dishonest.** `04-regulated-deployment-eng-gaps.md:32-33`
    — realistic enterprise readiness is "~15-20%, not 70%"; repeating it in a security review is "credibility
    death." **Critical.**
28. **Solo, non-domain founder + largely AI-written codebase selling trust software** is a credibility
    mismatch a security review will probe (`10-financial-model-and-fundraising.md:76`). **High.**
29. **AI-generated-code provenance / copyleft-contamination risk.** `01-licensing-and-relicensing.md:114-119`
    — IP-scan question; the inbound=outbound MIT CLA must be replaced before reopening contributions. **Medium.**
30. **No tech E&O / professional-liability insurance** for a compliance-content product
    (`08-regulatory-content-moat.md:128-131`): one failed audit can exceed any survivable liability cap. **High.**
31. **Regulatory-content moat has a licensing landmine** — the SCF corpus is CC BY-ND and "explicitly
    prohibits using AI to generate derivative content" (`08-regulatory-content-moat.md:44-52`), undercutting
    the "agents maintain the framework library" thesis. **High.**

---

## D. Trust, certifications & compliance artifacts

32. **No SOC 2 (Type I or II).** "Not started — readiness phase" (`docs/compliance/README.md:94`);
    "in progress" (`enterprise/security-overview.md:83`); `maverick soc2` is self-assessment tooling, not an
    attestation. The Type II observation window is calendar-bound and not started. **Critical.**
33. **No third-party penetration test.** "In progress" (`enterprise/diligence.md:66`); scheduling it is an
    *open* action item (`2026-06-24-management-review.md` A-3). **Critical.**
34. **No ISO 27001 / ISO 42001 certification.** "Not started — readiness phase"
    (`docs/compliance/README.md:94`); docs approved, audit not begun. **High.**
35. **No HIPAA BAA.** Listed as future work (`enterprise/single-client-deployment.md:120`); a hard gate
    for any PHI/healthcare deal. **Critical (healthcare).**
36. **No FedRAMP path / no FIPS-validated crypto.** `04-regulated-deployment-eng-gaps.md:51` — no FIPS
    mode; blocks gov/classified. (FedRAMP is correctly deferred, but its absence still gates gov buyers.) **High (gov).**
37. **No completed security questionnaire kit (SIG-Lite / CAIQ).** Planned, not done
    (`07-trust-certifications-roadmap.md:4`). Every deal re-answers from scratch. **High.**
38. **No Trust Center published.** "Soft-blocks — no page = filtered in triage"
    (`07-trust-certifications-roadmap.md:40`). **High.**
39. **Internal audit is self-conducted by the sole owner — no independence.** `2026-Q2-internal-audit-report.md`
    raises 3 nonconformities; the author is also the organization. **High.**
40. **Four compliance action items still OPEN** (`2026-06-24-management-review.md:75-81`): apply
    compliant config, schedule pen test, configure human-oversight gates, engage a SOC 2 assessor. **High.**
41. **No data-residency / region-pinning** (`04-regulated-deployment-eng-gaps.md:50`). Blocks EU/APAC
    residency requirements. **Medium.**
42. **Vulnerability-disclosure program has no track record** (`SECURITY.md:91`, "none yet"). No researcher
    trust history. **Low.**

---

## E. Legal contracts (all are unsigned templates)

43. **DPA is a bracketed template, "not legal advice."** `enterprise/legal/dpa-template.md:1-2,7,31` — even
    references "`<Add SOC 2 / ISO status when available>`," i.e. it can't be finalized until certs exist. **Critical.**
44. **SLA is a template with every target blank.** `enterprise/legal/sla-template.md:10,13,18-21` — uptime
    `<99.9%>`, response `<1h>`, credits all unfilled. No binding uptime/support commitment. **Critical.**
45. **Sub-processor list is an empty template** (`enterprise/legal/subprocessors.md:1-14`) — GDPR Art. 28
    disclosure not satisfiable. **Critical.**
46. **All legal docs marked "starting points, not legal advice — have counsel review."**
    `enterprise/legal/README.md:1`. Buyer must fund both sides' counsel to even get a signable set. **Critical.**

---

## F. Security posture & engineering readiness (the security-review failers)

> Cross-cutting note: the codebase has a newer `secure_by_default()` layer
> (`security_defaults.py:31-36`) that flips several controls **ON unless explicitly disabled**, but the
> compliance docs, several module docstrings, and the June-2026 internal audit still describe them as
> **off by default** — see #47. Treat the posture as *inconsistent and unproven*, which is itself a
> review finding.

47. **The security-default state is internally contradictory.** `crypto_at_rest.at_rest_enabled()` docstring
    says "Off by default" yet the code returns `secure_by_default()` = ON (`crypto_at_rest.py:88-124`); same
    for audit signing (`audit/writer.py:117-142`). Meanwhile `docs/compliance/soc2-controls.md:210,235` and the
    Q2 internal audit report these as `disabled`. A buyer cannot get a straight, provable answer. **High.**
48. **Default `local` sandbox runs model-generated shell on the host.** `SECURITY.md:106-114`;
    `enterprise/deployment-playbook.md:159` ("**blocker** if wrong"). One prompt-injection = host RCE unless the
    operator switches to a container backend. **Critical.**
49. **Agent Shield is optional and fails open.** `SECURITY.md:113-114`; held-out detection ~48%
    (`docs/security/shield-benchmark.md:53`). The primary injection defense isn't guaranteed to be present. **Critical.**
50. **Residual risk R-01 (sandbox escape) is mitigated only by a not-yet-scheduled pen test.**
    `docs/compliance/risk-register.md` R-01; `2026-06-24-management-review.md:56`. Acknowledged high risk,
    no code fix. **Critical.**
51. **Multi-tenant isolation is opt-in and broken at the call site even when enabled.** Default single shared
    `DEFAULT_DB` (`maverick_dashboard/_shared.py:77-118`, `world_model.py:32`); per-user tenancy is off by default
    (`paths.py:139-157`); the research teardown documents a latent **cross-tenant data leak**
    (`00-synthesis.md:25-28`, `04-regulated-deployment-eng-gaps.md:46`). Reportable breach the moment two
    customers share a host. **Critical.**
52. **No SSO/OIDC by default; dashboard auth fails open.** `require_principal()` returns `None` when OIDC is
    off and `has_permission()` then returns `True` (`maverick_dashboard/auth.py:222-226,285-394`); a missing
    `MAVERICK_DASHBOARD_TOKEN` means no auth at all. First line of any questionnaire. **Critical.**
53. **No resource-level RBAC — only tool-level ACL + coarse roles.** `safety/tool_acl.py`, `capability.py`;
    cannot express "user X may read goal/row/audit-day Y" (`04-regulated-deployment-eng-gaps.md:53`). **High.**
54. **No real secrets vault.** Provider keys and channel tokens read from raw env
    (`providers/anthropic_provider.py`, `server.py:313-427`); `secrets.py` is a log scrubber, not a vault. **High.**
55. **Audit signing silently degrades to unsigned** if the `cryptography` extra is missing
    (`audit/writer.py:277-303`) — operator believes it's on; auditor finds no signatures. **High.**
56. **No SIEM export / WORM / immutable external sink.** `04-regulated-deployment-eng-gaps.md:49` — no Splunk/
    Sentinel/S3-Object-Lock shipper. Auditors require an uneditable feed. **High.**
57. **Per-tenant encryption is off by default.** `crypto_at_rest.per_tenant_at_rest()` defaults off
    (`crypto_at_rest.py:129-151`); multi-tenant data shares one key unless explicitly enabled. **Medium.**
58. **OIDC sessions/bearer tokens cannot be revoked server-side** (12h cookie TTL)
    (`maverick_dashboard/oidc_login.py`, `auth.py:376-394`). Suspended users stay valid until expiry. **Medium.**
59. **Reverse-proxy auth trusts a forwarded header from any loopback client** (`auth.py:70-85`) — local-user
    impersonation on a shared host. **Medium.**
60. **SCIM bearer token is static, env-only, no rotation/revocation** (`maverick_dashboard/scim.py:43-71`). **Medium.**
61. **SQLite world model is single-writer (one process-wide `RLock`)**; the Postgres backend is a prototype
    with **no `tenant_id` column and no migration framework** (`09-saas-architecture-readiness.md:42-62`).
    Can't scale or safely schema-migrate a multi-tenant SaaS. **High.**
62. **Goals run as threads in the API process — no per-tenant isolation/quota** (one GIL, one FS)
    (`09-saas-architecture-readiness.md:63-72`). One tenant degrades all. **High.**
63. **Control plane and data plane are the same FastAPI process** (`09-saas-architecture-readiness.md:122-155`).
    A hosted SaaS needs a 6–9-month re-platform (`00-synthesis.md:85`). **High.**
64. **Architectural collision: kernel "fail-open, never require the shield" vs. a compliance product that must
    fail *closed* and prove it.** No policy-decision-point / hard-enforcement mode exists today
    (`00-synthesis.md:109-115`). Unresolved design gate. **High.**
65. **Floor to a credible regulated POC is ~30–40 person-weeks** (SSO + at-rest + real tenancy + WORM/SIEM)
    *before* any cert clock starts (`04-regulated-deployment-eng-gaps.md:113`). **Critical (timeline).**
66. **Firecracker silently falls back to Docker** if the VM layer is unavailable
    (`enterprise/deployment-playbook.md:323`) — isolation can degrade without warning. **Medium.**
67. **Granted plugins run in-process with no syscall/network sandbox**; the permissions manifest is advisory
    (`enterprise/deployment-playbook.md:322`, `docs/security/audit-readiness.md:160`). Plugin compromise =
    host compromise. **High.**
68. **Config is not schema-validated** — a typo like `max_dollarss` is silently ignored and the run goes
    **uncapped** (`docs/configuration.md:223-226`). **Medium.**

---

## G. Billing, licensing & entitlement — can't take money or enforce a plan

69. **No payment processor integration / cannot collect money.** The Stripe tool is read-only (no charge/
    invoice/subscription create) (`tools/stripe_tool.py:32-50`); invoices are frozen dataclasses printed to
    stdout (`billing.py:73-146`, `cli/__init__.py:2323-2374`). "Buying" cannot be completed in-product. **Critical.**
70. **No license key / activation / proof-of-payment anywhere.** `maverick tenant create --plan enterprise`
    grants every premium feature instantly with no payment check (`tenant/registry.py:150-171`). **Critical.**
71. **Entitlement gate fails OPEN.** `feature_allowed()` returns `True` for no-tenant, unknown-tenant, and on
    *any* exception ("never block on billing") (`billing.py:203-229`). A non-paying user reliably gets paid
    features; a guessed/typo'd tenant ID is admitted. **Critical.**
72. **Plan definitions are config-overridable with no signature/approval/audit** (`billing.py:171-187`). An
    operator (or anyone with config access) can redefine what "free" includes. **High.**
73. **No subscription creation/renewal automation** — a provisioned "pro" tenant has no payment method or
    recurring billing unless an operator adds them in Stripe by hand (`tools/stripe_tool.py`). **Critical.**
74. **Tenant quota is a soft warning, not a block.** Over-cap returns "⚠ … at its spend cap" but lets the
    request proceed; no auto-suspend (`tenant/registry.py:272-291`, `server.py`). **High.**
75. **Per-principal quota enforcement is off by default** (`quotas.py:232-270`) — paying customers are
    unthrottled unless `MAVERICK_QUOTA_ENFORCE=1`. **High.**
76. **Concurrency limits fail open on lookup error** — a 5-goal cap becomes unlimited if config load throws
    (`tenant/concurrency.py:26-56`). **High.**
77. **Spend reads and usage recording fail soft to $0 / no-op** on ledger error
    (`tenant/registry.py:250-269`, `quotas.py:272-287`) — a tenant truly at the cap appears unused; spend can
    go unbilled. **Medium.**
78. **Three uncoordinated spend ceilings** (per-run `Budget`, per-principal `quotas`, per-tenant
    `max_daily_dollars`) that don't talk to each other (`budget.py` vs `quotas.py` vs `registry.py`), so a
    tenant cap can be exceeded by parallel runs. **Medium.**
79. **Plan name is a free-form string, no enum validation** — `plan="enterpise"` silently downgrades to free
    (`tenant/registry.py:150-171,199-200`; `billing.py:171-188`). Operator thinks they sold "pro." **Medium.**
80. **No audit trail for plan/quota changes** (`tenant/registry.py:195-200`) — a Python-API caller can
    self-upgrade to enterprise with no record. **Medium.**
81. **`Entitlements.max_daily_dollars` is defined but never enforced** — only the registry's per-tenant cap is
    checked (`billing.py:151-157` vs `registry.py:272-291`). A plan-level cap set in config has no effect. **Medium.**
82. **Stripe refunds gated only by an env var, no approval workflow** — `MAVERICK_STRIPE_ENABLE_REFUNDS=true`
    lets any agent/user with tool access refund any charge (`tools/stripe_tool.py:225-260`). **Medium.**
83. **Invoices have no idempotency** — running the CLI twice double-bills the same usage
    (`billing.py:106-146`). Deleted tenants can still be invoiced (`tenant/registry.py:203-221`). **Medium.**

---

## H. Product GA, deployment, onboarding, support & ops

84. **Not GA.** README/`pyproject.toml` mark "Alpha" / "Development Status :: 3 - Alpha"; the only edition
    available now is full Enterprise, and **Community is "planned/future"** (`enterprise/editions.md:6-8`).
    No cheap on-ramp / eval tier. **Critical.**
85. **No hosted / managed / SaaS offering — self-host only** (`docs/deployment.md`; the "we host" column in
    `enterprise/deployment-playbook.md` is not a documented product). Buyer owns all ops. **Critical.**
86. **No real support organization or binding SLA** — only the blank SLA template and "contact us"
    (`enterprise/editions.md:19`, `sla-template.md`). **Critical.**
87. **Single-maintainer / bus-factor risk.** `MAINTAINERS.md` ("BDFL — final call"), LICENSE copyright one
    individual. Enterprises require vendor-viability assurance. **High.**
88. **Day-one requires an LLM provider API key + billing** (wizard pings Anthropic before save;
    `cli/__init__.py:75-99`). No free/local default path to evaluate. **High.**
89. **Several channels are scaffolds, not production** (WhatsApp/SMS/iMessage need Twilio + public webhooks;
    the wizard code itself calls offering them by default "dishonest") — `apps/installer-cli/.../wizard.py:70-77`,
    `docs/deployment.md:132`. **High.**
90. **Inbound webhooks fail closed with no secret** — forget `MAVERICK_WEBHOOK_SECRET` and all channel
    connectivity 401s (`SECURITY.md:150`). Silent day-one breakage. **High.**
91. **Unsigned installers** ("unknown developer" prompt; signing "still coming") — `README.md:65-66`.
    Blocks controlled enterprise rollout. **High.**
92. **`curl | sudo bash` VPS install pulls the mutable `main` branch by default**
    (`deploy/vps/install.sh:83-88`). Supply-chain risk; README one-liner doesn't pin a tag. **High.**
93. **No documented upgrade/migration runbook** (forward-only migrations are mentioned, no procedure)
    (`docs/operations.md`, `enterprise/deployment-playbook.md:278`). **Medium.**
94. **Backup/DR is manual for SQLite** (WAL torn-copy risk; stop-writers-to-restore; no HA replica/PITR)
    (`docs/operations.md:91-114`). RPO/RTO undefined. **Medium.**
95. **Postgres RLS is a sequenced, fail-closed migration with sharp edges** — pre-tenancy `NULL` rows become
    invisible *and* frozen; enabling it on live data can silently freeze legacy data (`docs/multi-tenancy.md:125-150`). **Medium.**
96. **Data retention is manual, not enforced** — conversations/events accumulate forever unless the operator
    schedules `maverick gc`; not GDPR-compliant by default (`docs/operations.md:177-212`). **Medium.**
97. **No native Terraform/Ansible modules; observability requires DIY Prometheus wiring**
    (`enterprise/deployment-playbook.md`, `docs/operations.md:245-263`). **Low.**

---

## I. Branding / rename completeness (customer-facing)

98. **Mismatched product vs. install name.** Sold as "Lightwork," but the buyer installs `maverick-agent`
    and runs `maverick init` → "**Maverick** installer" (`apps/installer-cli/.../wizard.py:502-521`;
    `README.md:28,68`). The PyPI description never mentions Lightwork
    (`packages/maverick-core/pyproject.toml:12`). **High.**
99. **Desktop (Tauri) app ships as "Maverick."** `apps/installer-desktop/src-tauri/tauri.conf.json:3,15,37-38`
    — `productName`/window title/bundle metadata all say Maverick; OS installer shows a generic "AI agent
    installer." **High.**
100. **Mixed GitHub URLs** — `Day-AI-Labs/Lightwork` vs `Day-AI-Labs/maverick` across README contact/release/
     clone links (`README.md:25,58,218`). One path may not resolve. **High.**
101. **MCP server identity is `maverick`** (`packages/maverick-mcp/maverick_mcp/server.py:59`) — appears as
     "maverick" inside a customer's Claude Desktop / MCP client, not "Lightwork." **Medium.**
102. **Dashboard branding is only partial** — footer says "Lightwork by Daybreak Labs" but page/tab titles are
     bare "Lightwork"; `test_branding.py` encodes the mixed state. **Medium.**
103. **"Daybreak Labs" itself is a placeholder company name** in the portfolio naming worksheet
     (`docs/product-portfolio.md:266`), unresolved. **Medium.**

---

## J. Market, competition & timing (deal-context risk)

104. **The core "agent governance" wedge is being commoditized** — Microsoft Entra Agent ID (GA), Agent 365,
     an open-sourced Agent Governance Toolkit, and Okta for AI Agents (GA ~Apr 2026) ship "register + scope +
     audit my agents" for free/near-free (`00-synthesis.md:14-20`, `03-competitive-teardown.md:11-15`). **Critical.**
105. **AI-governance budget may be 12–30 months out** — Credo/Holistic stalled at ~$100M valuations with tiny
     ARR; a seed can starve first (`10-financial-model-and-fundraising.md:73`, `00-synthesis.md:126`). **Critical.**
106. **The whole pivot is gated on an unmet validation bar: ≥5 paid design-partner LOIs (~$30–40K) in 8 weeks**
     — under 5 ⇒ "do not pivot the company" (`00-synthesis.md:39-41`, `10-…:79-83`). Willingness-to-pay is
     unproven. **Critical.**
107. **Heavier incumbents own the aggregator framing** — ServiceNow AI Control Tower, OneTrust (~$500M ARR,
     14k customers) (`03-competitive-teardown.md:19,23-24`). Rip-and-replace loses. **High.**
108. **Capital trap: ~$1M+/yr of certs + enterprise AEs *before* meaningful ARR**
     (`10-financial-model-and-fundraising.md:77`). **High.**
109. **Self-assessed odds: ~15–20% to $10M ARR, <5% venture-scale**
     (`10-financial-model-and-fundraising.md:10,81-82`). **Medium (context).**
110. **EU AI Act agentic-obligation timing can slip**, softening the "compliance forces purchase" urgency
     (`10-financial-model-and-fundraising.md:74`). **Medium.**

---

## Bottom line

- **To complete a purchase *today*, three things are hard stops in this repo:** the demo form sends
  nothing (#1), there is no way to take money or enforce a paid plan (#69–#73, entitlement fails open #71),
  and the product a buyer installs isn't even named what they bought (#98–#100).
- **To clear enterprise procurement, the blockers are systemic:** no SOC 2 / pen test / ISO (#32–#34),
  unsigned legal templates (#43–#46), default host-RCE sandbox + fail-open shield (#48–#49), an opt-in/
  contradictory security posture (#47, #51–#52), and a ~30–40 person-week engineering floor *before* the
  6–18-month cert clock even starts (#65).
- **The company's own research is candid** that the wedge is being commoditized (#104), the budget may be
  years out (#105), and the pivot shouldn't proceed without ≥5 paid LOIs first (#106).

*Severity counts: Critical ≈ 25, High ≈ 40, Medium ≈ 35, Low ≈ 5 (110 distinct issues; near-duplicates merged).*
