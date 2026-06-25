# Lightwork — Purchase-Blocker Audit & Resolution Log

> **Question:** What would prevent someone from buying Lightwork?
> **Method:** 8 parallel audits across the marketing site, pricing/packaging docs,
> commercialization research, enterprise legal/compliance surface, billing/licensing
> code, engineering-readiness code, deployment/onboarding, and branding.
> **Lightwork** = the commercial name for the **Maverick** codebase, by **Daybreak Labs**.
>
> This document is now a **living resolution log**. Each issue carries a status:
>
> - ✅ **Fixed** — a code/doc change has landed (PR noted).
> - ◐ **Addressed / by-design** — resolved via documentation or a mechanism; any
>   residual is an explicit operator/founder step.
> - 🔧 **Engineering backlog** — a real, often substantial, code effort; not done.
> - 👤 **Owner: business / legal / founder** — not a code change (a cert, a
>   contract, a pricing decision, a market bet). Tracked here, owned off-repo.

## Resolution summary

**Fixed this pass (PRs #1798, #1799):** branding (#98–#100, #102), security-default
doc contradiction (#47), pricing/naming canonicalization (#12–#14), config-lint
false-positive + stale doc (#68), plan-name typo guard (#79), invoice idempotency
(#83), website demo-form injection + placeholder (#1, #6), billing-model doc
(#69/#73), VPS installer release-pinning (#92).

**By-design, now documented:** payment/collection model (#69/#70/#73), Stripe tool
read-mostly (#82), self-host-only (#85), quotas/entitlement permissive defaults
(#71/#72/#75/#77), MCP slug + package names (#101).

**Engineering backlog (substantial — the audit's own ~30–40 person-week estimate):**
multi-tenant isolation, SSO/OIDC-by-default, resource RBAC, secrets vault, SIEM
export, control/data-plane split, Postgres+RLS hardening (#48, #51–#65), plus
smaller items (#41, #55, #66, #76, #78, #80, #81, #90, #94).

**Owner: business / legal / founder (not code):** certifications (#32–#40), legal
contracts (#3–#5, #43–#46, #86), pricing decisions (#7, #11, #15–#21), entity /
trademark / insurance / positioning (#22–#31), GA status & signing & maintainer
(#2, #84, #87, #91), market/timing bets (#104–#110).

---

## A. Path to purchase

1. ✅◐ **Demo form delivery** — `pitch/site/app.js` now resolves the Web3Forms key
   at deploy time (`<meta name="web3forms-access-key">` or `window.LIGHTWORK_ACCESS_KEY`),
   no source edit, mailto fallback kept (#1799). *Residual (operator):* provide the key.
2. 👤 **"Private alpha" in footers** — honest product-stage label; drop at GA. (founder)
3. 👤 **No Terms of Service / MSA** — needs counsel-drafted terms. (legal)
4. 👤 **No published DPA on the site** — a fill-in template exists in `docs/enterprise/legal/`; publishing a signed one is a legal step. (legal)
5. 👤 **No public security whitepaper / Trust Center** — (business)
6. ✅ **`[FILL: contact]` in `MANIFESTO.html`** — filled with the established contact (#1799).
7. 👤 **Pricing not published** — a deliberate "contact sales" choice for a high-ACV B2B sale. (founder)
8. 👤 **No customer references / case studies** — (business)
9. 👤 **Founder-bio placeholder in `company.html`** — founder content. (founder)
10. 👤 **Privacy "no cookies" vs Cloudflare beacon** — minor copy reconciliation. (founder)

## B. Pricing & packaging

11. 👤 **Pricing is "directional, not validated"** — needs design-partner validation. (founder)
12. ✅ **Three competing tier-naming systems** — `product-portfolio.md` now carries a "Canonical naming, editions & SKU map" tying edition / pricing-tier / billing-plan-key together (#1798).
13. ✅ **$120K vs $200K floor contradiction** — research teardown marked superseded; canonical floor stated once (#1798).
14. ✅ **Code plan keys vs marketing tiers** — `billing.py` comment + canonical map clarify these are entitlement IDs, not sales tiers (#1798).
15–21. 👤 **Outcome pricing, tax-pack model, fleet pricing, bundle math, annual-only, Platinum spread, metering rules** — all pricing-design decisions. (founder)

## C. Commercial entity, IP & positioning

22. 👤 **No C-corp** — needed to sign LOIs/contracts. (business)
23. 👤 **Trademark on "Lightwork" unregistered** — `TRADEMARK.md` exists in-repo; registration is a legal step. (legal)
24. 👤 **MIT irrevocable for shipped versions** — relicensing strategy. (legal)
25–28. 👤 **Positioning, trust paradox, founder credibility** — GTM messaging. (founder)
27. 👤 **"~70% compliant" claim** — lives only in the internal research doc, not customer-facing material; keep it out of buyer messaging. (founder)
29. 👤 **AI-code provenance / CLA** — IP-scan + CONTRIBUTING update. (legal)
30. 👤 **No tech E&O insurance** — (business)
31. 👤 **SCF content-license landmine** — regulatory-content strategy. (legal/strategy)

## D. Trust, certifications & compliance artifacts

32. 👤 **No SOC 2 (Type I/II)** — calendar-bound; `maverick soc2` self-assessment exists, attestation is an auditor engagement. (business)
33. 👤 **No third-party pen test** — open action item in the compliance evidence. (business)
34. 👤 **No ISO 27001 / 42001 cert** — docs approved; audit not begun. (business)
35. 👤 **No HIPAA BAA** — counsel-drafted, per-deal. (legal)
36. 👤/🔧 **No FedRAMP path; no FIPS crypto** — FedRAMP correctly deferred (business); FIPS mode is eng backlog.
37–40. 👤 **SIG/CAIQ kit, Trust Center, audit independence, open action items** — (business)
41. 🔧 **No data-residency / region-pinning** — engineering backlog.
42. 👤 **Vuln-disclosure program has no track record** — time + reports. (business)

## E. Legal contracts

43–46. 👤 **DPA / SLA / sub-processor list / MSA are unsigned templates** (`docs/enterprise/legal/`) — intentionally counsel-completed per deal; not fabricated here. (legal)

## F. Security posture & engineering readiness

47. ✅ **Contradictory security-default docs** — reconciled to the actual `secure_by_default()` behavior (at-rest encryption + audit signing default ON), verified via `collect_soc2_evidence` (#1798). *Post-merge review:* also fixed two stale "opt-in" rows in the `soc2-controls.md` control matrix that the prose pass had missed.
48. 🔧◐ **Default `local` sandbox runs host shell** — honest in `SECURITY.md`; the wizard already defaults real installs to a container when available, and enterprise mode upgrades `local`→container and fails closed. Making it fail-closed everywhere is a kernel-philosophy change (eng/decision).
49. ◐ **Agent Shield optional / fails open** — kernel rule 1 (fail-open by design); documented as a floor, not a guarantee.
50. 👤 **Residual risk R-01 (sandbox escape) → pen test** — schedule the pen test. (business)
51–65. 🔧 **Multi-tenant isolation, SSO/OIDC-by-default, resource RBAC, secrets vault, SIEM export, single-writer/PG-prototype, thread isolation, control/data-plane split, fail-closed enforcement mode** — the substantial regulated-SaaS engineering track (the audit's ~30–40 pw floor). Not addressed here; tracked as the core eng backlog. OIDC/encryption/signing *do* exist as opt-in/секure-default; the gap is "enforced multi-tenant by default."
55. 🔧 **Audit signing silently degrades to unsigned if `cryptography` missing** — small: make it warn loudly / refuse under a compliance floor.
66. 🔧 **Firecracker silently falls back to Docker** — small: alert on fallback.
67. ◐ **Plugins run in-process** — load-time allowlist by design; syscall sandbox is eng backlog.
68. ✅ **"Config not schema-validated"** — `config-lint` already existed (`maverick config-lint` + startup warning); fixed the `[budget] self_tuning` false-positive and the stale `configuration.md` claim (#1799). *Post-merge review:* `configuration.md` had claimed config-lint also runs inside `maverick doctor`, which it did not — now wired in (advisory `config-lint` rows), so the claim is true and `doctor` catches budget typos.

## G. Billing, licensing & entitlement

69/73. ◐ **No payment processor / no subscription automation** — by design for contract-sold tiers; `docs/billing.md` documents the meter→idempotent-invoice→AR model (#1799).
70/72. ◐ **No license key; plans config-overridable** — entitlement plans gate features per tenant; collection is contract/AR. By design, documented.
71. ◐🔧 **Entitlement fails open** — deliberately permissive so single-tenant/self-host is never gated; a strict multi-tenant enforcement mode remains an optional eng add.
74/75/76/77/78/81. 🔧 **Quota soft-warn, off-by-default, concurrency fail-open, fail-soft reads, uncoordinated ceilings, plan-level cap unenforced** — small eng items; several are intentional single-tenant defaults.
80. ✅ **No audit trail for plan/quota changes** — `set_plan`/`set_quota` now emit a tamper-evident audit row (`tenant_plan_changed` / `tenant_quota_changed`, with old→new values), covering the dashboard control-plane API and the CLI, so an upgrade or cap change is provable, not a silent edit (#1799).
79. ✅ **Plan-name typo silently downgraded to `free`** — `billing.known_plan_names()` + registry/CLI warnings (#1799).
82. ◐ **Stripe refunds env-gated** — reasonable guardrail; agents never create charges (by design).
83. ✅ **Invoice double-bill risk** — deterministic `invoice_id` idempotency key (#1799). *Post-merge review:* open-ended invoices (no `--since/--until`) now get an **empty** id rather than a stable-but-unsafe key over a growing total, so a deduping processor can't under-bill; CLI + `billing.md` updated.

## H. Product GA, deployment, support & ops

84. 👤 **Not GA (alpha)** — honest stage label. (founder)
85. ◐ **Self-host only / no managed SaaS** — the intended model (regulated buyers self-host); hosted SaaS is the eng track in §F.
86. 👤 **No binding SLA** — template needs counsel + an ops commitment. (legal/business)
87. 👤 **Single-maintainer / bus-factor** — hiring. (business)
88. ◐ **Day-one requires an LLM provider key** — local-model (Ollama/vLLM) paths exist; a zero-key default-eval flow is an optional eng add.
89. 🔧/👤 **Some channels are scaffolds** — the wizard already excludes them from the default checkbox; honest.
90. ✅ **Inbound webhooks 401 with no secret** — correct fail-closed behavior; `env-vars.md` now states the consequence (was misleadingly "optional") so operators set the secret before relying on inbound channels (#1799).
91. 👤 **Unsigned installers** — code-signing certs are an identity/cost step. (business)
92. ✅ **VPS installer pulled mutable `main`** — now defaults to the latest published release, falls back to `main` with a warning (#1799).
93/94/96/97. 🔧/👤 **Upgrade runbook, backup/DR, retention enforcement, IaC** — ops docs + small eng.
95. 🔧 **Postgres RLS enable-on-live-data sharp edges** — documented in `multi-tenancy.md`; safer migration is eng backlog.

## I. Branding (customer-facing)

98. ✅ **Installer said "Maverick"** — wizard now "Lightwork installer" (#1798).
99. ✅ **Desktop app shipped as "Maverick"** — Tauri productName/title/desc + Svelte UI now Lightwork (#1798).
100. ✅ **Broken `/Lightwork` repo URLs** — pointed at the real `Day-AI-Labs/Maverick` (#1798).
101. ◐ **MCP server slug `maverick`** — intentional machine identifier (like the PyPI `maverick-agent` name); not a buyer-facing display string.
102. ✅ **Dashboard branding** — already "Lightwork," footer co-branded "Lightwork by Daybreak Labs" (verified, #1798).
103. 👤 **"Daybreak Labs" placeholder company name** — the product-portfolio naming worksheet owns final naming. (founder)

## J. Market, competition & timing

104–110. 👤 **Wedge commoditization (Entra/Okta), budget timing, design-partner LOI gate, incumbent aggregators, capital intensity, odds, EU-AI-Act timing** — strategy/GTM bets documented in `docs/research/commercialization/`. Not code; the founder's calls. (founder/strategy)

---

## What remains, by owner

- **Engineering backlog (large):** the regulated-SaaS substrate — enforced multi-tenant
  isolation, SSO/OIDC by default, resource RBAC, secrets vault, SIEM/WORM export,
  control/data-plane split, Postgres+RLS (#48, #51–#65). This is the audit's
  ~30–40 person-week floor and the real gate on a hosted regulated offering.
- **Engineering backlog (small):** #41, #55, #66, #76, #78, #81, #94 — each a
  contained hardening task.
- **Business / legal / founder:** certifications (#32–#40), contracts (#3–#5, #43–#46,
  #86), pricing decisions (#7, #11, #15–#21), entity/trademark/insurance/positioning
  (#22–#31), GA/signing/maintainer (#2, #84, #87, #91), market bets (#104–#110). None
  are code; they are tracked here so nothing is lost.
