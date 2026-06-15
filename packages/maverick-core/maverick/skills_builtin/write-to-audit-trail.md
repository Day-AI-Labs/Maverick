---
name: write-to-audit-trail
triggers:
  - log this decision
  - record to audit
  - evidence this
  - make an audit entry
tools_needed:
  - audit_append
---
# What this skill does

Writes a structured, signed audit entry capturing what was done, on what inputs, citing which sources, and at what confidence, so a later reviewer or regulator can reconstruct the decision. The goal class is "leave durable evidence": the entry is append-only and immutable, and it records the reasoning trail, not just the outcome.

# Steps

1. Assemble the entry fields before writing: action (what was decided or produced), inputs (the data and parameters used), source_refs (citations backing any factual claims), confidence (a calibrated qualitative or numeric level), and actor (which agent/role and on whose behalf).
2. Call audit_append with the structured record. Do not free-text a paragraph; use the field structure so entries are queryable and diffable later.
3. Include enough input detail to make the entry reproducible (versions, file ids, the exact question asked) but redact any secret or special-category value first — the audit log is durable and must not become a credential store.
4. Confirm the append returned a sequence id / signature reference and surface that id to the caller so the entry can be cited downstream.

# Notes

Audit entries are append-only: never attempt to edit or delete a prior entry to "fix" it — write a new correcting entry that references the original. Logging only the outcome and not the inputs/sources defeats the purpose; the point is reconstructability. Do not dump raw secrets, PANs, or special-category personal data into the trail (run redact-secrets-in-output / redact-pii-before-egress first). Confidence must be honest; an over-confident audit entry is worse than none because it misleads the reviewer who trusts it.
