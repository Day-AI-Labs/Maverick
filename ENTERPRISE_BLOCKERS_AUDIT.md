# Enterprise Deployment Blockers — Maverick Audit

> Method: the codebase was swept in seven parallel deep passes (security/sandbox,
> auth/secrets/crypto, data/persistence/scalability, ops/observability/deploy,
> compliance/audit/privacy, supply-chain/CI, code-maturity/stubs). Findings are
> de-duplicated and cite real `file:line` evidence. Nothing was modified.

## TL;DR — the through-line

The engineering **core** (Ed25519 hash-chained audit, OIDC hardening, AES-256-GCM
at-rest, the sandbox container backends, the dreaming/hindsight/evolve learning
lifecycle) is **real and well-built — not theater.** The blockers cluster in five
recurring patterns:

1. **Every protective control ships OFF by default** (shield, egress lock, audit
   signing, at-rest encryption, consent gate, tenancy, OIDC). The product is
   secure-*if-configured*, not secure-by-default.
2. **Single-node SQLite is the real architecture; the Postgres/HA path is
   incomplete** (missing ~30 methods, schema v13 vs v20, dashboard ignores it,
   no at-rest support).
3. **The marketed security/governance surface is regex-based and fails open.**
4. **The tamper-evident audit log doesn't record success-path who-did-what-when.**
5. **Pre-1.0 alpha** with a few marquee claims that don't survive inspection.

Severity legend: **C** critical (hard blocker) · **H** high · **M** medium · **L** low.

---

## CRITICAL

### Architecture / data layer
- **C1. Postgres (HA) backend is incomplete — runtime `AttributeError` on core
  flows.** ~30 `WorldModel` methods exist only in SQLite (projects, share links,
  sign-offs, artifacts, `search_goals`, approvals, fact history…). Backend
  docstring admits it ships "the shape + hot-path methods only."
  `packages/maverick-core/maverick/world_model_backends/postgres.py:19-23`.
- **C2. Dashboard ignores the Postgres backend — split-brain state.** `_world()`
  hard-codes SQLite `WorldModel(DEFAULT_DB)` and never calls `open_world()`;
  runner/channels/gRPC honor `MAVERICK_WORLD_BACKEND=postgres`, so on a PG deploy
  the dashboard reads a stale local `~/.maverick/world.db`.
  `packages/maverick-dashboard/maverick_dashboard/_shared.py:35-59`.
- **C3. Postgres schema is behind SQLite (v13 vs v20).** Tables/columns from
  migrations 14–20 have no PG counterpart — structurally stale, not just
  method-incomplete. `world_model.py:30` vs PG migration ladder.
- **C4. Postgres + encryption-at-rest is a hard failure** (`PostgresAtRestUnsupported`).
  Regulated buyers who need *both* a shared DB and at-rest encryption have no
  supported path. `world_model.py:2367-2386`.
- **C5. Multi-tenant world model is SQLite-file-per-tenant** (`~/.maverick/tenants/<t>/world.db`),
  explicitly *not* PG-backed — tenancy and horizontal scale are mutually
  exclusive. `world_model.py:2418-2435`.

### Security / governance
- **C6. Flagship "Shield" SDK does not ship; real protection is ~20–45 hardcoded
  regexes.** `import agent_shield` (the marketed "F1 0.988 / ~115 pattern" engine,
  extra `agent-shield>=14.0`) resolves to nothing in every real install, silently
  degrading to `builtin_rules` the vendor itself calls "weak against obfuscation."
  `packages/maverick-shield/maverick_shield/guard.py:55-59,159-165`;
  `builtin_rules.py:13-17`.
- **C7. Security controls fail OPEN on any internal error.** ~31 sites return
  `ShieldVerdict.allow()` inside `except Exception` across shield/safety/agent;
  a malformed input that throws in any detector is allowed through.
  `maverick_shield/guard.py:222-329`; `agent.py:1528-1542`.
