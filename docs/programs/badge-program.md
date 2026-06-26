# "Built with Lightwork" badge program — kit

**Roadmap ref:** 2028-H1 Distribution — '"Built with Lightwork" badge
program'.
**Status:** kit complete; producing the badge SVG (blocked on the logo
assets, same gate as [`swag.md`](./swag.md)) and reviewing the first
applications is the remaining operational work.

A small, verifiable mark a project may display once it has demonstrated a
real Lightwork integration. The badge is worth something only if it's hard
to get dishonestly — so issuance rides the existing evidence machinery
(showcase wall + validator + moderation), and every badge links back to a
public registry row anyone can check.

## Badge tiers

| Tier | Who | Verification |
|---|---|---|
| **Built with Lightwork** | A project/deployment | Showcase-wall evidence standard (below) |
| **Validated integration** | Partner integrations | Already defined — the [integration-partnerships](./integration-partnerships.md) checklist; the badge is the visual for that listing |
| **Award** | [Skill of the Year](./skill-of-the-year.md) winners | That kit's process |
| **Ambassador** | Program members | [`ambassadors.md`](./ambassadors.md) |

## The badge itself (described; final art is a maintainer deliverable)

- **SVG, two variants** (light/dark), shield-style two-segment layout in
  the style of the README's existing shields.io badges: left segment the
  Lightwork mark + name, right segment the tier text (`built with` /
  `validated vX.Y` / `skill of the year <year>` / `ambassador`).
- Validated-integration badges **carry the version they validated
  against**; stale per the partnership re-validation cadence.
- Each issued badge is delivered as the SVG + a canonical embed snippet
  whose link target is the project's **registry row** (below) — not the
  Lightwork homepage — so a click verifies rather than advertises.
- No "certified by" wording on the Built-with tier; it attests use, not
  endorsement.

## Verification step (what earns it)

For the **Built with Lightwork** tier, the application is a PR adding the
project to the [showcase wall](../showcase.md), meeting its existing
qualifying bar — Lightwork load-bearing, inspectable setup, and **evidence
of a real run** (a `MAVERICK_TRACE_DIR` trace replayable with
`maverick diag replay`, or a `maverick export` of the run), secrets
redacted.

Plus the validator gate where it applies:

- **Skill-shaped projects:** the skill passes the skill validator —
  `maverick skill validate <path>` locally, or the dashboard's
  `POST /api/v1/skills/validate` endpoint (same linter) — and the
  moderation gauntlet (`python -m maverick.marketplace_moderation <path>`,
  verdict APPROVE).
- **Plugin-shaped projects:** `python -m maverick.plugin_matrix --ci` pass
  + moderation APPROVE.
- **Deployment-shaped projects** (no installable artifact): the trace/export
  evidence alone carries it.

Reviewer (maintainer or a delegated [ambassador](./ambassadors.md)) re-runs
the checks, merges the showcase row, and adds the registry row. Target
turnaround: two weeks; rejections come with the failing check named.

## Registry

One table in the docs site (maintained by PR, like the showcase wall):
project, tier, evidence link, issue date, validated-version where relevant,
status (active/stale/revoked). The badge's embed link points here. No
hosted verification service — self-host-first applies to the program
itself.

## Usage terms

The badge image is licensed for display **solely** to identify the verified
project, subject to [`TRADEMARK.md`](../../TRADEMARK.md):

- Display on the verified project's README/site/materials: permitted.
- Modifying the mark, recoloring beyond the two shipped variants, or
  compositing it into your own logo: not permitted.
- Implying endorsement, partnership (without a
  [partnership](./integration-partnerships.md)), or official status: not
  permitted.
- The badge does **not** convey any license to the Lightwork software
  itself ([`LICENSE`](../../LICENSE)) — running Lightwork still requires a
  license; the badge attests that a verified project exists, nothing more.

## Revocation

Revoked (registry row marked, embed link shows it) when: the evidence link
breaks and isn't repaired after one notice, the project no longer runs on
Lightwork, the showcase entry is removed under its curation rules, a
moderation-relevant issue surfaces (e.g. the artifact starts failing the
checks it passed), or trademark terms are violated. Stale (validated tier
only) follows the partnership re-validation cadence automatically.

## Measurement

Quarterly count: applications, issued, rejected (with failing-check
breakdown), revoked. If rejections cluster on one check, that check's docs
need work — file the issue. The program is healthy when the registry grows
slowly and every row survives a click.
