---
name: redact-secrets-in-output
triggers:
  - scan for secrets
  - no credentials in logs
  - safe to commit
  - strip api keys
tools_needed:
  - read_file
  - secret_scan
---
# What this skill does

Runs an entropy-plus-pattern scan over any text headed for a commit, a log, a ticket, or a shared channel and strips API keys, tokens, private keys, connection strings, and card numbers before they leak. The goal class is "never commit or share a credential": catch both well-known token formats and generic high-entropy secrets, and replace them with placeholders.

# Steps

1. Read the candidate output with read_file (the diff, the log buffer, the message body) and run secret_scan over the entire text including code comments and config blocks.
2. For each hit, replace the secret value with a typed placeholder such as [REDACTED:provider-key] while leaving surrounding non-secret text intact; preserve the variable name so the code still reads sensibly.
3. Treat connection strings with inline credentials, private-key PEM blocks, and bearer values as full-block redactions — redact the whole key material, not just the prefix.
4. Emit a count of redactions by type and, if any secret was found in something about to be committed, block the commit and flag for human review rather than committing the redacted version automatically.

# Notes

Redacting only a token prefix and leaving the body is a real leak — match and remove the whole secret. High-entropy generic strings (random 32+ char values next to words like token/secret/password) must be caught even without a known provider prefix. A secret already pushed cannot be unpushed by redacting locally; if one is found in history, escalate for rotation, do not just delete the line. This skill scans and proposes a cleaned artifact; it does not perform the commit/send. False positives are cheap and acceptable; false negatives are not.