- **C8. Default sandbox runs model-generated shell on the host (`shell=True`),
  no isolation.** Default backend is `local`; prompt injection = host RCE unless
  the operator has flipped enterprise / `require_container`.
  `packages/maverick-core/maverick/sandbox/__init__.py:244,393-394`;
  `sandbox/local.py:126`.
- **C9. Third-party plugins execute arbitrary code with no signature verification
  and no sandbox by default.** `ep.load()` runs after only an allowlist/name-squat
  check; isolation defaults to `"none"` (in-process). Signing infra exists but is
  wired only into *skills*, not plugins (`plugin_ca.py` marked roadmap 2028 H2).
  `plugins.py:202,315-389`; `plugin_isolation.py:19-54`.

### Compliance / privacy
- **C10. Tamper-evident audit chain does NOT record successful agent actions.**
  `GOAL_*`, `TOOL_*`, `EPISODE_*` events are defined but emitted to the signed
  chain only in tests/benchmarks — never from `agent.py`/`orchestrator.py`.
  Production `record()` logs only *denials*; the real who-did-what-when lives in
  the **plaintext, unsigned** SQLite world model. The "provable trail" sold to
  auditors is split. `audit/events.py:71-76` vs `orchestrator.py:360,455,517,529`.
- **C11. No outbound-prompt PII/PHI redaction.** `LLM.complete*` sends
  system+messages verbatim; the only pre-send gate is `assert_provider_allowed`.
  `privacy.py` is logs/audit-only; `provable_redaction.py` is never wired to
  egress; the "redact before egress" capability is a *model-optional skill*.
  `llm.py:632-644,755-761`; `privacy.py:1-19`; `skills_builtin/redact-pii-before-egress.md`.
- **C12. No data residency / region pinning / ZDR for any cloud provider.** Zero
  region/residency/no-retention knobs; only a generic `base_url` override. DeepSeek
  /Moonshot hard-pinned to China-jurisdiction endpoints. GDPR Art. 44 transfers
  cannot be met. `config.py` (no matches); `providers/deepseek_provider.py:22-24`.
- **C13. Prompts/responses/turns stored PLAINTEXT on disk by default.** At-rest
  encryption is off by default; the audit current-day file is always plaintext.
  Anyone with FS/backup access reads all history. `world_model.py:566-575,2097-2160`;
  `crypto_at_rest.py:29-33`.
- **C14. Subprocessor disclosure is an unfilled template.** `docs/enterprise/legal/
  subprocessors.md:1-24` is all `<placeholder>` — lists none of the 14 providers.
  A controller cannot complete a GDPR Art. 28 DPA schedule.

---

## HIGH

### Secure-by-default gaps
- **H1. Every governance/auth control is default-OFF.** Consent gate defaults to
  `auto-approve` (`safety/consent.py:8-9,75`), action gate becomes a logged no-op
  (`action_gate.py:24-28`), dashboard `has_permission` returns `True` with no
  principal (`dashboard/auth.py:216-226`), OIDC off (`oidc.py:204-208`), `tool_risk`
  ceiling unset = all risk allowed (`tool_risk.py:24-25`). The "governed workforce"
  ships ungoverned.
- **H2. Enterprise egress lock OFF by default** — a fresh install with an API key
  sends all prompts/tool outputs to Anthropic's cloud. `enterprise.py`; `llm.py:37,383`.
- **H3. Audit signing OFF by default** — default "tamper-evident log" is plain
  unsigned NDJSON. `audit/writer.py` `_resolve_signing` → `False`.
- **H4. At-rest encryption + per-tenant key isolation OFF by default.**
  `crypto_at_rest.py:111-154`; `world_model.py` at-rest flag.

### Security
- **H5. Shield is an optional dependency that fails open when absent** — when
  `maverick-shield` isn't installed, every `scan_tool_call/input/output` chokepoint
  is skipped. `orchestrator.py:85-94`; `agent.py:1416-1418`.
- **H6. Jailbreak/prompt-injection "detection" is 24 hand-written regexes**
  (`sigmoid(raw-1.0)`); any paraphrase/non-English/novel phrasing passes.
  `safety/jailbreak_heuristics.py:24-184`.
