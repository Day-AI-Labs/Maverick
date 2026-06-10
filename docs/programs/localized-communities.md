# Localized communities (top 5 non-English) — kit

**Roadmap ref:** 2028-H2 "localized communities (top 5 non-English)".
The repo-side halves are real: nine human-translated doc sets
([docs/i18n/](../i18n/)), the docs MT pipeline (`maverick.docs_i18n`), the
dashboard i18n portal (UI strings), and the RTL support. Chartering and
sustaining the communities is a people act this kit makes repeatable.

## Picking the five

Don't guess: rank by (a) community-survey language demographics, (b)
docs-i18n traffic once published, (c) presence of a willing **local lead**
(an ambassador — [ambassadors.md](./ambassadors.md) — who actually speaks
the language). A language with demand but no lead waits; a lead with
energy but thin demand gets a "channel + office-hours slot" trial, not a
full charter. The nine translated languages are the natural candidate
pool; the survey decides.

## What a chartered community gets

1. **A channel** (Discord section or equivalent) named for the language,
   not the country; CODE_OF_CONDUCT.md applies, with the local lead as
   first-line moderator and the global contact as escalation.
2. **The docs set in their language** — current translations plus a
   standing translation lane: UI strings via the i18n portal scaffold,
   docs via PRs following `docs/i18n/README.md`'s header/staleness
   contract (MT drafts from the pipeline are acceptable starting points,
   human review required before merge).
3. **A localized office-hours slot** ([office-hours.md](./office-hours.md)
   format) in a timezone that actually fits, hosted by the lead.
4. **Meetup standing** — the meetup playbook applies as-is
   ([meetups.md](./meetups.md)); localized-community meetups count toward
   the regional program.

## What stays global

Security reporting (SECURITY.md, English), the roadmap + voting (one
backlog, not five), releases and advisories (translated summaries welcome,
the English advisory is authoritative — the same "English is
authoritative" rule the translation headers already carry).

## Health check (per community, quarterly)

Active lead? Channel answers beat tumbleweed (median first-response < 48h)?
Translation lane moved (any doc PR or portal catalog update)? Two
consecutive failing quarters → fold the channel back to a language thread
in the global space, thank the lead, and say so publicly — a closed
community handled honestly beats a zombie one.
