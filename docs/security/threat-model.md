# Maverick threat model (STRIDE)

This is the working threat model for Maverick. It's living: when we add
a capability, we update this doc with the new threats and mitigations.
PRs that add tools or providers SHOULD touch this file.

The model uses STRIDE: **S**poofing, **T**ampering, **R**epudiation,
**I**nformation disclosure, **D**enial of service, **E**levation of
privilege.

## Trust boundaries

```
+-----------------+        +--------------------+
| user terminal   | <----> | maverick process   |
+-----------------+        +--------------------+
                                  |
                                  v
                           +-------------------+
                           | provider API      | (Anthropic/OpenAI/...)
                           +-------------------+
                                  |
                                  v
                           +-------------------+
                           | sandbox           | (local subprocess / docker / ssh)
                           +-------------------+
                                  |
                                  v
                           +-------------------+
                           | external sites    | (browser tool, http_fetch, web_search)
                           +-------------------+
```

The user's machine is the trust boundary on the inside. The provider
API and external sites are the trust boundary on the outside. Anything
crossing those needs explicit consent or shield approval.

### Networked / multi-principal boundaries (enterprise + federated)

The single-user picture above is the default. When Maverick is deployed
as a governed service it grows three more inbound trust boundaries, each
fronted by its own authenticated, fail-closed surface:

```
                         +----------------------------+
   dashboard users  ---> | dashboard (FastAPI)        |  OIDC / proxy / session
   (browsers, OIDC)      |  - per-user owner scoping   |  cookie; RBAC; CSRF
                         +----------------------------+
   API / SDK / MCP   ---> | gRPC goal API + MCP server |  bearer / per-caller
   clients               |  - capability-attenuated    |  trust token; TLS
                         +----------------------------+
   peer Maverick     ---> | federation + A2A + channel |  Ed25519 signed
   swarms / agents       |  + marketplace federation   |  envelopes; per-peer
                         |  - Agent Trust Plane gate    |  token; pinned keys
                         +----------------------------+
                                      |
                                      v
                         +----------------------------+
   queue workers     <---| queue / dispatcher handoff  |  capability re-
   (arq/Celery)          |  (cross-host)               |  attenuated by worker
                         +----------------------------+
```

**One client per deployment.** The product contract is one tenant per
Maverick instance; client/tenant state is namespaced on disk under
`tenants/<client>/` and the dashboard owner-scopes every object. Cross-peer
and cross-user data mingling is the threat this whole layer exists to prevent.

Each of these surfaces is **off by default** and **fail-closed**: it serves
nothing until explicitly configured with credentials, and an unauthenticated
or unknown caller is refused before any work is done.

## In-scope assets

- User's filesystem (`~/.maverick/`, the project working directory).
- API keys (in `~/.maverick/.env`, chmod 600).
- Session cookies (in `~/.maverick/sessions/*.json`, chmod 600).
- Audit log (in `~/.maverick/audit/*.ndjson`, chmod 600).
- World model SQLite db (optional per-column at-rest encryption,
  `crypto_at_rest` / `tenant_kms`; AES-256-GCM, per-tenant DEK).
- At-rest / KMS key material (`~/.maverick/keys/`, mode-at-creation 0600;
  the wrapped DEK is never written unwrapped).
- Per-deployment / per-tenant client data — must never mingle across
  peers (federation) or users (dashboard owner scoping).
- Federation + A2A credentials: per-peer shared tokens, pinned Ed25519
  public keys, dashboard `session_secret`, bearer tokens.

## Out-of-scope (won't defend against)

- Local-root attackers (anyone with root on the user's box owns
  everything anyway).
- Hardware attacks (cold boot, evil maid).
- Compromised provider API endpoints — we trust the providers we
  configured to do their job. If Anthropic ships a compromised model,
  we have bigger problems.
- Compromised optional plugins — plugins run in-process; users who
  install untrusted plugins are responsible for vetting them. The
  `[plugin.permissions]` manifest section is a soft signal, not an
  enforcement mechanism (yet).

## Threats by category

> The `(Qxx)` markers below are historical roadmap dates from when this
> section was written. Several have since shipped — audit-log Ed25519
> signing, webhook HMAC with replay-bound timestamps, capability tokens,
> and at-rest encryption are all live; see the networked/multi-principal
> section for the implemented enforcement points.

### Spoofing

| Threat                                   | Mitigation                                                                  |
|------------------------------------------|------------------------------------------------------------------------------|
| Attacker impersonates the user to a channel adapter (Discord etc.) | Channel auth tokens stored chmod 600; webhook receivers HMAC-signed (Q2 26). |
| Prompt injection from a fetched URL makes the agent issue tools as the user | Shield scan of inputs; injected-content detection (Q3 26). Tool ACLs limit blast radius. |
| Subagent claims a capability it doesn't have | Capability tokens (Q4 26) make declared capabilities unforgeable.            |
| Webhook receiver believes a forged event | `X-Maverick-Signature` HMAC; `verify_signature()` helper.                    |

### Tampering