- **H7. `tool_risk` is a hardcoded allowlist; unknown tools default to `medium`,
  not high** — a new write-capable plugin with no registry entry isn't fail-safe.
  `safety/tool_risk.py:41-233`.
- **H8. Medium-severity attack rules never block at the default `high` threshold**
  — system-prompt-leak, authority/urgency, zero-width/bidi smuggling are
  notice-only by default. `config.py:358`; `builtin_rules.py:142-146`.
- **H9. `maverick dashboard` CLI skips the non-loopback-without-token startup
  guard** that `app.main()` enforces — and it's the exact entrypoint every deploy
  manifest invokes (`--host 0.0.0.0`). Blunted by middleware (remote peers 401),
  but the safety contracts diverge. `cli.py:2015-2031` vs `app.py:4714`.
- **H10. Reference architectures bind `0.0.0.0` with no `MAVERICK_DASHBOARD_TOKEN`
  /OIDC in the manifest** (the `kubectl create secret` example sets only
  `ANTHROPIC_API_KEY`). Insecure-by-omission for copy-paste operators.
  `deploy/reference-architectures/kubernetes/maverick.yaml:11-12,58,66-68` (+ecs/fly/railway).

### Reliability / ops
- **H11. Liveness/readiness probes hit HTML root `/`, not `/healthz`, in every
  prod-facing manifest.** `/` returns 200 even when the DB is unwritable or no
  LLM key is present, defeating the deep-health design; LB keeps routing to dead
  pods. helm `deployment.yaml:64,68`, k8s `:73,77`, fly `:38`, ecs `:28`, railway
  `:9` (demo-cluster correctly uses `/healthz` — proving the pattern was known).
- **H12. No graceful drain on shutdown.** Lifespan says "No shutdown work is
  needed"; no `terminationGracePeriodSeconds`/`preStop`; helm uses `Recreate` on
  a RWO volume → every upgrade kills in-flight LLM goals. `app.py:197-215`;
  `deploy/helm/.../deployment.yaml:11-12`.
- **H13. No PodDisruptionBudget, HPA, or NetworkPolicy anywhere in `deploy/`.**
  Single-replica `Recreate` chart = full downtime on every upgrade/drain.

### Data / scale
- **H14. Durable job queue is host-local SQLite** (`~/.maverick/jobs.db`) — a
  second replica/failover node can't see or claim scheduled/retry work. SPOF for
  all background work. `job_queue.py:44,123-252`.
- **H15. Audit log is `flock`-guarded NDJSON — single-host only.** `flock` doesn't
  serialize across hosts (and is unreliable on NFS); multi-replica tears the
  signed hash-chain. `audit/writer.py:67,76-112`.
- **H16. In-process rate limiting doesn't hold across replicas** — module-level
  deques/lock; N replicas allow N× the intended spend ceiling. `app.py:752-833`.
- **H17. Webhook dedup uses an in-memory set** — same delivery to two replicas is
  processed twice. `app.py:3502`. (Channel message dedup is correctly DB-backed.)

### Supply chain / licensing
- **H18. No lockfile anywhere** (`uv.lock`/`Cargo.lock`/`package-lock.json` absent
  or git-ignored) — builds are not reproducible; the Ed25519 audit-*verifier*
  binary itself can't be reproduced. `.gitignore:37,70`; `pyproject.toml:5-12`.
- **H19. ~80 Python deps are floor-only `>=` with no upper bound** (`pre-commit`
  has no specifier at all); with no lock, a breaking major lands silently.
  `packages/maverick-core/pyproject.toml:29,102-139`.
- **H20. Released native artifacts are unsigned** — PyInstaller binaries get no
  cosign step; Tauri `.dmg/.msi/.exe` are explicitly un-notarized. Gatekeeper/
  SmartScreen reject them. `release.yml:98-176`; `desktop.yml:13-16,111,149-150`.
- **H21. No dependabot/renovate** — no mechanism to surface/PR CVE fixes between
  manual floor bumps. (`.github/dependabot.yml` / `renovate.json` absent.)
