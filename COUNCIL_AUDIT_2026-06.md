# Enterprise-Hardening Council Audit — 2026-06

A six-track adversarial audit (authz/multi-tenancy, injection/SSRF/sandbox,
crypto/audit-integrity, concurrency/HA-DR, supply-chain/CI, enterprise-features)
against the ServiceNow / CrowdStrike / Palo Alto deployment bar. Every Critical
and most Highs were verified in source. This file tracks what was **fixed in
this branch** and what **remains** (org/process or large-architecture work that
can't be a surgical code change).

## Correction to prior audit docs

The earlier docs claimed "every control ships OFF by default." That is **stale**.
`security_defaults.secure_by_default()` returns True, and at-rest encryption
(`crypto_at_rest.at_rest_enabled`), audit signing (`audit/writer._resolve_signing`),
fail-closed consent, and the tool-risk ceiling all resolve through it → **ON by
default**. Only outbound PII redaction (`privacy_egress`, default off), the egress
lock, and OIDC are opt-in (the last two justified: they'd break the cloud-LLM /
local-single-user happy path). The shield stays fail-open per kernel rule 1.

---

## FIXED in this branch

| ID | Severity | Issue | Fix |
|----|----------|-------|-----|
| C3 | Critical | Postgres cross-tenant IDOR cluster: `goals_for_origin` leaked decrypted goal content cross-tenant; `add_artifact`/`create_share_link`/`record_signoff`/`record_goal_origin` wrote by raw `goal_id` with no tenant gate; `resolve_share_link`/`revoke_share_link` unscoped. | Tenant-scoped every read; gated every write on the parent goal being in the active tenant (`WHERE EXISTS`, mirroring `start_episode`). Single-tenant path byte-identical. |
| C2 | Critical | Capability grants deserialized off the job queue with no signature → forgery (empty `allow_tools` = all tools; forged principal dodges revocation). | HMAC-SHA256 sign at enqueue / verify fail-closed at dequeue with a shared `MAVERICK_QUEUE_SIGNING_KEY`; one-time warning under enforcement when unset. |
| C1 | Critical | `plugin_ca.verify_artifact` (fail-closed, root-pinned) was wired into no loader — plugins executed in-process with no provenance. | `_gate` now verifies the entry-point module file against `[plugins] ca_root_pubkey` **before** `ep.load()`, fail-closed, gated on config / enterprise mode. Convention: `maverick_plugin.sig.json` bundle. New test suite. |
| C6/C3-skill | Critical | Public-dataset skill import bypassed Shield + signature; on-disk skills never re-verified at load. | `import_records` now Shield-scans the body + enforces signing policy; `available_skills` re-verifies under `require_signed`. |
| H2 | High | Shield decode pre-pass skipped under the SDK backend — SDK deployments got zero encoding-evasion coverage. | Pre-pass runs under any active backend via a local builtin floor (no extra remote calls). |
| H4-shield | High | `decoded_variants` bailed above 20k chars while the scanner reads 256 KB → trailing-payload bypass. | `_MAX_LEN` raised to 262 144 to match the scanner; depth to 3; work still bounded by `_MAX_VARIANTS`. |
| H3-crypto | High | `worm push` shipped **plaintext** audit data into a multi-year immutable lock when run before `seal`. | Refuses an unsealed closed day-file when sealing is active (at-rest on + key present); inert otherwise. |
| H1-conn | High | `notion`/`shopify`/`posthog`/`gdrive` connectors replayed bearer tokens to other hosts on a 30x. | `follow_redirects=False` (matching `jira.py`). |
| H10 | High | SCIM auth gate 500'd on a non-ASCII bearer (`compare_digest(str,str)`) — DoS/info-leak on the IdP surface. | Compare on bytes. |
| H11 | High | proxy-auth trusted **all** loopback peers when `trusted_proxies` unset → identity-header spoof from any co-located process. | Loopback fallback off under enterprise mode / `trust_loopback=false`; explicit pin unaffected. |
| #8 | Medium | `create_child_goal` / `upload_attachment` / `export_walkthrough` were viewer-writable. | Added `require_permission("operate")`. |
| #9 | Medium | Unknown `max_risk` string ranked "medium", relaxing a stricter intended ceiling. | `Capability.__post_init__` coerces unknown levels to the tightest. |
| H4-crypto | Medium | `browser_auth_vault` wrote its sealed store world-readable. | 0600 atomic temp+replace. |

All changes ship with green tests (existing suites + new `test_plugin_signature_gate.py`,
`test_decode_sdk_backend.py`, WORM-gate tests) and are lint-clean. Each keeps the
default single-tenant / no-auth / no-key path behavior-identical.

---

## REMAINING — recommended next (not in this branch)

### Architecture (large eng)
- **Shared-state store for multi-replica correctness (C4/C5/H13).** `killswitch`
  and `Budget` have *no* cluster story; rate-limit / webhook-dedup / OIDC-replay
  engage only under Postgres and silently degrade to per-process on the default
  SQLite backend. Introduce one shared store (Redis/PG) as a hard dependency when
  `replicaCount>1`; route halt, budget, breaker/failover, rate-limit, dedup, and
  idempotency through it; fail `/readyz` when absent. **This is the single
  highest-leverage fix for fleet correctness** (the emergency stop currently only
  halts the replica that served the request; budget caps are per-process so N
  replicas spend ≤ N× the cap).
- **Complete Postgres+RLS multi-tenancy.** Add per-request tenant-pinning
  middleware, `FORCE ROW LEVEL SECURITY` by default in hosted mode, add
  `projects`/`fact_history` to `_TENANT_TABLES`, port SQLite schema v20 to PG,
  default a small connection pool. (The IDOR fixes above harden the app layer;
  RLS is the DB backstop.)
- **Idempotency keys** on all goal-creating POSTs; **webhook retry/DLQ**.
- **Off-host audit/proof signing (H5/H6-crypto).** The audit anchor is an
  on-disk same-host key; `reanchor_file` can rewrite history; the proof-pack
  manifest has no shipped verifier and crypto guarantees report PASS when
  `cryptography` is absent. Require a KMS/HSM signing backend under enterprise
  mode; ship `verify_manifest`; treat crypto-skipped guarantees as INCONCLUSIVE.
- **Key lifecycle (H4-crypto, H3 broader):** real DEK rotation (re-encrypt, not
  additive-only), crypto-shred for DSAR, FIPS mode, Azure Key Vault backend.

### Code (medium eng)
- Consolidate the ~40 hand-written SaaS connectors (`home_assistant`, `sap`,
  `workday`, `servicenow`, …) onto `make_rest_tool`/`_ssrf.safe_client` so they
  get IP-pinning + the egress boundary.
- Plugin lockfile fail-closed on content-hash mismatch; default plugin/skill
  signing on under enterprise mode; weak-copyleft + `caldav`-GPL license gate.
- Commit `uv.lock`; `--require-hashes`/`--frozen` in CI so gates audit the
  shipped tree. Add Trivy image scan + CodeQL; SLSA provenance attestation.
- Shield: dedicated cipher-detection (ROT13/Atbash) layer that scans-and-discards
  rather than polluting `decoded_variants` (keeps the clean-text invariant);
  multilingual override-verb variants; homoglyph skeleton via `confusables.txt`.
- SAML 2.0; OIDC `groups` → role mapping; SCIM Groups endpoint + `sub` linkage so
  deprovisioning revokes access.

### Org / process (not code)
- SOC2 Type II + ISO 27001 + third-party pentest (all currently self-generated
  evidence) — the biggest single sale blocker.
- Vendor IR plan + committed breach-notification SLA (template token today).
- FedRAMP / NIST 800-53 mapping for federal/SLED.
- Fill `docs/enterprise/legal/subprocessors.md` (still a placeholder); reconcile
  the "Lightwork" vs "Maverick" branding in legal docs.
- Native installer signing/notarization (Apple/Windows certs).
- Native SIEM connector (Splunk/Sentinel/Chronicle) + PagerDuty/Opsgenie;
  API-key lifecycle + server-side session revocation; data-residency enforcement
  (today it's header passthrough, not a real control); legal-hold enforcement;
  close the vector/trajectory-store erasure gap for DSAR.