| Threat                                       | Mitigation                                                              |
|----------------------------------------------|--------------------------------------------------------------------------|
| Audit log entries get edited or deleted after the fact | Daily-rotated NDJSON, chmod 600. Audit-log signing (Q3 26) adds an Ed25519 chain. |
| Skill/plugin code is modified on disk between installs | Hash-pinned via `maverick skills install`. Signed skills (Q2 26).        |
| Browser session cookie is replayed by a third process | chmod 600 + 0o700 parent dir. Encrypted at rest (Q1 27).                 |
| World model gets corrupted mid-write       | SQLite WAL mode + autocheckpoint + `PRAGMA wal_checkpoint(TRUNCATE)` on close. |

### Repudiation

> **Tamper-evidence is opt-in.** The audit log is plain NDJSON by default;
> the rows below are only *tamper-evident* with `[audit] sign = true`
> (Ed25519 hash-chain). Even then, third-party attribution requires
> verifying with an **externally-held** pubkey — a key co-located with the
> log only detects accidental/non-privileged edits. Run `maverick audit
> verify --pubkey <hex>` to check the chain.

| Threat                                                        | Mitigation                                                  |
|--------------------------------------------------------------|--------------------------------------------------------------|
| User claims they didn't approve a destructive action           | Audit log records every consent prompt + decision + source (tamper-evident only when signing is on). |
| User claims they didn't spend $X on a run                    | Episode records `cost_dollars` + `(in,out)` tokens per call. |
| Agent took an action no one can attribute                    | Every tool call audit-logged with agent id + goal id (tamper-evident only when signing is on). |

### Information disclosure

| Threat                                                          | Mitigation                                                                       |
|------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| Tool output leaks API keys to logs                              | `secret_detector` scrubs Anthropic/OpenAI/AWS/GCP/Azure/GitHub/JWT before logging. |
| Browser tool leaks session cookies to external sites             | Cookies sent only to the origin they were captured from.                          |
| Telemetry phones home with prompt content                       | Telemetry is opt-in (Q3 26); anonymous-mode strips goal text from logs.           |
| Webhook payload leaks PII                                       | Outbound webhooks send only minimal payload; users control which events fire.     |
| Audit log readable by other local users                         | chmod 600 enforced; load refuses if perms relax.                                  |

### Denial of service

| Threat                                                       | Mitigation                                                                  |
|--------------------------------------------------------------|------------------------------------------------------------------------------|
| Runaway agent burns the user's budget                        | Hard caps on dollars / tokens / tool calls / wall-seconds; budget_status tool. |
| Agent gets stuck retrying a 401 forever                      | retry_classifier marks auth errors terminal.                                  |
| Webhook receiver hangs the run                               | Webhook dispatch is async via a daemon ThreadPoolExecutor; failures logged.   |
| Tool blocks the agent (e.g. shell command hangs)             | Sandbox timeouts; killswitch file (`~/.maverick/HALT`) aborts cleanly.        |
| Compaction balloons memory on long traces                    | Hierarchical compaction (Q2 26) + retrieval-augmented compaction (Q4 26).     |

### Elevation of privilege

| Threat                                                  | Mitigation                                                                            |
|---------------------------------------------------------|----------------------------------------------------------------------------------------|
| Plugin escapes its declared capabilities               | Plugin manifest declares permissions; tool ACLs filter at registry time.               |
| Browser tool reaches private/loopback addresses        | `http_fetch` refuses private IPs by default; `MAVERICK_FETCH_ALLOW_PRIVATE=1` opt-in.  |
| Computer-use tool drives mouse/keyboard outside scope  | Kill switch `MAVERICK_COMPUTER_DISABLE=1`; consent prompt for first session (Q2 26).   |
| Shell tool reads sensitive files (gold patches, etc.)  | Opaque-mode blocklists for benchmark contexts; tool ACLs.                              |
| Subagent gains tools the parent doesn't have           | Spawn-tools layer; tool ACLs apply at every level.                                     |

## Networked / multi-principal threats (enterprise + federated)

These cover the inbound boundaries in the second diagram: the dashboard,
the gRPC/MCP APIs, cross-instance federation (federation / A2A / channel /
marketplace), and the cross-host queue. Every mitigation below is
implemented today (not roadmap); the named mechanism is the enforcement
point.

### Spoofing

| Threat | Mitigation |
|--------|------------|
| A peer presents a copyable shared token to impersonate another swarm | Per-peer token, constant-time compared; when the Agent Trust Plane is engaged a pinned-key peer must additionally **sign** the canonical envelope with its Ed25519 key (`federation_envelope.verify_envelope` against the pinned pubkey — a self-carried pubkey is never the trust anchor). |
| Dashboard caller forges another user's identity | OIDC ID-token verification is asymmetric-only (defeats HS256/`none` alg-confusion), all of `exp/iat/aud/iss/sub` required; the browser-login session cookie is HMAC-signed (constant-time verify, expiry-enforced). |
| API/MCP caller spoofs the bearer | Constant-time bearer compare; per-caller `[agent_trust]` tokens give real per-caller identity; fail-closed when nothing matches. |

### Tampering