- **H22. LGPL dependency shipped, invisible to the license gate.** `psycopg[binary]`
  (LGPL-3.0) at `maverick-core/pyproject.toml:51` & `maverick-knowledge/:23`; the
  scanner denies only *strong*-copyleft and CI scans only the installed tree
  (skips ~40 extras). Unmet LGPL obligations + false "policy OK." `license_scan.py:31`.
- **H23. No NOTICE/THIRD-PARTY attribution file** anywhere — redistributing a
  proprietary wheel embedding MIT/BSD/Apache deps without attribution breaches
  each. (confirmed absent.)

### Code maturity
- **H24. Pervasive silent error-swallowing** — 251 `except Exception: pass` in
  non-test code (206 in core), 1,526 broad `except Exception` total; masks
  failures and (with C7) silently disables controls. e.g. `cli.py:367-368`.
- **H25. "1,118 specialist packs" are declarative TOML prompt+policy manifests,
  not engineered capabilities** — one runtime, 1,118 system prompts. `maverick/domains/*.toml`.
- **H26. Governed connectors ship only an in-memory reference; real systems of
  record (Salesforce/ServiceNow/SAP) `raise NotImplementedError`.** The Palantir-
  style governed-action integration is unbuilt. `governed_connectors.py:12-40`.

### Privacy (additional egress)
- **H27. Multiple outbound channels bypass the egress lock** — webhooks
  (`webhooks.py:184-218`), 80+ REST enterprise connectors
  (`tools/enterprise_connectors.py:98-101`), federation gRPC delegation
  (`federation.py:472-565`). With the lock off (default) all are allow-all but SSRF.
- **H28. Primary system-of-record has confidentiality but no integrity** — world
  model rows (approvals incl. `decided_by`, costs, outcomes) have no hashing/
  chaining/signatures; encryption ≠ tamper-evidence. `world_model.py`.
- **H29. Audit signing key co-located with the writer** (`~/.maverick/audit/keys/`,
  0600) — host access = read key + re-sign forged history. Regulators expect
  HSM/KMS. `audit/signing.py`.

---

## MEDIUM

- **M1. `/metrics` is bearer-gated but no deploy artifact wires Prometheus auth**
  (no ServiceMonitor/scrape bearer) — alerting goes blind on any tokened deploy.
  `app.py:4610-4612`; `deploy/observability/prometheus-rules.yaml:4`.
- **M2. Two divergent metrics surfaces** with different names/ports — dashboard
  `/metrics` (`maverick_goals_total`…) vs core `observability.py:199-234` port 9100
  (`maverick_llm_calls_total`…); shipped dashboards/alerts cover only the first.
- **M3. `maverick serve` bypasses structured logging + secret scrubbing**
  (raw `logging.basicConfig`); inconsistent with the dashboard path. `cli.py:3323-3326`.
- **M4. uvicorn access/error logs stay plaintext even under JSON logging** (no
  `log_config` passed) — mixed JSON+text breaks Loki/CloudWatch ingestion. `app.py:4731-4732`.
- **M5. ~124 `MAVERICK_*` env vars, no config-schema validation** — a misspelled
  cap/backend silently falls back to a default (possibly unsafe single-node SQLite).
  `config.py:195`.
- **M6. `:latest`/floating image tags** in k8s (`maverick.yaml:57`) & ecs
  (`task-definition.json:12`); Docker base `python:3.12-slim` unpinned by digest,
  no `HEALTHCHECK`. Breaks reproducible deploy/rollback. `deploy/docker/Dockerfile:15`.
- **M7. Per-process tenant ceiling of 128, no LRU eviction** — hard cap on
  concurrent active tenants per replica. `world_model.py:2406`.
- **M8. Postgres backend serializes all callers on one connection by default**
  (pooling opt-in) — throughput bottleneck/head-of-line stall. `postgres.py:421-436`.
- **M9. Default knowledge/vector store is brute-force cosine over JSON in SQLite**
  — O(n) per query, no pagination; pgvector opt-in. `maverick_knowledge/store.py:46`.
