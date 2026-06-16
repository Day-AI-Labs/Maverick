# Encryption at rest

Maverick keeps its state under `~/.maverick`. By default that state is plaintext on
disk — fine for a personal agent, but a GDPR Art. 32 / HIPAA exposure once the agent
handles sensitive data. **At-rest encryption** seals the sensitive stores with
AES-256-GCM.

## Enable it

Off by default. Turn it on with any of:

```toml
[encryption]
at_rest = true
```

- env: `MAVERICK_ENCRYPT_AT_REST=1`
- the installer wizard ("Encrypt sensitive local stores at rest?")
- **implied by [enterprise mode](safety.md#enterprise-mode-private--sensitive-data)** —
  enabling enterprise mode enables this too.

## What gets sealed

| Store | Location | Field(s) |
|---|---|---|
| Cross-session memory | `~/.maverick/memory/**` | whole files |
| Channel conversation turns | world DB | `turns.content` |
| Persisted facts | world DB | `facts.value` |
| Per-goal agent message log | world DB | `messages.content` |
| Clarifying questions | world DB | `questions.question`, `questions.answer` |

Sealing is transparent — values are encrypted on write and decrypted on read, so
application behaviour is unchanged. A value written **before** encryption was enabled
carries no seal marker and is read back as-is, so enabling encryption is a gradual
migration, not a flag-day re-encrypt.

## Seal existing data

To seal data written *before* encryption was enabled (instead of waiting for it
to be rewritten), run:

```
maverick encryption migrate            # seal existing turns/facts/messages/questions
maverick encryption migrate --dry-run  # report how much would be sealed
```

It is **idempotent** (already-sealed values are skipped, so it is safe to re-run)
and requires at-rest encryption to be enabled first.

## Key management

Key resolution (first match wins):

1. `MAVERICK_ENCRYPTION_KEY` — a 32-byte key as hex or base64, e.g. injected from a
   KMS / secrets manager so it never touches disk.
2. `~/.maverick/keys/at_rest.key` — generated on first use, `chmod 600` inside a
   `chmod 700` directory.

**Fail-closed:** if encryption is enabled but the `cryptography` backend or the key is
unavailable, a write *errors* rather than silently storing plaintext.

**Backend:** at-rest sealing is implemented in the **SQLite** backend only. The
**Postgres** backend does not seal content at rest yet, so `open_world` **fails closed**
— selecting Postgres (`[world_model] backend = "postgres"` / `MAVERICK_WORLD_BACKEND`)
while encryption-at-rest is enabled raises `PostgresAtRestUnsupported` rather than
silently storing plaintext. Use the SQLite backend for encrypted / regulated
deployments until Postgres sealing lands (tracked in `FIXES.md`).

## Search trade-off

`messages.content` is full-text indexed (SQLite FTS5). Under encryption the index
holds ciphertext, so a plaintext query can't match it — **full-text search over
encrypted messages is disabled** (messages written before encryption stay searchable).
The `facts` substring search (`search_facts`) likewise can't match encrypted *values*;
key matches still work.

## What is *not* sealed (and why)

- **`goals.title` / `description` / `result` and `episodes.summary`** — these are read
  by the dashboard through direct SQL and rendered in its UI, so sealing them safely
  requires decrypting in every raw read path. Tracked as a follow-up; **do not assume
  they are encrypted.**
- **The audit log** (`~/.maverick/audit/*.ndjson`) — integrity comes from the Ed25519
  hash-chain plus the erase/retention tooling, which read and rewrite the NDJSON;
  encrypting it is a separate design. Secrets in audit payloads are redacted before
  write regardless.
- **Attachments** (`~/.maverick/attachments/**`) — on-disk uploaded files; only the
  metadata row lives in the DB.
- **`config.toml` / `.env`** — configuration and API keys; `.env` is already
  `chmod 600`. Protect these with filesystem permissions / full-disk encryption.

## Verify

`maverick compliance` reports the at-rest control under **GDPR Art. 32**.
