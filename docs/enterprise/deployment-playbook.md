# Enterprise Deployment Playbook

A step-by-step runbook for standing up Maverick for an enterprise customer:
what to **collect from them**, what to **provision**, how to **install**, how to
**harden**, how to **verify**, and how to **operate** day-2. Every command and
config key below is real; anything not yet implemented is called out explicitly
in [§10 Known gaps](#10-known-gaps-to-track).

> TL;DR ordering: **decide the shape → collect inputs → provision deps →
> install → harden (do not skip §6) → provision tenants → verify → operate.**

---

## 1. Decide the deployment shape

| Question | Options | Drives |
|---|---|---|
| Who runs it? | Customer self-hosts **(recommended)** / we host | Data boundary, sub-processor list |
| Tenancy | One instance **per customer** (recommended) / shared multi-tenant | Channels, OIDC, isolation model |
| State backend | SQLite (1 replica) / **Postgres** (scale, HA, RLS) | Replica count, backups |
| Trust of agent-run code | Trusted ops only / **untrusted/multi-tenant** | Sandbox backend (§6.1) — **blocker if wrong** |
| LLM | Cloud (Anthropic/OpenAI/…) / **self-hosted** (vLLM/Ollama/TGI) | Egress lock, data residency |
| Auth | Dashboard token / OIDC SSO / reverse-proxy | What you collect from their IdP |

**Recommended enterprise default:** one instance per customer, Postgres backend,
self- or cloud-LLM per their data policy, OIDC SSO, **container sandbox**,
enterprise mode ON. Distinct per-tenant bot/IdP identities require
one-instance-per-tenant (the inbound listener/issuer is what identifies the
user) — the Helm chart + per-tenant config overlay make that cheap.

---

## 2. Collect from the customer ("I need this from them")

Hand the customer this checklist. ☐ = required, ◇ = optional/feature-dependent.

### 2.1 LLM access (one path required)
- ☐ **Cloud key** for their chosen provider → env var, stored as a secret:
  `ANTHROPIC_API_KEY` | `OPENAI_API_KEY` | `GEMINI_API_KEY` | `OPENROUTER_API_KEY`
  | `MOONSHOT_API_KEY` | `DEEPSEEK_API_KEY` | `XAI_API_KEY`
- ◇ **OR self-hosted endpoint** (for data residency / air-gap):
  `VLLM_BASE_URL` | `TGI_BASE_URL` | `OPENAI_COMPATIBLE_BASE_URL`, or
  `[providers.ollama] base_url`.

### 2.2 Identity / SSO (if dashboard is exposed to humans)
From their IdP (Okta/Entra/Auth0/Google):
- ☐ Issuer URL → `MAVERICK_OIDC_ISSUER`
- ☐ Audience / client_id → `MAVERICK_OIDC_AUDIENCE`
- ☐ JWKS URI → `MAVERICK_OIDC_JWKS_URI`
- ◇ For browser login: `MAVERICK_OIDC_CLIENT_ID`, `MAVERICK_OIDC_CLIENT_SECRET`,
  redirect `https://<dashboard-host>/auth/callback`, and a random
  `MAVERICK_OIDC_SESSION_SECRET`.
- ☐ The list of admin principals → `[dashboard] admins` / `MAVERICK_DASHBOARD_ADMINS`.
- ◇ Alternative: reverse-proxy SSO — they tell you the trusted header + upstream IPs (`[auth.proxy]`).

### 2.3 Database (for scale / HA)
- ◇ A **Postgres 14+** instance (managed RDS/CloudSQL/Azure DB recommended),
  multi-AZ, automated backups w/ PITR → a DSN of the form
  `postgres://…@HOST:5432/DBNAME` (credentials from their secret store) for
  `MAVERICK_PG_DSN`. SQLite (no dependency) is fine for a single-replica
  per-customer instance.

### 2.4 Network / TLS
- ☐ A **DNS hostname** for the dashboard (e.g. `maverick.customer.com`).
- ☐ **TLS certificate** (their cert, or cert-manager/Let's Encrypt). TLS is
  terminated at their ingress/reverse proxy — Maverick assumes HTTPS in front.

### 2.5 Secrets you will generate (give them visibility, store in their secret store)
- ☐ `MAVERICK_DASHBOARD_TOKEN` — random 32+ bytes (API/remote auth).
- ◇ `MAVERICK_ENCRYPTION_KEY` — 32-byte hex/base64 (at-rest encryption).
- ◇ `MAVERICK_A2A_TOKEN`, `MAVERICK_MCP_TOKEN`, gRPC bearer — if those surfaces are exposed.
- ◇ `MAVERICK_WEBHOOK_SECRET` — if outbound webhooks are used.

### 2.6 Channels (only the ones they want the agent to listen on)
Each channel needs its own credential, e.g.: Slack (`SLACK_APP_TOKEN` +
`SLACK_BOT_TOKEN`), Telegram (`TELEGRAM_BOT_TOKEN`), Discord
(`DISCORD_BOT_TOKEN`), Email (`EMAIL_USER` + `EMAIL_APP_PASSWORD` + IMAP/SMTP
hosts), Matrix (`MATRIX_ACCESS_TOKEN`), WhatsApp/SMS via Twilio
(`TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN`) or Meta Cloud (`WHATSAPP_CLOUD_*`).
Plus the **allow-list of sender IDs** per channel. (API/dashboard-only
deployments need none of these.)

### 2.7 Optional services
- ◇ Web search key (`TAVILY_API_KEY` / `BRAVE_API_KEY` / `SERPAPI_API_KEY`).
- ◇ Vector store for RAG (`MAVERICK_QDRANT_URL`+key, Weaviate, pgvector via the Postgres DSN).
- ◇ KMS for wrapping per-tenant keys; SIEM endpoint for audit export; Sentry/OTLP for telemetry.
- ◇ Enterprise connectors (ServiceNow/Salesforce/Snowflake/…): their instance URLs + service-account creds.

---

## 3. Provision the external dependencies

1. **LLM:** confirm the key works, or stand up the self-hosted endpoint and note its URL.
2. **Postgres** (if scaling): create the DB + least-privilege role; capture the DSN.
   See `deploy/postgres/README.md`. Enable extensions if using pgvector.
3. **IdP:** register the app, set the redirect URI, capture issuer/audience/JWKS.
4. **DNS + TLS:** point the hostname at the ingress; provision the cert.
5. **Secret store:** create the secrets from §2.5 (K8s Secret, Vault, SSM, etc.).

---

## 4. Install

All targets run as the unprivileged `maverick` user (uid/gid 1000); state lives
under `/home/maverick/.maverick`.

### 4.1 Kubernetes via Helm (recommended for enterprise)
```bash
# 1. Create the secret (or reference an existing one / external-secrets)
kubectl create secret generic maverick-secrets \
  --from-literal=ANTHROPIC_API_KEY=… \
  --from-literal=MAVERICK_DASHBOARD_TOKEN="$(openssl rand -hex 32)" \
  # + MAVERICK_PG_DSN, MAVERICK_ENCRYPTION_KEY, MAVERICK_OIDC_* as needed

# 2. Install with your values (see deploy/helm/maverick/values.yaml)
helm install maverick deploy/helm/maverick -f my-values.yaml
```
Key `values.yaml` knobs: `image.{repository,tag}`, `replicaCount` (1 for SQLite,
≥3 only with Postgres), `worldModel.backend`, `persistence.{size,storageClass}`,
`secret.data.*`, `env.*` (MAVERICK_ENTERPRISE, MAVERICK_OIDC_*, MAVERICK_TENANT_BY_USER),
`ingress.{hosts,tls,annotations}`, and the `securityContext` block (already
hardened: runAsNonRoot, drop ALL caps, fsGroup, seccomp RuntimeDefault).

### 4.2 VPS / single Linux host
```bash
curl -sSL https://raw.githubusercontent.com/Day-AI-Labs/Maverick/main/deploy/vps/install.sh | sudo bash
```
Creates a dedicated `maverick` user, pipx install, a hardened systemd unit
(NoNewPrivileges, ProtectSystem=strict, memory cgroups, crash-loop limit), and a
Caddyfile reverse proxy (auto-TLS, HSTS, security headers). Then run
`maverick init` as the service user to write config.

### 4.3 Docker (single-tenant / evaluation)
```bash
docker compose -f deploy/docker/docker-compose.yml run --rm maverick init   # first run
docker compose -f deploy/docker/docker-compose.yml up -d
```

### 4.4 Other reference architectures
`deploy/reference-architectures/{ecs,fly,railway}/` — ECS uses SSM Parameter
Store secrets + EFS; Fly uses `fly secrets set` + a volume; Railway uses a
mounted volume + env vars. All pin a single writer unless Postgres is used.

## 5. First-run configuration
`maverick init` (the wizard) writes `~/.maverick/config.toml` + `~/.maverick/.env`
(0600). It collects providers, per-role models, channels, safety profile,
sandbox backend, capabilities, tenancy, retention, and enterprise toggles. For
headless/IaC, template `config.toml` and `.env` directly (or `maverick init
--from-file`).

---

## 6. Mandatory enterprise hardening

> **Do not skip this section.** Defaults favor a friendly single-user dev
> experience; an enterprise deployment must explicitly lock these down.

### 6.1 Sandbox backend — the #1 blocker
The agent runs generated code. The **code-level default is `local`, which
executes `shell=True` on the host** (`sandbox/local.py`; `_warn_local_unsandboxed`
warns once). For any deployment running untrusted/multi-tenant work this is a
**blocker**.
```toml
[sandbox]
backend = "docker"      # or "podman" / "gvisor" / "kubernetes" / "firecracker" — NOT "local"
allow_root = false
allow_network = false   # default-deny egress from agent code
workdir = "/home/maverick/workspace"
```
The container backend already drops ALL Linux caps, sets `no-new-privileges`,
`--network=none`, `--user`, and pids/memory limits. Use `gvisor` for stronger
isolation. **Verify** the running backend isn't `local` before go-live.

### 6.2 Enterprise / regulated mode
```bash
MAVERICK_ENTERPRISE=1        # or [enterprise] mode = true
```
Enforces, fail-closed: **egress lock** (LLM calls pinned to local/allow-listed
providers; cloud providers blocked before the prompt is sent), **tool egress
allow-list** (`[enterprise] allowed_hosts`), **consent fail-closed** (destructive
actions default to deny in non-interactive contexts), and **capability
enforcement** (sub-agents can't exceed their grant). Implies at-rest encryption
and capability enforcement.

### 6.3 Auth on every exposed surface
- **Dashboard:** set `MAVERICK_DASHBOARD_TOKEN` (fail-closed off-loopback) and/or
  enable OIDC (`MAVERICK_OIDC_ENABLED=1` + issuer/audience/JWKS). RBAC roles
  (admin/operator/viewer) + per-tenant role memberships gate the admin APIs.
- **gRPC API** (if exposed): set `[grpc] tls = true` with cert/key, and
  `tls_client_ca` for **mTLS**. Set `MAVERICK_GRPC_BEARER_TOKEN`. A non-loopback
  **plaintext bind is now refused** unless `MAVERICK_ALLOW_INSECURE_GRPC=1`.
- **MCP server** (if exposed): set `MAVERICK_MCP_TOKEN`, restrict
  `MAVERICK_MCP_ALLOWED_ORIGINS` to your gateway, and prefer per-agent tokens via
  the Agent Trust Plane (`[agent_trust] enforce = true`). Per-caller rate limit
  via `MAVERICK_MCP_RATE_LIMIT` (default 600/min).
- **A2A / webhooks:** `MAVERICK_A2A_TOKEN`, `MAVERICK_WEBHOOK_SECRET`.

### 6.4 Supply chain
```toml
[skills]
require_signed = true
require_signed_catalog = true
trusted_pubkeys = ["<your-org-ed25519-hex>"]
```
Unsigned skills are installable by default — lock to your org's signing keys.
For plugins, the **allowlist** (`[plugins] enabled` / `MAVERICK_PLUGINS_ALLOW`)
and **permission grants** are enforced default-deny (an ungranted permission
skips the plugin). The residual gap is in-process runtime isolation (§10), so
still restrict to a **vetted, code-reviewed** set.

### 6.5 Data protection
```bash
MAVERICK_ENCRYPTION_KEY=<32-byte hex/base64>   # at-rest AES-256-GCM
MAVERICK_AUDIT_SIGN=1                           # tamper-evident Ed25519 audit chain
```
```toml
[audit]
sign = true
[retention]
audit_days = 365      # set to the customer's retention policy
```
For shared multi-tenant DBs, enable Postgres RLS: `MAVERICK_PG_RLS=1`
(+ `MAVERICK_STRICT_TENANT_ISOLATION=1`).

---

## 7. Provision tenants

```bash
maverick tenant create acme --plan enterprise --display-name "Acme Inc" --max-daily-dollars 500
maverick tenant list                       # shows status, plan, over-quota flag
maverick tenant suspend acme               # / resume / quota acme 1000 / delete acme --purge
```
Or via the admin REST API (admin-gated): `POST /api/v1/admin/tenants`, etc. Drop
a per-tenant overlay at `~/.maverick/tenants/<id>/config.toml` for that tenant's
own provider keys, models, budget, `[channels.*]`, and `[auth.oidc]`. Plan tiers
are enforced (concurrency, `channels`, `audit_export`).

---

## 8. Verify before go-live

```bash
maverick doctor                       # env/config/provider health; non-zero on failure
maverick version                      # package + runtime versions
maverick enterprise verify            # actively proves egress lock, encryption, audit signing,
                                      #   consent, retention hold; exits non-zero if any fail
maverick compliance --strict          # maps controls to regulation; exits 1 on action_needed
                                      #   (add --framework gdpr|us|… )
maverick audit verify --all           # Ed25519 hash-chain integrity; exits 1 on break
```
HTTP probes (auth-exempt; payload redacts when a token is set):
- `GET /livez` — TCP-accept liveness
- `GET /healthz` — DB writable + provider key present + runner alive (200/503)
- `GET /readyz` — readiness (client-binding, shield, agent-trust)
- `GET /metrics` — Prometheus (`maverick_goals_total`, `maverick_cost_dollars_total`,
  `maverick_concurrent_goals`); bearer-gated when a token is set.

Wire monitoring from `deploy/observability/`: `prometheus-rules.yaml`
(MaverickDown, ConcurrencySaturated, SpendSpike, GoalFailureRate),
`grafana-dashboard.json`, and `runbook.md`.

---

## 9. Day-2 operations

**Backup / restore (per client/tenant):**
```bash
maverick backup create --out /backups/acme-$(date +%F).tgz   # consistent (SQLite online-backup API)
maverick backup info /backups/acme-2026-06-18.tgz            # manifest: client_id, schema ver, hashes
maverick backup restore /backups/acme-2026-06-18.tgz         # fail-closed on client_id/schema mismatch
```

**Upgrade:** a pre-migration snapshot is written automatically
(`world.db.pre-migration-v<N>.bak`); migrations are forward-only and CI-gated to
be online-safe for rolling upgrades. Rollback = stop → restore the snapshot →
start the prior version.

**Secret / key rotation:** API keys — edit `~/.maverick/.env` and reload (no
downtime). The audit signing key and at-rest encryption key are long-lived with
**no built-in rotation** — plan an offline re-seal if rotation is required (§10).

**Tenant offboarding (GDPR Art. 15/17/20):**
```bash
maverick dsar export --user <id> --tenant acme -o acme-export.json   # portability
maverick erase --channel <ch> --user <id>                            # right-to-erasure (re-signs chain)
maverick tenant delete acme --purge --yes                            # remove tenant data
maverick audit verify --all                                          # confirm chain still intact
```

**Retention enforcement:** `maverick retention enforce` (schedule via cron;
`--dry-run` to preview).

**Compliance scaffolds for their auditors:** `maverick ropa`, `maverick dpia`,
`maverick ai-act`, and the machine-readable `soc2` evidence collector.

---

## 10. Gap status

Honest, current state — what's now enforced in code vs. what genuinely remains.

### Closed in code
| Area | What changed |
|---|---|
| **Sandbox** | `build_sandbox` now **refuses the unsandboxed `local` backend fail-closed** under enterprise mode / `MAVERICK_REQUIRE_CONTAINER_BACKEND=1` / `[sandbox] require_container=true` (`SandboxPolicyError`). `maverick enterprise verify` reports a "Sandbox isolation" guarantee. Still set `[sandbox] backend=docker` explicitly. |
| **gRPC TLS** | A **non-loopback plaintext bind is now refused** (`TlsConfigError`) unless TLS is configured or `MAVERICK_ALLOW_INSECURE_GRPC=1` is set. Set `[grpc] tls=true` + `tls_client_ca` for mTLS. |
| **MCP rate limiting** | Per-caller sliding-window limiter (bearer/IP), `MAVERICK_MCP_RATE_LIMIT` (default 600/min; 0 disables) → 429 over cap. |
| **Plugins** | Correction: load-time **allowlist** (`[plugins] enabled` / `MAVERICK_PLUGINS_ALLOW`) **and permission-grant enforcement are real and default-deny** (`enforce_permissions=true`) — an ungranted permission *skips* the plugin. (Earlier draft mis-stated this as unenforced.) |

### Remaining (disclose to the customer / roadmap)
| Area | Gap | Interim mitigation |
|---|---|---|
| gRPC | Per-caller **rate limiting** not built in (only `max_concurrent_rpcs` + thread pool). | Enforce at the gateway; cap via Agent Trust per-agent ceilings. |
| MCP | Shared bearer grants full tool access; per-tenant gating only via Agent Trust Plane (opt-in). | `[agent_trust] enforce=true` with per-agent tokens. |
| Plugins | Granted plugins run **in-process** — no runtime syscall/network sandbox (load-time grants only). | Vet + code-review allowlisted plugins. |
| Firecracker | Silently falls back to Docker if the VM layer is unavailable. | Monitor logs; alert on fallback. |
| Keys | No **automated rotation** for audit-signing / at-rest keys. | Manual re-seal (`maverick encryption migrate`); schedule offline. |
| Billing | Metering + invoicing exist; **no payment integration** (Stripe). | Export usage; bill externally. |
| Compliance | **DPA / sub-processor / SLA templates** now ship in `docs/enterprise/legal/`; **SOC 2 Type II + penetration test require external auditors** (not code). | Engage auditor/pen-test firm; complete the templates with counsel. |

---

*Grounded in: `deploy/{helm,vps,docker,postgres,observability,reference-architectures}/`,
`packages/maverick-core/maverick/{config.py,cli.py,sandbox/,enterprise.py,deployment.py,audit/,backup.py}`,
and `packages/maverick-dashboard/maverick_dashboard/{app.py,api.py,auth.py,rbac.py}`.*
</content>