- **M10. Generic REST connector follows redirects with no SSRF-pinned client** —
  a rogue SaaS endpoint can 3xx-redirect to `169.254.169.254` (IMDS) and exfil
  cloud creds; every other fetch path pins IPs. `tools/_rest_connector.py:102-104,392`.
- **M11. No access-control separation on audit data** — `/api/v1/audit/tail` &
  `/audit/grep` have no role gate; one shared bearer; no auditor-read-only role.
  `maverick-dashboard/.../api.py:1798-1830`.
- **M12. Audit data deletable by any host user/token holder (SoD failure)** —
  `maverick erase` hard-deletes audit rows, `maverick retention enforce` unlinks
  day-files, both ordinary CLI with no separate audit-admin auth. `audit/erase.py`,
  `audit/retention.py`.
- **M13. Retention purge is indistinguishable from tampering** — `purge_audit_files`
  deletes day-files without re-anchoring; `verify_anchors` then reports them as
  breaks. `audit/retention.py:69-86`.
- **M14. Firecracker "microVM isolation" tier is an unfinished scaffold** — falls
  back to plain docker; constructor raises `NotImplementedError` without `firectl`.
  Misrepresents a security-datasheet isolation guarantee. `sandbox/firecracker.py:148-189`.
- **M15. Constitutional policy layer silently drops invalid rules**
  (`except re.error: continue`) — a typo'd policy becomes no policy. `shield/constitutional.py:28-50`.
- **M16. LLM pricing table carries an unverified-rates TODO** in core code; feeds
  budget caps (a kernel rule). `llm.py:111`.
- **M17. Demo-cluster k8s manifest omits `securityContext` entirely** (copy-paste
  blueprint fails restricted PSS). `deploy/reference-architectures/demo-cluster/k8s.yaml:66-156`.
- **M18. ECS task def lacks non-root/read-only/cap-drop hardening.**
  `deploy/reference-architectures/ecs/task-definition.json:9-42`.
- **M19. SBOM is best-effort (`continue-on-error`), not attached to releases, no
  provenance/attestation.** `ci.yml:227-244`.
- **M20. GitLab CI template ships no security scanning** (no SAST/dep-scan/secret-
  detection/container-scan). `deploy/gitlab-ci/maverick.gitlab-ci.yml`.
- **M21. `curl | sudo bash` VPS install from mutable `main`.** `deploy/vps/install.sh:5,8`.
- **M22. OIDC login replay guard is per-process/in-memory** — callback replay
  possible against another replica in HA. `oidc_login.py:76,127-149`.
- **M23. Prior versions published under MIT (irrevocable fork exposure)** —
  `0.1.6` shipped to PyPI as MIT across six packages. `LICENSE:19-22`.
- **M24. Brand vs trademark/license mismatch** — README/CLI brand "Lightwork by
  Daybreak Labs"; LICENSE/TRADEMARK/CLA say "Maverick / Day AI Labs"; trademark
  policy protects only "Maverick." `README.md:5-7` vs `TRADEMARK.md`.
- **M25. Postgres DR story undefined; backup/DR is single-node cold standby only.**
  `backup.py:1-20`.
- **M26. Web search egresses full query text to Tavily/Brave/SerpAPI** (gated only
  under enterprise mode). `tools/web_search.py:247-281`.

---

## LOW

- **L1. 926 `# pragma: no cover` markers**; the live fleet-rollback path
  (`learning_rollout.py:104-131 promote_skill_live`) is excluded and degrades
  snapshot/audit failures to "proceed cautiously."
- **L2. Known-gap detection tests committed as `xfail`** encoding C6/H6 as accepted
  ("no layer catches this phrasing yet"). 103 skip/xfail total.
  `maverick-shield/tests/test_injection_corpus.py:152`.
- **L3. `proof_pack.collect_benchmarks` always returns `NOT_RUN`; published
  `benchmarks/MOAT_RIGOROUS_RESULTS.md` self-flags "these numbers are INVALID."**
  The "provable moat" has no valid published measurement. `proof_pack.py:154-166`.
