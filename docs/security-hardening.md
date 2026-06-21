# Security hardening (operator guide)

Lightwork ships **defense in depth**. The protective controls that don't break
the happy path are now **on by default** ([Secure by default](#secure-by-default)
— at-rest encryption, audit signing, fail-closed consent for high/critical
actions, a sane tool-risk ceiling); the rest (OIDC, egress lock, Postgres RLS,
...) stay **opt-in** so a personal install isn't forced into operational burden.
Either way the controls are easy to miss, so this guide is the single place that
lists every one — what it does, the exact `~/.maverick/config.toml` block, the
environment-variable equivalent, the installer-wizard toggle (if any), gotchas,
and how to confirm it's actually on.

> **Precedence.** For every toggle below: a mandatory compliance floor wins over
> an explicit code arg, which wins over an environment variable, which wins over
> `~/.maverick/config.toml`, which wins over the secure-by-default posture. A few
> controls (capabilities, encryption-at-rest) are additionally **implied by
> enterprise mode** — see [Enterprise mode](#enterprise-mode-the-umbrella-switch).

> **Verify what's on.** `maverick soc2` prints a JSON posture snapshot of the
> main toggles (capabilities, tenant isolation, quotas, OIDC, encryption-at-rest,
> DSAR) plus audit-log verification. Use it after any change. See
> [Verifying your posture](#verifying-your-posture).

## Contents

- [Always-on safety (not opt-in)](#always-on-safety-not-opt-in)
- [Secure by default](#secure-by-default)
- [Enterprise mode (the umbrella switch)](#enterprise-mode-the-umbrella-switch)
- [Capability enforcement](#capability-enforcement)
- [Role-based access control (RBAC)](#role-based-access-control-rbac)
- [Multi-tenancy (per-user isolation)](#multi-tenancy-per-user-isolation)
- [Usage quotas](#usage-quotas)
- [OIDC SSO authentication](#oidc-sso-authentication)
- [OIDC browser login (built-in)](#oidc-browser-login-built-in)
- [Reverse-proxy SSO](#reverse-proxy-sso)
- [Encryption at rest](#encryption-at-rest)
- [Risk-proportional verification](#risk-proportional-verification)
- [Audit-log signing (tamper-evidence)](#audit-log-signing-tamper-evidence)
- [Compliance commands](#compliance-commands)
- [Verifying your posture](#verifying-your-posture)
- [Recommended enterprise baseline](#recommended-enterprise-baseline)

---

## Always-on safety (not opt-in)

These are on by default and need no configuration. They are the floor the
opt-in controls build on:

- **Agent Shield** — the safety detection layer (`packages/maverick-shield/`).
  Fail-open with a warning if not installed; it's a chokepoint, not a hard
  dependency.
- **Sandbox-mediated shell** — all tool shell execution goes through
  `sandbox.exec()` (local/Firecracker backends), never raw `subprocess`.
- **Hard `Budget` caps** — every long-running path respects a per-run budget
  (`budget.check()`); a single run cannot spend without bound.
- **Append-only audit log** — every notable action is written to an
  append-only NDJSON audit log; when [signing](#audit-log-signing-tamper-evidence)
  is enabled it becomes an Ed25519 Merkle-chained, tamper-evident log.
- **Tool ACLs / risk ceilings** — allow/deny tool lists and a per-deployment
  max-risk ceiling (`maverick.safety.tool_acl`).
- **Consent / HITL** — human-in-the-loop confirmation gates for sensitive or
  destructive actions.

Most of the sections below are now **on by default** (next section); the rest you
**explicitly turn on**.

---

## Secure by default

The protective controls that don't break the happy path ship **on by default**.
No configuration is needed for a hardened baseline; you opt *out* if you want the
old behaviour. On by default:

| Control | Default-on behaviour | Opt out |
|---|---|---|
| [Encryption at rest](#encryption-at-rest) | seals sensitive stores; key auto-generates | `[encryption] at_rest = false` |
| [Audit-log signing](#audit-log-signing-tamper-evidence) | Ed25519 tamper-evidence; key auto-generates | `[audit] sign = false` |
| Fail-closed consent | high/critical-risk actions require confirmation (not auto-approved) | per-action consent config |
| Tool-risk ceiling | caps at `high` (CRITICAL tools need an explicit raise) | set `[security] max_risk` |

Still **opt-in** (operational burden / can break a working deployment): OIDC,
the egress lock (enterprise mode), and [Postgres RLS](multi-tenancy.md#enabling-rls-safely-guided-opt-in).
The Shield stays **fail-open** (the kernel runs without it).

**Master switch.** Turn the whole posture off with:

```toml
[security]
secure_defaults = false
```

- env: `MAVERICK_SECURE_DEFAULT=0`
- **Precedence** (per control): a mandatory compliance floor > explicit code arg >
  env var > config > `secure_defaults`. So an explicit `[encryption] at_rest = true`
  always wins, and HIPAA-mode at-rest can't be turned off by `secure_defaults = false`.

**Existing installs are safe.** Sealed reads are plaintext-tolerant, so data
written before the flip is returned unchanged until rewritten; run
`maverick encryption migrate` to seal it eagerly (and **back up the auto-generated
key** — `maverick encryption backup-key --to <dir>` — losing it loses the data).

---

## Deployment profile (one named switch)

If you only remember one knob, remember this one. `profile` picks the whole
security posture by name:

- `standard` (default) — the personal / dev posture. The always-on hardened
  controls (audit signing, at-rest encryption, fail-closed consent, tool-risk
  ceiling — see [Secure by default](#secure-by-default)) stay on, but the
  egress lock and the rest of enterprise mode stay off. Right for a single user
  running against a cloud LLM on their own machine.
- `enterprise` — the regulated posture. Turns [enterprise mode](#enterprise-mode-the-umbrella-switch)
  on by default (egress lock, consent fail-closed, capabilities enforced) on top
  of the always-on controls. This is what the Helm chart and the reference
  server deployments set.

```toml
[profile]
name = "enterprise"     # or "standard"
```

```bash
export MAVERICK_PROFILE=enterprise    # env wins over config
```

Precedence is preserved: this only sets the *default* an unset control falls
back to. Any explicit knob (e.g. `[enterprise] mode = false`) and any compliance
floor still win over the profile. Because `enterprise` engages the egress lock,
make sure a local/self-hosted (or allow-listed) provider is configured, or runs
fail closed by design.

## Enterprise mode (the umbrella switch)

The fastest way to a hardened posture. Enterprise mode pins every LLM call to a
local/self-hosted provider (an **egress lock**: sensitive data physically
cannot reach a cloud API) and, as a side effect, **implies two of the controls
below**: it forces [capability enforcement](#capability-enforcement) on and
turns on [encryption at rest](#encryption-at-rest).

**config.toml**

```toml
[enterprise]
mode = true
```

**Environment variable**

```bash
export MAVERICK_ENTERPRISE=1          # set to a falsey value to force-disable
```

**Wizard toggle:** yes — "Enterprise mode (private/sensitive data)?"

**Gotchas**

- The egress lock pins LLM calls to `ollama` / `vllm` / `tgi`, or endpoints you
  allow-list under `[enterprise] local_providers`. A call routed to a known
  cloud provider raises `EgressBlocked` *before any prompt is sent*, and the
  denial is audited. Make sure you actually have a local provider configured,
  or runs will fail closed.
- `MAVERICK_ENTERPRISE` (when set to a non-empty value) wins over
  `[enterprise] mode`.
- Enterprise mode is documented in depth in
  [`docs/security/`](security/) and the enterprise module
  (`maverick.enterprise`). This guide only covers its security side effects.

> If you only want the individual controls (not the egress lock), skip this and
> turn on each control directly below.

---

## Capability enforcement

**What it does.** Gives every agent a *scoped, signed, attenuating* capability:
a grant over which tools (up to what risk), which filesystem paths, and which
network hosts it may touch. Child/sub-agents can only ever be **narrowed**
(attenuated) relative to their parent — least privilege by construction, so a
sub-agent can never exceed what its parent was granted. Off → enforcement is a
no-op and behaviour is unchanged.

**config.toml**

```toml
[capabilities]
enforce = true
```

**Environment variable**

```bash
export MAVERICK_ENFORCE_CAPABILITIES=1
```

**Scopes** (the grant is built from your existing `[security]` tool-ACL config —
the same allow/deny/max-risk knobs `maverick.safety.tool_acl` reads). The
`Capability` fields are:

| Field | Meaning | "empty" convention |
| --- | --- | --- |
| `allow_tools` | tool whitelist | empty set = **all** tools |
| `deny_tools` | subtractive deny — **deny wins over allow** | — |
| `max_risk` | risk ceiling: `"low"` / `"medium"` / `"high"` | `None` = no cap |
| `allow_paths` | fnmatch globs of filesystem paths the principal may touch | empty = **all** paths |
| `allow_hosts` | fnmatch globs of network hosts the principal may reach | empty = **all** hosts |

**Attenuation.** As a grant propagates to children: `allow_tools` intersects
(only shrinks), `deny_tools` unions (only grows), `max_risk` only tightens,
`allow_paths`/`allow_hosts` intersect, and `expires_at` is inherited (a child
never outlives its parent).

**Ed25519 signing.** Grants can be Ed25519-signed (`sign_capability` /
`verify_capability`, reusing the audit-signing key primitives) so they are
independently verifiable. Signing/verification requires the `cryptography`
package; verification returns `False` (never raises) if it's absent, so callers
that *require* verification must check for crypto first.

**Gotchas**

- A denied tool call emits a **`capability_denied`** audit event
  (`tool`, `principal`, `channel`, `user_id`) — grep your audit log for it to
  see what got blocked.
- With no `[security]` ACL configured, the root grant is all-permissive but
  still gives identity + least-privilege-on-spawn (children still attenuate).
- **Enterprise mode forces this on** regardless of `[capabilities] enforce`.

**Verify it's on:** `maverick soc2` →
`controls.capability_enforcement.status == "enabled"`.

---

## Role-based access control (RBAC)

**What it does.** Binds principals to *named roles*, where each role is a
capability scope. A principal's grant is the deployment ACL (the
[capability](#capability-enforcement) ceiling) **narrowed** by their role — so a
role can only ever *restrict*, never escalate past `[security]`. Roles fold into
the grant wherever capabilities are built, so they bite under capability
enforcement; with enforcement off they are inert.

**config.toml**

```toml
# Roles are capability scopes (same fields as a capability).
[roles.analyst]
allow_tools = ["read_file", "search", "memory"]
max_risk = "low"

[roles.operator]
deny_tools = ["shell"]
allow_paths = ["/srv/work/*"]

# Bind principals to roles. Keys are principal ids (an OIDC user maps to
# `user:<sub>`); `default` is the fallback for unassigned principals.
[role_assignments]
"user:alice" = "analyst"
"user:bob" = "operator"
default = "analyst"
```

**How it narrows.** A role routes through capability *attenuation*: `allow_tools`
intersects the ceiling, `deny_tools` unions it, `max_risk` only tightens, and
`allow_paths`/`allow_hosts` intersect. A role that lists *broader* tools than
`[security]` permits still cannot grant them — the ceiling wins, by construction.

**Gotchas**

- RBAC is opt-in: with no `[role_assignments]` the grant is exactly the ACL
  (behaviour unchanged). An unknown role name (no matching `[roles.<name>]`) is a
  no-op.
- It is a *subset* model, not additive: an "admin" role is simply one with no
  extra restrictions (it inherits the full ACL ceiling); narrower roles carve out
  less.

**Verify it's on:** roles fold into the capability grant, so the same
`maverick soc2` → `controls.capability_enforcement` signal applies; grep the
audit log for `capability_denied` to see a role's restrictions bite.

---

## Multi-tenancy (per-user isolation)

**What it does.** Namespaces Lightwork's on-disk state per *tenant* so one
tenant's data cannot leak to another. When enabled, each channel user is
isolated into their own tenant. Tenant `t`'s data lives under
`~/.maverick/tenants/<t>/...` instead of the legacy `~/.maverick/...` root.

This increment routes the **cross-session memory** store, the **usage ledger**
(quotas), and other tenant-aware stores through the tenant-aware path resolver.
(The `maverick.paths` docstring notes the world model and audit log are migrated
in follow-on increments — see *Gotchas*.)

**config.toml**

```toml
[tenancy]
by_user = true
```

**Environment variables**

```bash
export MAVERICK_TENANT_BY_USER=1      # isolate each channel user into its own tenant
# or pin a single explicit tenant for the whole process:
export MAVERICK_TENANT=acme-corp
```

**Wizard toggle:** yes — "Per-user tenant isolation?"

**Tenant derivation.** With `by_user` on, a request's tenant is
**`"<channel>:<user_id>"`** (e.g. `telegram:12345`), sanitized for safe use as
a path segment. The active tenant is resolved in order:

1. an explicit `set_tenant(...)` / `tenant_scope(...)` scope (a `ContextVar`, so
   concurrent async runs each pin their own tenant safely);
2. the `MAVERICK_TENANT` environment variable;
3. none → the shared/legacy `~/.maverick/...` root.

**Gotchas**

- With **no** tenant active, paths resolve to the legacy locations, so
  single-tenant installs are completely unchanged.
- Tenant ids become path segments: non-`[A-Za-z0-9._-]` bytes are
  percent-encoded, and an over-long id (> 200 chars after encoding) raises
  `InvalidTenantError`. Distinct ids can never collapse onto the same on-disk
  namespace.
- Per the module docstring this is an *incremental* migration: the
  most leak-sensitive store (cross-session memory) is isolated first. Confirm in
  your version which stores are routed through `maverick.paths.data_dir` before
  relying on isolation for a specific store.

**Verify it's on:** `maverick soc2` →
`controls.tenant_isolation.status == "enabled"`.

---

## Usage quotas

**What it does.** Where `Budget` caps a *single run*, quotas cap a *principal*
across runs over a rolling **UTC calendar day** — so you can do chargeback /
rate-limit spend per user or team. A persistent ledger records cumulative
dollars + input/output tokens per `(principal, day)` under the tenant-aware data
dir (`<data>/usage/ledger.json`, so it's already tenant-isolated). The module is
**fail-soft**: a ledger error logs a warning and never crashes a run; quotas
only ever *refuse*, never crash.

**config.toml**

```toml
[quotas]
enforce = true
max_dollars_per_day = 25.0       # 0 or unset = no limit on this dimension
max_tokens_per_day = 5000000     # counts input + output tokens
```

**Environment variables**

```bash
export MAVERICK_QUOTA_ENFORCE=1
export MAVERICK_QUOTA_MAX_DOLLARS_PER_DAY=25
export MAVERICK_QUOTA_MAX_TOKENS_PER_DAY=5000000
```

**Wizard toggle:** yes — "Enforce per-principal usage quotas?" (the wizard
writes starter caps of `25.0` dollars and `5000000` tokens).

**Gotchas**

- Env vars override config per field. A cap of `0` (or unset) means "no limit on
  *this* dimension"; if **both** caps are `0`/unset, nothing is enforced even
  with `enforce = true`.
- Usage is **always recorded** (even when enforcement is off) so the ledger
  accrues chargeback data — turning enforcement on later acts on history already
  collected.
- The day window is **UTC**, so it doesn't shift with the host timezone/DST.

**Verify it's on:** `maverick soc2` →
`controls.usage_quotas.status == "enabled"`.

---

## OIDC SSO authentication

**What it does.** Verifies an OpenID-Connect **ID token** (a JWT) for the
`maverick serve` / dashboard HTTP surface against a configured issuer and
audience, mapping a verified subject to the principal `user:<sub>` (which slots
straight into the capability/tenant model). When enabled, **every gated request
must carry a valid `Authorization: Bearer <jwt>` header**; a missing/invalid
token gets an opaque `401`. Off → no token is required and behaviour is
unchanged (fail-open only when disabled).

**config.toml**

```toml
[auth.oidc]
enabled = true
issuer = "https://login.example.com/"
audience = "maverick"
jwks_uri = "https://login.example.com/.well-known/jwks.json"
algorithms = ["RS256", "ES256"]   # optional; asymmetric-only, default RS256/ES256
```

**Environment variables**

```bash
export MAVERICK_OIDC_ENABLED=1
export MAVERICK_OIDC_ISSUER="https://login.example.com/"
export MAVERICK_OIDC_AUDIENCE="maverick"
export MAVERICK_OIDC_JWKS_URI="https://login.example.com/.well-known/jwks.json"
export MAVERICK_OIDC_ALGORITHMS="RS256,ES256"   # comma-separated
```

**Wizard toggle:** yes — "Enable OIDC SSO token verification?" (prompts for
issuer / audience / jwks_uri and writes the `[auth.oidc]` table).

**Exempt paths** (answer without a bearer even when OIDC is on, for load
balancers / k8s probes / OpenAPI docs):
`/healthz`, `/livez`, `/readyz`, `/openapi.json`, `/docs`, `/redoc`,
`/docs/oauth2-redirect`, `/.well-known/agent-card.json`,
`/.well-known/agent.json`. **HMAC-signed webhooks** (`/webhook/...`) are also
exempt — they carry their own shared-secret signature and are gated separately,
so OIDC does not 401 inbound webhooks.

**Gotchas**

- **Needs the optional extra.** OIDC verification requires PyJWT:
  `pip install 'maverick-agent[oidc]'` (equivalently `pip install
  'pyjwt[crypto]>=2.13.0'`). The kernel imports fine without it; you'll only hit
  the error when a token is actually verified.
- **Asymmetric-only by design.** `algorithms` is filtered to asymmetric
  algorithms (`RS*`/`ES*`/`PS*`/`EdDSA`); `none` and every HMAC alg
  (`HS256/384/512`) are hard-rejected regardless of config — this defeats the
  alg-confusion attack. A config that lists only `HS256`/`none` falls back to
  the default `["RS256","ES256"]`.
- `exp`, `iat`, `aud`, `iss`, `sub` are all **required and verified**. Signing
  keys are fetched from `jwks_uri` keyed by the token's `kid`; an unknown `kid`
  is a rejection (no fallback key). There is **no fail-open-to-authenticated**
  path — any failure raises and yields a `401`.

**Verify it's on:** `maverick soc2` → `controls.oidc_auth.status == "enabled"`
(reports `absent` if the optional module/extra isn't installed).

---

## OIDC browser login (built-in)

**What it does.** The [OIDC SSO](#oidc-sso-authentication) gate above verifies a
bearer **ID token** that *something else* obtained — great for API clients, but a
plain browser has no way to get one. The usual answer for browsers is to put an
auth proxy in front of the dashboard (oauth2-proxy, an ALB OAuth listener, your
IdP's proxy) and let it run the login. **If you can't run a proxy**, this
built-in flow has the dashboard itself drive the OAuth2 / OpenID-Connect
**authorization-code flow** (with PKCE): it redirects the browser to your IdP,
exchanges the returned code for tokens server-side, verifies the ID token (reusing
the same verifier as the bearer gate), and sets a signed session cookie. After
that, the browser is authenticated by the cookie — no bearer header needed.

> **Prefer the proxy.** The [reverse-proxy SSO](#reverse-proxy-sso) path below is
> the simpler, lower-surface option: it keeps the OAuth client secret and the
> login flow out of Lightwork entirely. Reach for this built-in flow only when
> running a proxy isn't practical.

**Off by default, fail-closed.** The `/auth/login`, `/auth/callback`, and
`/auth/logout` routes are inert (they return `404`) unless the flow is **fully
configured**; an unconfigured deployment behaves exactly as before, and the
bearer gate is untouched. "Fully configured" means OIDC is enabled **and**
`client_id` **and** `session_secret` are set **and** the authorization/token
endpoints are reachable (either an `issuer` for discovery, or both endpoints set
explicitly).

**config.toml** (extends the same `[auth.oidc]` table)

```toml
[auth.oidc]
enabled = true
issuer = "https://login.example.com/"     # used for discovery + ID-token verify
audience = "maverick"                       # your client_id / API audience
jwks_uri = "https://login.example.com/.well-known/jwks.json"

# --- browser-login (authorization-code) flow ---
client_id = "maverick-dashboard"            # the OAuth client registered for this app
client_secret = "..."                       # the OAuth client secret
redirect_uri = "https://dash.example.com/auth/callback"  # MUST match the IdP registration
session_secret = "a-long-random-string"  # pragma: allowlist secret

# Optional: skip discovery by pinning the endpoints explicitly.
# authorization_endpoint = "https://login.example.com/authorize"
# token_endpoint = "https://login.example.com/token"
```

**Environment variables**

```bash
export MAVERICK_OIDC_CLIENT_ID="maverick-dashboard"
export MAVERICK_OIDC_CLIENT_SECRET="..."
export MAVERICK_OIDC_REDIRECT_URI="https://dash.example.com/auth/callback"
export MAVERICK_OIDC_SESSION_SECRET="a-long-random-string"  # pragma: allowlist secret
# Optional explicit endpoints (otherwise discovered from the issuer):
export MAVERICK_OIDC_AUTHORIZATION_ENDPOINT="https://login.example.com/authorize"
export MAVERICK_OIDC_TOKEN_ENDPOINT="https://login.example.com/token"
```

**Wizard toggle:** yes — under "Enable OIDC SSO token verification?", a follow-up
"Also enable the built-in browser login flow?" prompts for the client_id/secret,
redirect URI, and session secret.

**Security model** (these are the load-bearing controls):

- **CSRF on the callback.** Each login mints an opaque `state` and stashes it in
  a short-TTL (~10 min) signed transaction cookie; the callback rejects (HTTP
  `400`) unless the returned `state` matches — *before* any token exchange.
- **PKCE (S256).** A per-login `code_verifier` is generated; its S256
  `code_challenge` is sent on the authorization request and the verifier on the
  token exchange, so an intercepted authorization code can't be redeemed.
- **HTTPS-only token exchange.** The token endpoint must be `https://` (the
  client secret is POSTed to it); a non-https endpoint is refused. Discovery is
  https-only too.
- **ID token still fully verified.** The `id_token` from the exchange is verified
  by the same `maverick.oidc.verify_oidc_token` as the bearer gate (asymmetric-
  only, `exp`/`iat`/`aud`/`iss`/`sub` required, JWKS-by-`kid`). No second,
  weaker verifier.
- **Signed session cookie.** The session cookie is HMAC-SHA256 signed with
  `session_secret` (stdlib only — no new dependency), carries `{sub, exp}`, and
  is verified in constant time with expiry enforced. It is `HttpOnly`,
  `SameSite=Lax`, and `Secure` (except on loopback for local dev). Tampered /
  expired / wrong-secret cookies are simply not authenticated.
- **Open-redirect defence.** A post-login `return_to` is honored only if it is a
  safe *local* path (starts with a single `/`, no `//`, no backslash, no control
  chars); anything else falls back to `/`.
- **No secrets in logs.** Failures log a generic reason only — never the token,
  the authorization code, the client secret, or the session value.

**Identity precedence.** When login is on, a valid `mvk_session` cookie is
accepted as the request identity (mapped to `user:<sub>`, recording
`claims.via = "session"`), sitting between any reverse-proxy header and the OIDC
bearer. Invalid/absent → falls through to the bearer path unchanged.

**Gotchas**

- The `redirect_uri` must **exactly** match what you registered at the IdP, and
  must be the dashboard's public `…/auth/callback` URL.
- Keep `session_secret` secret and stable: rotating it invalidates every live
  session (users re-login); leaking it lets an attacker forge sessions.
- This is **identity**, not network access — the dashboard's existing token /
  loopback gate still governs who may connect. The `/auth/*` routes are exempt
  from that gate (they bootstrap the session) but self-gate on full
  configuration.

---

## Reverse-proxy SSO

**What it does.** Lets a standard auth proxy in front of the dashboard
(oauth2-proxy, your IdP's proxy, an ALB OAuth listener, ...) own the browser
login, then forward the authenticated user's identity in a request header.
Lightwork maps that header to a `user:<id>` principal that flows into the
[capability](#capability-enforcement) and tenant model — browser SSO without
Lightwork hand-rolling an OAuth flow. The [OIDC](#oidc-sso-authentication) bearer
gate still serves API clients; this adds the browser path.

**config.toml**

```toml
[auth.proxy]
enabled = true
header = "X-Forwarded-User"          # the identity header your proxy sets
trusted_proxies = ["127.0.0.1"]      # peers allowed to assert it (default: loopback)
```

**Environment variables**

```bash
export MAVERICK_PROXY_AUTH=1
export MAVERICK_PROXY_AUTH_HEADER="X-Forwarded-User"
```

**Security — read this.** A forwarded header is trivially spoofable by a direct
client, so Lightwork honors it **only when the request's network peer is a
trusted upstream** (`trusted_proxies`; default loopback, since the proxy usually
runs on the same host). For this to be safe you **must**:

1. Make the proxy the **only** ingress to the dashboard (bind the dashboard to a
   loopback/private interface the proxy reaches) so nobody can connect directly.
2. Configure the proxy to **strip any client-supplied copy** of the identity
   header before it sets its own.

An explicit `trusted_proxies` list is exact — it *replaces* the loopback
default, so include loopback if you still want it. An unknown/empty peer is
never trusted (fail-closed).

**Gotchas**

- This sets *identity*, not network access — the dashboard's existing token /
  loopback gate still governs who may connect.
- The principal is `user:<header-value>`, so it lines up with `[role_assignments]`
  keys for role-based access control; the verified principal records
  `claims.via = "proxy"` so proxy-asserted identities are distinguishable from
  signed ID tokens.

**Verify it's on:** request a gated dashboard route through the proxy and confirm
access matches the forwarded user (grep the audit log for `capability_denied` to
see a role biting). Direct (non-proxy) requests must not carry a honored header.

---

## Encryption at rest

**What it does.** AES-256-GCM authenticated encryption for Lightwork's sensitive
local stores, so anyone who can read `~/.maverick` can't read its contents.
**On by default** ([Secure by default](#secure-by-default)); the key
auto-generates on first use.

**config.toml** (to **disable** on a personal box)

```toml
[encryption]
at_rest = false
```

**Environment variable**

```bash
export MAVERICK_ENCRYPT_AT_REST=0     # 1 to force-enable; 0 to force-disable
```

**Wizard toggle:** yes — "Encrypt sensitive local stores at rest?"

**Key management** (first match wins):

1. **`MAVERICK_ENCRYPTION_KEY`** — a 32-byte key as **hex or base64**, so you
   can inject a KMS-derived key without it ever touching disk.
   ```bash
   export MAVERICK_ENCRYPTION_KEY="$(openssl rand -hex 32)"   # 64 hex chars
   ```
2. Otherwise **`~/.maverick/keys/at_rest.key`** — generated on first use,
   `chmod 600`, directory `chmod 700`.

**Gotchas**

- **Scope.** Sealed: the **memory store**, the sensitive **world-DB content
  columns** (goal title/description/result, facts, turns/messages, questions,
  goal events, episode summaries/outcomes, parked approvals), and the
  **semantic-recall documents** on the chroma/pgvector backends. Run
  `maverick encryption migrate` to seal rows written before it was on. Not sealed:
  the live audit day-file (seal closed ones with `maverick audit seal`) and the
  qdrant/weaviate vector backends — see [encryption.md](encryption.md) for the
  full map.
- **Back up the key.** The auto-generated `~/.maverick/keys/at_rest.key` is the
  only way to read sealed data — escrow it with `maverick encryption backup-key
  --to <dir>`; if it's lost, the data is unrecoverable.
- **Requires `cryptography`.** With at-rest enabled but the package missing,
  `seal()` **fails closed** (raises `EncryptionUnavailable`) rather than writing
  plaintext: `pip install 'maverick-agent[audit-signing]'`.
- **Transparent migration.** Sealed blobs carry a magic header; data written
  *before* you enabled encryption is read back transparently (no flag-day
  re-encrypt). New writes are sealed.
- **Don't lose the key.** If you rely on the generated `at_rest.key`, back it up
  — losing it means losing access to sealed data. Prefer
  `MAVERICK_ENCRYPTION_KEY` from your KMS for production.
- Precedence: `MAVERICK_ENCRYPT_AT_REST` (non-empty) wins over `[encryption]
  at_rest`, which wins over enterprise mode (which **implies** at-rest on).

**Verify it's on:** `maverick soc2` →
`controls.encryption_at_rest.status == "enabled"` (enterprise mode implies it).

---

## Risk-proportional verification

**What it does.** When on, the orchestrator may **skip** the LLM self-verifier
on clearly low-risk answers (a short, prose-only reply reached without touching
any tools), spending verification only where it matters. Any coding task, any
tool use, an embedded code block/diff/edit, or a long multi-part answer falls
through to full verification. This is a *cost/latency* optimization, not a safety
control — it never weakens verification on anything non-trivial.

**config.toml**

```toml
[verification]
risk_proportional = true
```

**Environment variable**

```bash
export MAVERICK_RISK_PROPORTIONAL_VERIFY=1
```

**Wizard toggle:** yes — risk-proportional verification prompt under advanced
options.

**Gotcha.** Off by default; with it off, the orchestrator's FINAL is always
verified (subject to budget). Leave it off if you want maximal verification
regardless of cost.

---

## Audit-log signing (tamper-evidence)

**What it does.** Turns the append-only audit log into an **Ed25519
Merkle-chained, tamper-evident** log: each row is hash-chained and signed, and a
cross-file tip-ledger (`anchors.ndjson`) catches deletion/truncation of a whole
day-file. This is what makes [`maverick audit verify`](#compliance-commands)
and the `soc2` audit-chain probe meaningful. **On by default**
([Secure by default](#secure-by-default)); the signing key auto-generates. With
it off the log is append-only NDJSON but not cryptographically tamper-evident
(the probe reports `unsigned`).

**config.toml** (to **disable**)

```toml
[audit]
sign = false
```

**Environment variable**

```bash
export MAVERICK_AUDIT_SIGN=0     # 1 to force-enable; 0 to force-disable
```

**Gotchas**

- Precedence: explicit code arg > `MAVERICK_AUDIT_SIGN` env > `[audit] sign` in
  config > the secure-by-default posture (on).
- Requires `cryptography` (`pip install 'maverick-agent[audit-signing]'`).
- The signing key lives under `~/.maverick/keys/`; `maverick soc2`'s
  `audit_signing_key` probe reports whether a key is present.

**Verify it's on:** `maverick audit verify` (see below) and `maverick soc2` →
`audit_log.status == "ok"` (vs `unsigned` when signing is off).

---

## Compliance commands

| Command | Purpose |
| --- | --- |
| `maverick soc2` | Print a SOC 2 technical-posture snapshot as JSON (which controls are ON + whether the audit log verifies). Add `--json` for compact single-line output. Fail-soft: always emits JSON, exits 0. |
| `maverick audit verify` | Verify the Ed25519 hash-chain (+ cross-file tip-ledger) of a signed audit log. Exits non-zero if the chain is not intact, so it can gate CI/cron. |
| `maverick dsar export --user <id>` | GDPR Art. 15/20 (access / portability): export everything Lightwork holds for a subject as a JSON bundle. |
| `maverick erase --channel <c> --user <id>` | GDPR Art. 17 (right to erasure): erase everything Lightwork knows about a `(channel, user_id)` pair. |

**`maverick audit verify` flags:**

```bash
maverick audit verify --day 2026-06-07           # default: today (UTC)
maverick audit verify --all                      # sweep every day-file in the audit dir
maverick audit verify --tenant acme              # verify a specific tenant's audit dir
maverick audit verify --file path/to/log.ndjson  # one file (overrides --day/--all)
maverick audit verify --pubkey <ed25519-hex>     # trusted external key for real
                                                 # third-party tamper-evidence
```

> **Flags.** `audit verify` accepts `--day`, `--all`, `--tenant`, `--file`, and
> `--pubkey`. `--all` sweeps every `YYYY-MM-DD.ndjson` day-file in the audit dir
> (the anchor ledger is verified separately as the cross-file tip-ledger).
> `--tenant <t>` resolves that tenant's audit dir the same way the writer/signer
> wrote it (`~/.maverick/tenants/<t>/audit/`); the default follows the active
> tenant. `--file` pins a single file and overrides `--day`/`--all`. Without
> `--pubkey` it trusts a locally-held key and prints a warning; pass the
> externally-held pubkey for genuine third-party tamper-evidence. Exits 1 on any
> break, 0 when clean. If `cryptography` is missing the chain can't be verified
> at all, which is treated as a verification break and exits 1 — so automation
> can't pass unverifiable evidence as clean.

**`maverick dsar export` flags:**

```bash
maverick dsar export --user <user_id> \
    [--tenant <t>] \         # default: active tenant
    [--output bundle.json] \ # -o; default stdout. Written 0o600.
    [--json]                 # compact single-line JSON
```

**`maverick erase` flags:**

```bash
maverick erase --channel telegram --user <user_id> [--yes]
```

> Note: `erase` requires **both** `--channel` and `--user`; it scopes erasure to
> that one `(channel, user_id)` pair (conversations, turns, on-disk
> attachments, the conversation row, related facts/episodes, and an audit
> re-anchor). `--yes` skips the confirmation prompt.

**SOC 2 controls mapping.** The mapping of these technical controls to the SOC 2
Trust Services Criteria lives in
[`docs/compliance/soc2-controls.md`](compliance/soc2-controls.md). The
machine-readable evidence collector behind `maverick soc2` is
`maverick.soc2.collect_soc2_evidence()`.

---

## Verifying your posture

After enabling anything, run:

```bash
maverick soc2
```

It reports each main control's `status` (`enabled` / `disabled` / `absent` /
`unknown`) and the audit-chain state. The relevant keys:

| `soc2` key | Backing control |
| --- | --- |
| `controls.capability_enforcement` | [Capability enforcement](#capability-enforcement) |
| `controls.tenant_isolation` | [Multi-tenancy](#multi-tenancy-per-user-isolation) |
| `controls.usage_quotas` | [Usage quotas](#usage-quotas) |
| `controls.oidc_auth` | [OIDC SSO](#oidc-sso-authentication) (`absent` if the extra isn't installed) |
| `controls.encryption_at_rest` | [Encryption at rest](#encryption-at-rest) |
| `controls.data_subject_export` | DSAR export (`maverick dsar export`) is implemented |
| `audit_log` | audit-chain verification: `ok` / `unsigned` / `broken` / `empty` / `no_crypto` / `unknown` |
| `audit_signing_key` | whether an audit signing key is present |

Then confirm tamper-evidence end-to-end with `maverick audit verify`.

> Encryption-at-rest and risk-proportional verification have no dedicated
> `soc2` field; confirm those via your config/env (and remember enterprise mode
> implies at-rest).

---

## Recommended enterprise baseline

A sensible default for a deployment handling sensitive data. Adjust the quota
caps, OIDC endpoints, and key source to your environment.

```toml
# ~/.maverick/config.toml

# Umbrella: egress lock + implies capability enforcement + at-rest encryption.
[enterprise]
mode = true

# Least privilege per agent, with attenuating propagation to sub-agents.
# (Redundant under enterprise mode, but explicit is clearer and survives
# turning enterprise mode off.)
[capabilities]
enforce = true

# Isolate each channel user into their own on-disk tenant.
[tenancy]
by_user = true

# Per-principal daily chargeback/rate-limit caps (0 disables a dimension).
[quotas]
enforce = true
max_dollars_per_day = 25.0
max_tokens_per_day = 5000000

# Tamper-evident, Ed25519 Merkle-chained audit log.
[audit]
sign = true

# AES-256-GCM at rest for sensitive local stores (memory store today).
[encryption]
at_rest = true

# SSO for `maverick serve` / dashboard. Requires:  pip install 'maverick-agent[oidc]'
[auth.oidc]
enabled = true
issuer = "https://login.example.com/"
audience = "maverick"
jwks_uri = "https://login.example.com/.well-known/jwks.json"
# algorithms defaults to ["RS256","ES256"]; asymmetric-only is enforced.

# Optional cost/latency optimization (NOT a safety control): skip the LLM
# verifier on clearly low-risk, tool-free answers. Omit for maximal verification.
# [verification]
# risk_proportional = true
```

For production, prefer injecting the at-rest key from your KMS rather than the
generated keyfile:

```bash
export MAVERICK_ENCRYPTION_KEY="$(your-kms-fetch | xxd -p -c 32)"   # 32 bytes, hex
```

Then verify:

```bash
maverick soc2
maverick audit verify
```

**Further reading:** [`docs/compliance/soc2-controls.md`](compliance/soc2-controls.md)
(SOC 2 TSC → control mapping), the enterprise-mode docs under
[`docs/security/`](security/), and [`docs/env-vars.md`](env-vars.md) for the
full environment-variable reference.
