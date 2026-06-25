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

**Engineering backlog — re-scoped after a code-level re-audit.** The audit's
~30–40 person-week estimate assumed these were greenfield. A file-by-file review
found the regulated-SaaS substrate was *largely already built* (mature Postgres
tenancy with fail-closed RLS, per-tenant flooring + KMS/DEK, OIDC/SAML/SCIM +
RBAC + owner-row scoping, WORM export, an out-of-process dispatcher seam, a
unified enterprise/REGULATED_PROFILE). The real remaining work was a set of
*contained, opt-in* hardening tasks, now landed:

- ✅ **#51/#57 enterprise-default isolation+RLS** — strict per-tenant reads and
  Postgres RLS auto-enable under `MAVERICK_PROFILE=enterprise`, gated by a boot
  preflight that refuses to start on legacy NULL-tenant rows.
- ✅ **#52 guarded require-auth** — the dashboard refuses to boot if
  `[dashboard] require_auth` is set with no token/OIDC/proxy (PR #1803, merged).
- ✅ **#58 session/token revocation** — per-principal revocation epoch; logout-
  everywhere + SCIM deprovision end live sessions/bearers.
- ✅ **#54 secrets vault seam** — `secret_provider.get_secret()` with a `file`
  backend (Vault/CSI/Docker-secret mounts), wired into OIDC/webhook/SCIM secrets.
- ✅ **#56 SIEM forwarder** — `maverick audit forward` pushes the audit log to a
  tcp/udp syslog or http(s) (Splunk HEC) collector (push counterpart of export).
- ✅ **#62 control/data-plane** — the gRPC remote-worker dispatcher is now wired
  into dashboard startup (it had a complete installer nothing called).
- ✅ **#41 data residency** — strict region pin enforced at boot via
  `require_residency_or_die()` + a `verify_deployment()` guarantee.
- ✅ **#78 budget/cap coordination** — the per-run dollar cap is clamped to the
  tenant's remaining daily allowance, so one run can't overshoot the tenant cap.

Earlier-merged smaller items: #55, #68, #79, #80, #81, #83, #90, #92 (PRs #1798/
#1799). Genuinely-large items still open as *roadmap*, not blockers: per-tenant
KMS at fleet scale, Alembic-grade migration governance, and an automated
control/data-plane e2e + evidence artifact.

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
41. ✅ **No data-residency / region-pinning** — `maverick.residency` declares the
    deployment region + allowed set (EU/EEA groups expand) and, in strict mode
    (`MAVERICK_RESIDENCY_STRICT` / `[residency] strict`), refuses to boot when the
    region is missing or outside the allowlist (`require_residency_or_die`, wired
    into the dashboard lifespan; also a `verify_deployment()` guarantee). Off by
    default. Honest scope: it pins/validates the *declared* region, not the
    physical location of every byte.
42. 👤 **Vuln-disclosure program has no track record** — time + reports. (business)

## E. Legal contracts

43–46. 👤 **DPA / SLA / sub-processor list / MSA are unsigned templates** (`docs/enterprise/legal/`) — intentionally counsel-completed per deal; not fabricated here. (legal)

## F. Security posture & engineering readiness

47. ✅ **Contradictory security-default docs** — reconciled to the actual `secure_by_default()` behavior (at-rest encryption + audit signing default ON), verified via `collect_soc2_evidence` (#1798). *Post-merge review:* also fixed two stale "opt-in" rows in the `soc2-controls.md` control matrix that the prose pass had missed.
48. 🔧◐ **Default `local` sandbox runs host shell** — honest in `SECURITY.md`; the wizard already defaults real installs to a container when available, and enterprise mode upgrades `local`→container and fails closed. Making it fail-closed everywhere is a kernel-philosophy change (eng/decision).
49. ◐ **Agent Shield optional / fails open** — kernel rule 1 (fail-open by design); documented as a floor, not a guarantee.
50. 👤 **Residual risk R-01 (sandbox escape) → pen test** — schedule the pen test. (business)
51–65. ✅◐ **Multi-tenant isolation, SSO/OIDC-by-default, resource RBAC, secrets vault, SIEM export, control/data-plane split, fail-closed enforcement** — a code-level re-audit found this substrate *largely already built* (Postgres tenancy + fail-closed RLS, per-tenant flooring + KMS/DEK, OIDC/SAML/SCIM + RBAC + owner-row scoping, WORM export, dispatcher seam, unified enterprise profile). The remaining opt-in gaps are now closed: **#51/#57** enterprise-default strict-isolation + RLS with a boot preflight; **#52** guarded require-auth (PR #1803); **#58** session/token revocation; **#54** `secret_provider` vault seam; **#56** `maverick audit forward` SIEM push; **#62** gRPC dispatcher wired into startup. Roadmap (not blockers): per-tenant KMS at fleet scale, migration governance, control/data-plane e2e.
52. ✅ **Dashboard could boot with auth required but unconfigured** — `_assert_dashboard_auth_configured()` refuses startup when `[dashboard] require_auth` is set with no token/OIDC/proxy (PR #1803, merged).
54. ✅ **No secrets vault** — `maverick.secret_provider.get_secret()` adds a `file` backend (Vault Agent / Secrets Store CSI / Docker-secret mounts), wired into the OIDC client/session secrets, the inbound webhook secret, and the SCIM bearer; default `env` backend keeps existing behavior.
56. ✅ **SIEM export was pull-only** — `maverick audit forward` pushes the tamper-evident log (JSONL/CEF) to a tcp/udp syslog or http(s) collector (Splunk HEC), the push counterpart of `audit export`; same paid-tier entitlement gate.
57. ✅ **Enforced multi-tenant by default** — see #51 (strict isolation + RLS auto-on under enterprise mode).
58. ✅ **No way to revoke a session/bearer** — per-principal revocation epoch (`session_revocation.py`): logout-everywhere and SCIM deprovision (`active=false`/DELETE) end live cookies and OIDC bearers, not just future logins.
62. ✅ **Control/data-plane split incomplete** — the gRPC remote-worker dispatcher (`grpc_dispatcher.install_from_config`) is now installed at dashboard startup as the out-of-process fallback after the arq queue; it had been complete but uncalled.
55. ✅ **Audit signing silently degrades to unsigned if `cryptography` missing** — warns loudly and refuses under a compliance floor (earlier pass).
66. 🔧 **Firecracker silently falls back to Docker** — small: alert on fallback.
67. ◐ **Plugins run in-process** — load-time allowlist by design; syscall sandbox is eng backlog.
68. ✅ **"Config not schema-validated"** — `config-lint` already existed (`maverick config-lint` + startup warning); fixed the `[budget] self_tuning` false-positive and the stale `configuration.md` claim (#1799). *Post-merge review:* `configuration.md` had claimed config-lint also runs inside `maverick doctor`, which it did not — now wired in (advisory `config-lint` rows), so the claim is true and `doctor` catches budget typos.

## G. Billing, licensing & entitlement

69/73. ◐ **No payment processor / no subscription automation** — by design for contract-sold tiers; `docs/billing.md` documents the meter→idempotent-invoice→AR model (#1799).
70/72. ◐ **No license key; plans config-overridable** — entitlement plans gate features per tenant; collection is contract/AR. By design, documented.
71. ◐🔧 **Entitlement fails open** — deliberately permissive so single-tenant/self-host is never gated; a strict multi-tenant enforcement mode remains an optional eng add.
74/75/76/77/81. ◐ **Quota soft-warn, off-by-default, concurrency fail-open, fail-soft reads, plan-level cap** — wired onto the core run path (#74), plan-cap fallback (#81, opt-in), loud fail-soft reads (#77); the remaining off-by-default behaviors are intentional single-tenant defaults.
78. ✅ **Uncoordinated ceilings** — the per-run budget (`max_dollars`) is now clamped to the tenant's remaining daily allowance (`registry.tenant_remaining_today`), the highest-precedence budget layer, so a single run can't overshoot the per-tenant aggregate cap between over-quota checks.
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
95. ✅ **Postgres RLS enable-on-live-data sharp edges** — the enterprise auto-on path (#51/#57) now runs `_preflight_rls_or_die()`, which refuses to boot when legacy `tenant_id IS NULL` rows would be frozen and points the operator at `maverick tenant backfill`; explicit `MAVERICK_PG_RLS=1` keeps the documented opt-in path. Safe-on-ramp tooling (`rls-preflight`/`backfill`) documented in `multi-tenancy.md`.

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

- **Engineering backlog (the regulated-SaaS substrate, #48/#51–#65):** the code-level
  re-audit found this *largely already built*, and the remaining opt-in gaps are now
  closed (#51/#52/#54/#56/#57/#58/#62 — see the resolution summary). What is left is
  **roadmap, not a purchase blocker**: per-tenant KMS at fleet scale, Alembic-grade
  migration governance, and an automated control/data-plane e2e + evidence artifact.
- **Engineering backlog (small):** #66, #76, #94 — each a contained hardening task
  (Firecracker→Docker fallback alerting, concurrency default, IaC examples). #41,
  #55, #78, #81, #95 are now resolved (above).
- **Business / legal / founder:** certifications (#32–#40), contracts (#3–#5, #43–#46,
  #86), pricing decisions (#7, #11, #15–#21), entity/trademark/insurance/positioning
  (#22–#31), GA/signing/maintainer (#2, #84, #87, #91), market bets (#104–#110). None
  are code; they are tracked here so nothing is lost.