- **L4. Companion apps are thin scaffolds** (visionos "not run on hardware,"
  desktop Tauri ~179 Rust LOC, emacs/nvim/zed/jetbrains minimal) — honestly
  labeled, but "13 apps" is mostly stubs around one dashboard + CLI.
- **L5. Product is explicitly pre-1.0 alpha** — every package `0.1.6`,
  `Development Status :: 3 - Alpha` — no API-stability commitment. `maverick-core/pyproject.toml:18`.
- **L6. `readOnlyRootFilesystem: false` in helm** (justified but no RO-root + writable
  emptyDir split for PSS-restricted clusters). `deploy/helm/.../values.yaml:80`.
- **L7. Helm chart ships no NetworkPolicy and ingress TLS defaults empty**
  (`tls: []`) despite "don't expose without TLS" docs. `deploy/helm/.../values.yaml:97-106`.
- **L8. Relay edge service logs nothing** (`log_message` no-op) — zero request/
  audit logs on an internet-adjacent forwarder. `deploy/relay/relay.py:106-107`.
- **L9. Stale demo docs advertise removed `?token=` query auth** (trains token-in-URL
  habit; the dashboard removed it to stop bearer leakage). `deploy/demo/fly.toml:10`,
  `render.yaml:10`, `cli.py:2020`.
- **L10. MCP URL-mode elicitation accepts any model-controlled https URL, no host
  allowlist** — prompt-injected model can point the user at a credential-harvest
  site. `maverick-mcp/.../server.py:1121`.
- **L11. `rust/mvk-scan-py/pyproject.toml` declares no license field** — ambiguous
  SBOM metadata for the `maverick-native` wheel.
- **L12. Operating Record / Operating capsule embeds its own verifying pubkey** —
  proves integrity, not origin (anyone can mint a key + sign). `operating_record.py:203,233`.
- **L13. Trajectory store / replay / run-share write plaintext to disk or upload
  scrub-only data to GitHub gists.** `trajectory_store.py:166`; `run_share.py:16-54`.
- **L14. Runbook doc drift** — says `/readyz` is "alias of /healthz" but code runs
  extra deep checks. `deploy/observability/runbook.md:12`.

---

## What is genuinely solid (so effort can be scoped)

- **Audit:** real Ed25519 + SHA-256 per-row signatures, hash-chain + cross-file
  anchor ledger, truncation/torn-write defense, independent Rust verifier, key
  rotation preserving history, fail-closed `verify_chain`.
- **Identity:** OIDC asymmetric-only alg allowlist (defeats alg-confusion), required
  exp/iat/aud/iss/sub, JWKS-by-`kid`, no fail-open. Dashboard bearer uses
  constant-time `hmac.compare_digest`; CSRF same-origin fail-closed; loopback
  trust has DNS-rebind + proxy-forward defense; RBAC covers all 37 mutating routes.
- **Sandbox container backends:** `--cap-drop ALL`, `no-new-privileges`, non-root,
  `--network=none`, memory/pids caps, seccomp RuntimeDefault; single `shell=True`
  chokepoint; SQL parameterized; DuckDB external-access disabled; no pickle/yaml.load/eval.
- **Learning lifecycle is real, not theater:** dreaming (lexical clustering + atomic
  NDJSON + snapshot/rollback), hindsight, evolve (real fitness hill-climb that
  subprocess-runs the agent vs ground truth). Zero theater patterns found on the
  learning surface.
- **Telemetry: clean** — no vendor phone-home enabled by default; all telemetry
  subsystems local-only/opt-in; the donate-upload path isn't even implemented.
- **Supply chain (release side):** OIDC trusted publishing (no stored tokens),
  cosign keyless wheel signing, SHA-pinned third-party Actions, blocking pip-audit
  + bandit + license + detect-secrets gates, non-root container.

---

## Top 10 to unblock a regulated deployment (priority order)

1. Complete the Postgres backend (methods + schema parity + at-rest) and make the
   dashboard use `open_world()` — **C1/C2/C3/C4/C5**.
