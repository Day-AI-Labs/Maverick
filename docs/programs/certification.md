# Skill + channel certification programs

**Roadmap ref:** 2028-H1 "skill + channel certification programs".
Certification here is **mechanical, not ceremonial**: a listing is
"certified" exactly when it passes the shipped gates below, and the gates
are runnable by anyone — the program is the publication of the bar, not a
committee's taste. Operating the program (reviewing submissions, issuing
badge rows) is a maintainer act; every check is already in the tree.

## Skill certification — the bar

A skill is **Certified** when all of:

1. **Validator-clean:** `maverick skill validate <dir>` exits 0 (SKILL.md
   contract, schema, examples).
2. **Moderation pass:** the marketplace moderation scan returns APPROVE
   (`python -m maverick.marketplace_moderation <dir>`) — no prohibited
   content, no secret-shaped strings, declared network use.
3. **Signed:** artifact signed and verifiable — sigstore keyless
   (`sigstore_signing.py`) or the self-hosted plugin CA (`plugin_ca.py`);
   `[skills] require_signed` installs must accept it.
4. **Donation link (if any) valid:** https + allowlisted host
   (`marketplace_donations.py`).

Re-certification: any new version re-runs all four (the gates are cheap);
a listing that starts failing is moved to "lapsed", not silently kept.

## Channel certification — the bar

A channel adapter is **Certified** when all of:

1. **Contract suite green:** the adapter passes the channel SDK contract
   tests (start/send/stop seams, `as_reply` shape — see
   `maverick_channels/base.py` and the existing adapters' test style).
2. **Allowlist posture:** refuses all senders until an allowlist or
   explicit any-authenticated opt-in is configured (the wizard's standing
   rule for channels).
3. **No raw-secret config:** credentials come from env/secret stores, never
   inline tokens in committed config (detect-secrets-scannable).
4. **Plugin matrix entry:** listed in the compatibility matrix CI
   (`plugin_matrix.py`) so a core change that breaks it is visible.

## Publication

Certified listings get a row in the marketplace with the certification
date + gate versions, and may use the "Lightwork Certified" wordmark per
TRADEMARK.md. The badge program kit ([badge-program.md](./badge-program.md))
carries the asset rules. Revocation: a security issue in a certified
listing follows SECURITY.md disclosure; certification is pulled with the
advisory, restored on the fixed version's re-pass.

## What this program is not

Not a paid gate (certification is free; sponsorship is a separate,
unrelated kit), not an exclusivity device (uncertified listings still
list, marked "community"), and not a warranty (the gates check what they
check; LICENSE's warranty disclaimer stands).
