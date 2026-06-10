# Skill of the Year — award kit

**Roadmap ref:** 2027-H2 Distribution — "Skill of the Year award" (the
2028-H2 "awards push" repeats this annually).
**Status:** kit complete; announcing the first cycle is the remaining
operational work. **Prize (if any) is a founder decision.**

An annual award for the best community-published skill. The judging deliberately
reuses the shipped marketplace machinery — the validator, the moderation
gauntlet, and the ratings ledger — so the award measures the same things the
product enforces, with no parallel bureaucracy.

## Eligibility

A submission qualifies when all hold:

- A `SKILL.md` per the schema in
  [`benchmarks/example-skills/README.md`](../../benchmarks/example-skills/README.md),
  publicly available (own repo or a catalog index entry), installable via
  `maverick skill install <source>`.
- **Passes the validator**: `maverick skill validate <path>` clean (same
  linter as the dashboard's `POST /api/v1/skills/validate`).
- **Passes moderation**: `python -m maverick.marketplace_moderation <path>`
  verdict APPROVE — no embedded secrets, no permission escalation, no
  prohibited patterns, license declared. FLAG findings must be resolved
  with the judges; REJECT disqualifies.
- Author signs off on entry (no drafting people in) and the skill respects
  [`TRADEMARK.md`](../../TRADEMARK.md).
- Not authored by the maintainer or judges (their skills are showcased,
  not awarded).
- Published or substantially updated within the award year.

## Judging rubric

Scored by a small panel (maintainer + 1-2 ambassadors per
[`ambassadors.md`](./ambassadors.md); conflicts recuse). 0-2 per row,
machine-checked rows first:

| Dimension | Signal source | 0 / 1 / 2 |
|---|---|---|
| Validator + moderation hygiene | `maverick skill validate` + `marketplace_moderation` output | gate, not scored — must pass to enter |
| Community ratings | the ratings machinery: index `rating`/`ratings_count` aggregates shown in `maverick template browse` / `maverick skill browse`, plus exported local ledgers (`maverick template ratings-export`, `marketplace_ratings.py`) | 0 = no signal; 1 = some ratings; 2 = strong rating with non-trivial count. **Caveat the judges apply:** index aggregates are self-asserted by the index (the code says so) — treat them as input, verify outliers manually |
| Usefulness | judges install it and run the trigger phrases against a real goal | 0 = doesn't trigger/help; 1 = works; 2 = clearly better than no skill on a real task |
| Craft | the SKILL.md body | clarity of steps, honest tool list (`tools_needed` matches actual use — the moderation declared-vs-used check is the floor) |
| Evidence | a replayable trace (`MAVERICK_TRACE_DIR`) or `maverick export` of the skill in action, showcase-wall standard ([`showcase.md`](../showcase.md)) | 0 = none; 1 = partial; 2 = inspectable end-to-end run |
| Safety posture | does the skill keep the runtime's guardrails (budget-aware, no consent-bypass patterns) | judges' read, reasons written down |

Ties: the higher Evidence score wins; then the panel votes.

## Cadence

| When (relative to award year) | What |
|---|---|
| Year start | Cycle announced; this doc + entry form linked |
| Rolling | Entries accepted all year (an entry is a link + the two command outputs) |
| Year end + 2 weeks | Entry freeze; machine checks re-run on every entry at the current release |
| + 4 weeks | Panel scoring; rubric sheets kept |
| + 6 weeks | Winner + up to 2 honorable mentions announced |

## What winning gets

- The award named on the docs site and in the announcement; a badge per
  [`badge-program.md`](./badge-program.md) (award tier).
- The skill featured in the example-skills catalog README and demoed at the
  next [summit](./summit-v1-virtual.md) / [office hours](./office-hours.md).
- Contributor-grade swag ([`swag.md`](./swag.md)).
- Prize beyond that: _founder decision_ (if a cash prize exists, it routes
  through the [community-grants](./community-grants.md) payment rails).

Honest framing in the announcement, every year: how many entries there
were — even if the number is three. A small first cycle reported truthfully
beats an inflated one.

## Records

Publish with the result: the rubric scores (anonymized per judge), the
machine-check outputs, and the judges list. The award must survive the same
scrutiny the audit log does.