| Threat | Mitigation |
|--------|------------|
| A captured federation message is **replayed** at the same peer | Signed `created_at` freshness window **plus** a per-signature replay-nonce cache (federation delegate, channel federation); the cache is lock-guarded for the server thread pool. |
| An **older** signed marketplace bundle is replayed to resurrect a withdrawn (e.g. malicious) listing | Per-origin monotonic `created_at` watermark — an import must be strictly newer than the last applied from that origin (also blocks exact-replay). |
| A delegated capability grant is tampered with in transit / on the queue | gRPC and the queue worker **re-intersect** any wire-supplied capability with the receiver's own local policy (`_rpc_capability` / `_worker_capability`); a grant can only narrow, never broaden. |
| Audit chain edited after the fact | Ed25519 hash-chain with cross-file anchoring; `maverick audit verify --pubkey <externally-held hex>` is required for third-party tamper-evidence (a co-located key only catches non-privileged edits). |

### Repudiation

| Threat | Mitigation |
|--------|------------|
| A node drops its half of a cross-swarm delegation | Both halves are audit-logged with a shared `correlation_id`; `audit.federation` reciprocity (`cross_verify`) detects a missing half. |
| A trust-plane denial isn't recorded | Every inbound/outbound denial lands in the audit chain (`agent_trust.record_denied`). |

### Information disclosure

| Threat | Mitigation |
|--------|------------|
| One federation peer reads another peer's (or a local) goal status/result | `GoalStatus` is owner-scoped — a goal is stamped `federation:<peer>` and only its delegating peer can poll it; anything else is reported as "unknown" (indistinguishable from non-existent). |
| One dashboard user reads another user's goals (IDOR) | Object-level `assert_goal_access` on every goal-by-id endpoint; exact owner match; denials return **404** (not 403) so existence isn't disclosed. Legacy `owner==""` rows are unreachable by authenticated non-admins. |
| A peer reads webhook/push secrets back from config | `get_push_config` masks the token; support bundles redact secret-named keys. |
| Provider session cookies readable by another local user mid-write | Written **mode-at-creation** (`os.open(..., 0600)`), closing the world-readable window the old write-then-chmod left. |
| Cross-tenant data decryption | Per-tenant DEK + AEAD context binding (`tenant_kms`); a tenant's key/ciphertext can't open another's (GCM auth fails). |
| Forwarded channel user-ids leak across peers | Pseudonymized per-peer (HMAC under a per-pair secret) before they leave the host; no secret = no forwarding. |

### Denial of service

| Threat | Mitigation |
|--------|------------|
| A deeply-nested signed envelope crashes verification (`RecursionError` in the canonical-JSON digest) before the signature is even checked | Recursion-safe depth guard rejects over-nested envelopes first (`federation_envelope._within_depth`). |
| A hostile A2A client sends a malformed `id`/`message.parts` shape to crash the task engine into a 500 | Parsers are shape-defensive: a non-string id resolves to "not found", a non-list `parts` yields empty text. A standing fuzz harness (`test_parser_fuzz`) holds the "never raises / fail-closed" contract across every untrusted-input parser. |
| An outward surface is flooded | Per-peer token-bucket rate limiting (channel federation); bounded thread pools + `maximum_concurrent_rpcs` (gRPC/federation/webhooks); SSE/WS offload + a WS concurrency cap (dashboard); A2A in-memory task store is bounded. |
| A client-supplied budget/deadline bypasses caps | Clamped down to operator ceilings (A2A `_limits`, federation `clamp_budget`); budget caps are enforced at record time, never bypassed. |
| ReDoS via adversarial text on the scanning surfaces | Secret-detector / shield regexes are anchored (verified <0.15s on 100 KB adversarial inputs). |

### Elevation of privilege

| Threat | Mitigation |
|--------|------------|
| A peer obtains authority the receiver wouldn't grant | Delegations are **narrow-only**: the peer's requested tools intersect the receiver's local grant; the trust registry ceiling tightens it further; `negotiate_boot` refuses a delegation it can't fully equip. |
| A queue worker honors an over-broad grant placed on the queue | The worker re-attenuates by its own local policy when enforcement is on (zero-trust across the queue boundary). |
| A tool escapes the workspace via a symlink swapped after the path check (TOCTOU) | File tools verify containment **through the opened descriptor** (`/proc/self/fd`), immune to a post-check swap; writes `O_CREAT` without `O_TRUNC`, verify, then write — an escaped file is never truncated. |
| An MCP/connector tool defaults to an under-restricted risk | Unclassified + MCP tools default to **high** risk; the capability `max_risk` ceiling drops over-risk tools at registry time; tool-ACL fails **closed** for restricted principals on a config-read error. |
| An external surface served unauthenticated | Federation/A2A/MCP-HTTP all require credentials and refuse to start/serve without them; a client-bound deployment refuses to serve unbound (`require_client_binding`). |

## Threat-model review cadence

- Reviewed at every minor release.
- Reviewed when a new tool, provider, sandbox, or channel ships.
- External penetration tests planned for Q3 2027 and Q3 2028.
