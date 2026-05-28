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

## In-scope assets

- User's filesystem (`~/.maverick/`, the project working directory).
- API keys (in `~/.maverick/.env`, chmod 600).
- Session cookies (in `~/.maverick/sessions/*.json`, chmod 600).
- Audit log (in `~/.maverick/audit/*.ndjson`, chmod 600).
- World model SQLite db.

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

## Threat-model review cadence

- Reviewed at every minor release.
- Reviewed when a new tool, provider, sandbox, or channel ships.
- External penetration tests planned for Q3 2027 and Q3 2028.
