# Regulated-Deployment Readiness — Code-Grounded Engineering Gaps

> Teardown audit #4 for the commercial pivot (regulated-compliance + agent
> governance vs OneTrust). Method: read the actual code in
> `packages/maverick-core/maverick/` and `packages/maverick-dashboard/`, then
> test each enterprise must-have against it. All file:line pointers verified on
> the working tree, 2026-06-06. Adversarial framing: "opt-in, default-off,
> fail-open" primitives are scored as NOT enforced.

## Bottom line

The strategy doc (`regulated-deployment-and-compliance-platform.md`) claims
"~70% built on be-compliant." **That number is honest about cryptographic
primitives and dishonest about enterprise readiness.** What exists is a genuinely
good *single-tenant, single-operator, local-first* governance substrate: an
Ed25519 hash-chained audit log with cross-file anti-deletion anchors
(`audit/signing.py`), GDPR erase that re-anchors the chain (`audit/erase.py`),
attenuating signed capabilities (`capability.py`), and a tool-level ACL
(`safety/tool_acl.py`). That is real and differentiated.

But **every control a regulated buyer actually procures against is either
absent or is a default-off no-op**: there is zero identity federation (SSO/OIDC/
SAML/SCIM appears nowhere except PyPI CI publishing), zero encryption-at-rest
(`world.db` and audit NDJSON are plaintext; no KMS, no keychain, no DEK), no
resource-level RBAC (ACL gates *tools*, never *data rows*), no SIEM export, no
data-residency/region pinning, no FIPS mode, and no secrets *vault* (the only
"secrets" file is a regex redactor, `secrets.py`). Multi-tenancy is a
`contextvars` path-prefix (`paths.py`) wired into **exactly one** subsystem
(cross-session memory) — the world model and audit log it is supposed to isolate
are still global. The dashboard control plane has a **single shared bearer
token** and no concept of a user. **Realistic readiness for a bank/hospital/
pharma/gov buyer is ~15-20%, not 70%** — and the 70% figure conflates "we have
crypto building blocks" with "an enterprise can deploy this."

## Have vs missing (with file pointers)

