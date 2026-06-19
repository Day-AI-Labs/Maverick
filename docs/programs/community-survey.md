# Annual community survey — kit

**Roadmap ref:** 2027-H2 Distribution — "annual community survey" (2028-H2
"survey v3 + retrospective" repeats it).
**Status:** kit complete; fielding the survey is the remaining operational
work. **Survey window dates: founder-set.**

One survey a year, ≤10 minutes, results published. Its analysis is designed
to pair with the shipped **UX retrospective generator**
(`packages/maverick-core/maverick/ux_retrospective.py`, run as
`python -m maverick.ux_retrospective --since --until`): the survey captures
what deployments *say*, the retrospective captures what a deployment's
world model *recorded* (goal volume/outcomes, top task verbs, channel mix,
approval friction, plus its data-driven reset worksheet). Divergence between
the two is the finding.

Privacy stance (state it on page one of the survey): anonymous by default,
optional contact field, no tracking pixels, raw responses never published —
only aggregates. This is a product whose pitch is "your data never leaves";
the survey behaves accordingly.

## Question bank

Pick ≤20 per year; keep the **core block identical year over year** so
trends are real. Scales are 1-5 unless noted.

### Core block (repeat verbatim annually)

1. How do you run Lightwork? (desktop / Docker / VPS / Kubernetes /
   air-gapped / not currently running it)
2. Which surfaces do you use? (multi-select: CLI / dashboard / channels /
   MCP server / gRPC / GitHub Action / scheduled goals)
3. Which providers do you route to? (multi-select, 12 shipped + "local
   models" + other)
4. What roles does it do for you? (free text — pairs with the
   retrospective's task-verb table)
5. How satisfied are you overall? (1-5)
6. How likely are you to still be using it in a year? (1-5)
7. What nearly made you stop, or did? (free text — the churn question)
8. What's the one thing you'd fix first? (free text)

### Rotating blocks (choose by year's focus)

- **Governance/ops:** Do you run with capability enforcement / OIDC /
  tenancy / audit signing on? (multi-select) · Has `maverick audit verify`
  / SIEM export been used in a real review? (y/n/n-a) · Retention
  configured? (y/n)
- **Safety:** Shield mode in use (SDK / built-in rules / off)? · Have you
  hit a false positive that blocked real work? (y/n + free text) · Consent
  mode you run (`ask` / auto-approve / auto-deny / dashboard).
- **Approval friction** (pairs directly with the retrospective's approvals
  section): roughly what share of approval prompts are rubber-stamps?
  (none / some / most) · Which prompt do you wish would stop asking?
  (free text)
- **Extensions:** Have you written a skill / plugin / channel / sandbox
  backend? (multi-select) · What stopped you? (free text)
- **Docs & programs:** Which docs did you actually use? (multi-select from
  the docs map) · Attended office hours / summit / a meetup? (multi-select)
  · Was it worth your time? (1-5)
- **Commercial honesty block:** Is the proprietary license a blocker for
  your org? (yes / no / it's why we can use it) — ask it plainly; the
  answer matters more than it flatters.
- **Demographics (all optional):** org size band, regulated industry (y/n),
  region, role.

## Distribution plan

- **Channels:** README banner for the window, docs-site note, office-hours
  mentions, release-notes link, ambassadors relay
  ([`ambassadors.md`](./ambassadors.md)), summit/meetup mentions. No paid
  promotion, no incentive raffles (they buy noise).
- **Window:** 3-4 weeks, dates founder-set; avoid overlapping the summit
  (survey fatigue).
- **Tooling:** any form tool meeting the privacy stance (no respondent
  tracking, exportable raw data, self-hostable preferred). _Choice:
  founder._
- **Sample-size honesty:** publish N. If N is small, say so and skip
  percentage theater (report counts).

## Analysis template (pairs with `ux_retrospective`)

Produce one report with three parts:

1. **What people said** — survey aggregates: core-block trends vs. prior
   years, top churn themes (hand-coded free text, codes published), the
   fix-first list ranked.
2. **What deployments recorded** — operators who volunteer it run
   `python -m maverick.ux_retrospective --since <window-start> --until
   <window-end>` on their own deployment and share whichever aggregate
   lines they choose (the report is markdown; sections without data say
   so). We publish our own dogfood deployment's retrospective in full.
3. **Where they disagree** — the worksheet. For each row, name the action
   taken or the reason none is:

| Survey says | Retrospective says | Divergence? | Action / owner |
|---|---|---|---|
| e.g. "approval prompts are mostly rubber-stamps" | approvals section: decided/approved/denied counts | | |
| e.g. channel X heavily used | channel mix table | | |
| e.g. dominant use case (Q4 free text) | top task verbs | | |
| e.g. satisfaction trend | goal outcome mix (success/failure) | | |

The retrospective's built-in **reset worksheet** (zero-use surfaces to cut,
friction concentrations, dominant verbs) is appended as-is — its questions
are answered from data rows, which keeps part 3 honest.

**Publication:** results within 6 weeks of close, as a docs PR; last year's
"action" column is scored publicly in the next year's report (did we do
what the survey told us?). That closing of the loop is what makes year 2's
response rate better than year 1's.
