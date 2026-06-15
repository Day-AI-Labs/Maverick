---
name: redact-pii-before-egress
triggers:
  - redact before sending
  - scrub pii
  - safe to share
  - remove personal data
tools_needed:
  - read_file
  - pii_scan
---
# What this skill does

Runs the PII detector over any payload that is about to leave the trust boundary (email, export, third-party API, ticket) and masks personal and special-category data before it egresses. The goal class is "do not leak personal data": catch names, contact details, government ids, financial account numbers, health/biometric and other special-category fields, and mask them deterministically.

# Steps

1. Read the outbound payload with read_file and identify the destination and its sensitivity tier (internal vs external vs regulated third party).
2. Run pii_scan over the full payload, including attachments and structured fields, not just the prose body. Treat free-text comment fields as high-risk because PII hides there.
3. Mask each hit with a stable placeholder (for example [REDACTED:email], [REDACTED:ssn]) so referential structure survives while the value does not. Give special-category data (health, biometric, racial/ethnic, religious, sexual-orientation) stricter handling — prefer dropping over masking when it is not needed for the purpose.
4. Emit a redaction manifest (counts by category) alongside the cleaned payload and flag for human review if any high-risk category was present, so a person decides whether egress is appropriate at all.

# Notes

Detectors miss context-dependent identifiers (an internal employee id, a rare diagnosis, a quasi-identifier combination that re-identifies someone); when the destination is external and the data is sensitive, default to human review rather than trusting a clean scan. Masking preserves length/format only for readability — never reversibly encode the original value into the placeholder. This skill prepares a redacted copy; it does not itself send anything. Data minimization beats redaction: if a field is not needed for the purpose, drop it instead of masking it.