| Must-have | State | Evidence / why it does not count |
|---|---|---|
| **SSO / OIDC** | **MISSING** | No code. `grep -i oidc` hits only PyPI/Sigstore CI (`.github/workflows/publish.yml:10,17`). Identity is channel strings (`tg:123`). |
| **SAML** | **MISSING** | Zero occurrences anywhere in `packages/` or `apps/`. |
| **SCIM provisioning / de-provisioning** | **MISSING** | Zero occurrences. No user store exists to provision *into* — there are no user accounts. |
| **Dashboard auth (RBAC)** | **Single shared token** | `maverick_dashboard/app.py:291-329`: one `MAVERICK_DASHBOARD_TOKEN` for everyone, else loopback-only. No users, no sessions, no roles. Any token-holder sees all goals/spend/audit and can approve anything. |
| **Encryption at rest** | **MISSING** | `world.db` opened plaintext (`world_model.py:393`); audit is plaintext NDJSON (`audit/writer.py`). Protection is Unix file mode `0o600`/`0o700` only (`world_model.py:366,389,395`). No `keyring`/`vault`/`hsm`/`AES` import in core. |
| **KMS / per-tenant DEK** | **MISSING** | No envelope encryption, no key hierarchy. The only crypto is Ed25519 *signing* keys stored next to the data (`audit/signing.py:41`). |
| **Multi-tenant isolation (world model + audit)** | **~5% — memory only** | `paths.py:81` `data_dir()` is the tenancy primitive but is called in **one** file: `tools/memory.py:41`. `world_model.py:24` and `audit/writer.py:25` use hardcoded global `~/.maverick/` paths. **No tenant column** in any table — SQLite schema v10 (`world_model.py:31-164`) and the Postgres mirror (`world_model_backends/postgres.py:46-75`) are both global. Tenancy is opt-in/default-off (`paths.py:97`). |
| **Tenant scope actually enforced** | **Broken even when on** | `server.py:95` wraps `run_goal` in `tenant_scope`, but `create_goal`/`append_turn`/`get_or_create_conversation` run **outside** that scope against the shared `self.world` (`server.py:81-88`). Dashboard `_world()` reads `DEFAULT_DB` with no tenant (`app.py:561-577`). The "co-tenant" comment at `world_model.py:386` is about *OS users*, not app tenants. |
| **Per-tenant quotas / chargeback** | **MISSING — Budget is per-run** | `Budget` (`budget.py:123-355`) is a per-invocation dataclass: no persistence, no aggregation across runs, no principal/tenant key, no time window. `budget_from_config` (`budget.py:366`) builds a fresh cap per goal. Chargeback would be net-new. |
| **Immutable audit** | **Partial — tamper-EVIDENT, opt-in** | Ed25519 chain + cross-file anchors + `verify_chain`/`verify_anchors` (`audit/signing.py:173-556`) is strong. But signing is **default OFF** (`audit/writer.py:74-92`, `sign=False`), the trust-anchor key is co-located (the file's own docstrings, e.g. `signing.py:584-586`, admit it does not stop an attacker with key access), and it is **append-only by convention, not WORM** (no `chattr +a`, no Object-Lock). |
| **SIEM export (Splunk/Sentinel/S3-WORM)** | **MISSING** | No shipper. `grep -i splunk\|sentinel\|siem\|object.lock\|WORM\|chattr` in core → nothing. Closest is a `/api/v1/cost.csv` spend export (`app.py:1330`). |
| **Data residency / region pinning** | **MISSING** | No `residency`/`region_pin` code. "Residency" is an *argument* (self-host keeps data local), not a feature; no region tagging or enforcement. |
| **FIPS-validated crypto** | **MISSING** | No FIPS mode; relies on `cryptography` (OpenSSL) with no validated-module gate. SHA-256 + Ed25519 are fine algorithmically but un-attested. |
| **Secrets management** | **MISSING (name collision)** | `secrets.py` is a **regex secret *scrubber*** for logs (`secrets.py:87 scrub()`), not a vault. No credential store, rotation, or broker. Provider keys are read from raw env vars (`app.py:416-429`). |
| **RBAC at resource level** | **MISSING** | ACL (`safety/tool_acl.py`) and capabilities (`capability.py`) gate **tool names + a risk ceiling** only. No notion of "user X may read goal/world-row/audit-day Y." `Capability.principal` is a free string with no link to a federated identity. |
| **Segregation of duties / two-person rule** | **MISSING** | Consent default mode is `auto-approve` (`safety/consent.py:59-63`). Approvals queue is single-approver, status flip only; the `approvals` table (`world_model.py:87-96`) has **no approver-identity column**. No N-of-M. The consent ledger is plaintext, **unsigned** (`consent.py:75-85`) — unlike the audit log. |

## Overclaims vs code

The strategy doc is broadly careful but several load-bearing statements
overstate what the code does. Flagging the ones that would burn us in a buyer's
security review:

1. **"~70% built on be-compliant."** Reframes cryptographic *primitives* as
   *deployability*. By control count against a regulated checklist, the
   enforced-and-present fraction is ~15-20%. The 70% is defensible only for "do
   we have an audit/capability/erase library," which is not what a CISO scores.

2. **Part 2 table: "Tenant isolation 🟡 in progress: data-path + memory done;
   world-model/audit next."** Technically true but the "🟡" hides that isolation
   reaches **one** non-critical store (memory) and is *broken at the call site
   even when enabled* (`server.py:81-88` writes the world model outside the
   tenant scope). The two stores that hold the regulated data — world model and
   audit — have **no tenant dimension at all**, not even a column to migrate.
   Calling this "in progress" implies 50%+; it is closer to 5%.

3. **Part 3 §2: "Reuse the existing `cryptography` dep ... [audit at rest] in
   2027 H1. Pull forward."** Understates scope. The roadmap line
   (`ROADMAP.md:413`) encrypts **only the audit log**, via OS keychain, for a
   single host. It does **not** cover `world.db` (where goals, conversations,
   facts, and PII live), per-tenant DEKs, or external KMS — all of which the
   gap list itself demands. The roadmap is narrower than the gap it claims to
   close.

4. **Part 2: "RBAC (tool-level) ✅."** Accurate *with the parenthetical*, but the
   doc later leans on "RBAC" generically (per-regime table, HIPAA/SOC2 rows) in a
   way a reader maps to resource/role RBAC. Tool-ACL ≠ the access control HIPAA
   §164.312(a) or SOC2 CC6 auditors test.

5. **Implicit: "immutable audit."** The audit is tamper-**evident**, opt-in, and
   keyed on the same host it protects. "Immutable" (WORM, externally anchored)
   is what a regulator means and is not present. The doc's own Part 2 says
   "append-only," which is correct — but Part 4's pitch ("tamper-evident action
   audit as a compliance artifact") will be read as immutable by buyers.

6. **Nowhere on the 36-month roadmap** do SSO/OIDC, SAML, SCIM, KMS, per-tenant
   DEK, SIEM-to-Splunk, data-residency, or FIPS appear. The strategy doc says
   these are "scattered across 2027-2028" and just need pulling forward — but
   they are not actually scheduled at all. They are net-new scope.

## Minimum bar for deal #1

A regulated buyer (even a mid-market hospital or a fintech, not yet FedRAMP)
will not sign without, at minimum:

| Gap to close | Why it is non-negotiable | Realistic eng effort |
|---|---|---|
| **SSO/OIDC + enforced de-provisioning** | Table stakes in *every* regime; "shared bearer token" fails the first questionnaire. New `identity/` module → map federated principal onto `Capability.principal` + a real user store; gate the dashboard middleware (`app.py:291`) on it. SCIM can wait if de-provisioning is manual-but-documented. | **6-9 pw** (OIDC + session/user model + dashboard wiring); +4-6 pw for SCIM. |
| **Encryption at rest for `world.db` + audit** | PHI/PCI on plaintext disk is a hard stop. Envelope-encrypt with a key from OS keychain or KMS; start single-key, design for per-tenant DEK. | **4-6 pw** (single host, keychain); +6-8 pw for external KMS + per-tenant DEK. |
| **Finish tenant isolation (world model + audit) + enforce at call sites** | Multi-customer hosting is impossible without it; the current state silently co-mingles. Add `tenant_id` columns + migrations to SQLite **and** Postgres schemas, route `world_model`/`audit/writer` through `data_dir()` or a tenant-filtered query layer, and fix `server.py` to open the world model inside the scope. | **8-12 pw** (schema + query refactor across both backends + the dashboard `_world()` path; this touches a lot of SQL). |
| **Immutable audit + SIEM export** | Auditors want logs they cannot edit and a feed into their SIEM. Add S3-Object-Lock/WORM sink + `chattr +a` option; ship signed NDJSON to Splunk/Sentinel/S3. The signing exists; this is plumbing. | **3-5 pw**. |
| **Resource-level RBAC + record approver identity** | "Who could see/approve what" must be answerable per user/resource. Extend capabilities/ACL to resources; add approver-id + N-of-M to the `approvals` table. | **5-8 pw**. |
| **Per-tenant quotas/chargeback** | Needed to bill and to bound a tenant's spend. Extend `Budget` to a persisted per-principal aggregate with a time window; do **not** bypass `check()`. | **3-5 pw**. |

**Floor to credibly enter a regulated POC: ~30-40 person-weeks of engineering**
(SSO + at-rest + real tenant isolation + WORM/SIEM), before any SOC 2 Type II /
HIPAA BAA / DPA process clock — which is months of calendar time regardless of
code. The doc's "narrow gaps" framing is wrong by roughly an order of magnitude
once "default-off primitive" is held to the "enforced control" standard.

## What would kill us

- **Selling "70% compliant" into a real security review.** The first
  OIDC/SCIM/encryption-at-rest/data-residency line on a vendor questionnaire is
  a flat "no." Leading with the 70% number and getting caught is a credibility
  death that poisons the whole account. Lead with the audit/capability story
  (which is genuinely strong) and be explicit that identity + at-rest + tenancy
  are in flight.
- **A multi-tenant data-leak incident.** If we host two customers before
  isolation is finished and *enforced* (today: world model + audit are global,
  and tenancy breaks at the `server.py` call site even when "on"), one tenant
  can read another's goals/PII. For a HIPAA/PCI customer that is a reportable
  breach and likely company-ending. Do **not** offer hosted multi-tenant until
  the world model + audit carry an enforced `tenant_id`.
- **"Immutable audit" claims meeting an attacker model.** The signing key lives
  next to the log (`signing.py` says so repeatedly). Anyone who roots the host
  can forge a clean chain. Marketing "tamper-proof" instead of "tamper-evident,
  externally-anchorable" invites a researcher takedown. WORM + external key
  custody must ship before that word is used.
- **FedRAMP/gov daydreaming.** No FIPS, no continuous-monitoring, no ATO path,
  single-token control plane. Gov is years out; chasing it now burns the budget
  that should buy the mid-market regulated wedge.
- **The fail-open house rule colliding with "enforced compliance."** Every
  control here is opt-in/fail-open by deliberate kernel design (CLAUDE.md rule
  1). A compliance *product* must be able to **fail closed and prove it stayed
  closed**. Reconciling "kernel never requires the shield" with "enterprise SKU
  enforces policy" is an architectural decision (a hard enforcement mode /
  policy-decision-point the deployment cannot disable) that does not exist yet —
  and underestimating it is how the whole pivot slips.