2. Make protective controls default-ON (or hard-block enterprise mode without them):
   shield, egress lock, audit signing, at-rest encryption — **C7/H1/H2/H3/H4/H5**.
3. Ship the real shield engine or stop marketing the regex fallback as the product —
   **C6/H6/H7/H8**.
4. Make the default sandbox a container; verify/sign plugins before load — **C8/C9**.
5. Emit success-path `GOAL_*/TOOL_*/EPISODE_*` to the signed chain (or sign
   world-model rows) — **C10/H28**.
6. Add outbound-prompt PII redaction + provider region/ZDR controls + fill the
   subprocessor/DPA disclosure — **C11/C12/C14**.
7. Fix probes to hit `/healthz`, add graceful drain + PDB/HPA/NetworkPolicy — **H11/H12/H13**.
8. Move job queue / audit log / rate limiter / webhook dedup to a shared store —
   **H14/H15/H16/H17**.
9. Commit lockfiles, cap/​scan deps (incl. LGPL), sign native artifacts, add
   dependabot, ship a NOTICE file — **H18–H23**.
10. Audit-data SoD: role separation for read/delete, signed retention markers,
    KMS-held signing key — **M11/M12/M13/H29**.

---

## Remediation status (as of this session)

This audit was a point-in-time snapshot; a large share of it has since been
remediated. Re-verify the cited `file:line` before acting on any item — several
were fixed by concurrent work and are no longer accurate.

### Shipped / merged or in review

- **Postgres/HA backend:** method parity, schema parity (migration ladder
  extended), at-rest sealing (**C4**), temporal `fact_history`, dashboard uses
  `open_world()` (**C2**), backend-agnostic `/healthz`+`/metrics` ping — **C1/C2/C3/C4** addressed.
- **Compliance/privacy:** success-path `GOAL_*/TOOL_*/EPISODE_*` events to the
  signed chain (**C10**), approval-decision integrity events (**H28**),
  outbound-prompt PII redaction (**C11**), provider residency/ZDR headers (**C12**),
  signed retention markers (**M13**), KMS/env-injected audit signing key (**H29**),
  audit-endpoint RBAC + auditor read-only role (**M11/M12**).
- **HA shared-store cluster correctness:** OIDC replay (**M22**), webhook dedup
  (**H17**), goal-creation rate limit (**H16**) all moved to the shared store.
- **Reliability/deploy:** graceful drain (**H12**), helm HPA + Dockerfile
  healthcheck/digest hook (**H13/M6**); probes already hit `/livez`+`/readyz`,
  PDB/NetworkPolicy/ServiceMonitor already shipped (**H11/H13/M1**).
- **Security:** outbound webhooks held to the egress lock (**H27**), MCP
  elicitation host allowlist (**L10**), REST-connector SSRF redirect pin (**M10**),
  plugin content-hash integrity lock (**C9**).
- **Config/ops:** startup config validation (**M5**), uvicorn JSON logs (**M4**),
  `maverick serve` structured logging (**M3**), tenant-world LRU eviction (**M7**),
  PG pool opt-in (**M8**), SBOM-on-release + VPS pin warning (**M19/M21**).
- **Supply chain / docs:** dependabot (**H21**), THIRD-PARTY-NOTICES (**H23**),
  Postgres DR docs (**M25**), rust license field (**L11**), runbook `/readyz`
  correction (**L14**), constitutional invalid-rule logging (**M15**).

### New findings beyond the original 83 — found by deeper sweeps, fixed

Multi-pass sweeps (concurrency/data-integrity, API/auth, multi-tenancy,
budget/RBAC, logic-correctness, sandbox/event-loop, channels, gRPC/federation/
MCP, file/path, relay/desktop/SDK) surfaced real bugs the original passes
missed. Each was verified against the code (and against real PostgreSQL where
relevant) before fixing, with non-vacuous tests:

- **Cross-tenant data leaks (Postgres, RLS-off default — the highest-value
  find).** `answer()` cross-tenant write, `recent_event_contents()` /
  `erase_conversations()` cross-tenant read/delete, plus an exhaustive
  method-by-method scoping audit that hardened the FK readers
  (`artifacts_for_goal` / `share_links_for_goal` / `signoffs_for_goals` /
  `origin_status_counts`) at the DB layer. External vector stores
  (chroma/qdrant/weaviate) isolated per-tenant by collection.
- **RBAC gaps:** goal mutators (`answer`/`retitle`/`reparent`) gated on
  ownership but not the `operate` role; `/agents/{name}/validate` and
  `/redact/preview` were unauthenticated.
- **Concurrency/data-integrity:** Postgres per-key write races (artifact
  version, fact-history window) → advisory locks; the SQLite cross-process
  analog (artifact version) → atomic single-statement insert; Postgres schema
  migration race across replicas → `pg_advisory_xact_lock`.
- **Reliability/security:** unbounded `git` calls in the GitHub webhook handler
  (process hang) → time-boxed; async-compaction pending queue uncapped → bounded;
  WhatsApp / model-proxy / dashboard-template error responses leaked internal
  detail → scrubbed/generic.
- **Verified clean (filtered out, not churned into PRs):** budget enforcement,
  logic-correctness in the safety gates, gRPC/federation/MCP authz, file/path/
  upload/installer handling, Tauri/desktop/TS-SDK, the relay edge service, the
  knowledge store (per-tenant path). ~40–50% of agent-reported "findings" were
  false positives dismissed on inspection.

### Backlog — deferred by decision (need product / business / infra input)

These are not blind code fixes; each needs an owner decision and is left for
explicit prioritization:

- **H1–H4 — secure-by-default posture (THE top remaining blocker).** Every
  protective control still ships OFF (shield, egress lock, audit signing,
  at-rest encryption, consent gate, OIDC, tenancy, Postgres RLS). The enterprise
  *preflight* (`MAVERICK_REQUIRE_ENTERPRISE=1`) hard-gates startup when the
  boundary isn't satisfied, but there is no single "turn the boundary ON" switch
  and the defaults stay permissive. Flipping defaults is a posture decision
  (breaks local/dev UX) — but it is the item a regulated buyer flags first.
- **C6 — ship/license the real "Shield" engine.** The marketed F1-0.988 SDK does
  not ship; the builtin regex fallback loads instead. Product/legal decision:
  build, license, or stop marketing the fallback as the product. (Bypasses in
  the fallback were separately hardened.)
- **C8 — container-by-default sandbox.** Making the default sandbox a container
  is a breaking behavior change (pure-local dev without Docker stops working).
  Needs a product call on the default posture vs. the enterprise opt-in that
  already exists (`require_container`).
- **C5 — Postgres-backed multi-tenancy.** Today tenancy is SQLite-file-per-tenant;
  Postgres scales horizontally but isn't the per-tenant store. Unifying them is a
  significant architecture project (per-tenant isolation model on a shared DB).
- **H20 — sign/notarize native artifacts.** PyInstaller cosign + Tauri
  notarization require an Apple Developer Program membership and signing
  identities — an infra/credential provisioning task, not a code change.
- **M16 — verify the LLM pricing table.** The budget-cap rates carry an
  "unverified" TODO; correcting them needs authoritative current vendor pricing,
  not a code edit.
- **M23 / M24 — prior MIT release exposure & brand/trademark mismatch.** Legal /
  brand decisions (irrevocable fork exposure from the `0.1.6` MIT publish;
  "Lightwork by Daybreak Labs" vs. "Maverick / Day AI Labs" naming).

### Larger items still open (tractable, not yet scheduled)

- **H1–H4 / secure-by-default posture** — flipping controls to default-ON (or
  hard-gating enterprise mode without them) is partially addressed by the
  enterprise preflight; a full default-ON flip is a posture decision.
- **H14/H15 — job queue & audit log shared/multi-host store** (the audit log is
  host-local NDJSON by design; a multi-writer chain is a larger design).
- **H28 (row-level signing)** beyond approvals; **M2** metrics-surface unification.
