# University outreach — 5-partnership kit

**Roadmap ref:** 2027-H1 Distribution — "university outreach (5 partnerships)".
**Status:** kit complete; sending the emails and signing the agreements is the
remaining operational work. **The license grant to each partner is a founder
decision** (see the IP note at the bottom — Maverick is proprietary, so a
partnership *requires* a written educational/evaluation license).

Goal: 5 active partnerships where a course, lab, or capstone program does a
semester of real work on or around Maverick. "Real work" means code, evals,
or formal analysis that survives contact with CI — not a logo exchange.

## Target-profile rubric

Score each candidate institution/lab 0-2 per row; pursue the top scorers.
Aim the 5 partnerships at *different* profiles (one systems lab, one
security lab, one SE/agents course, etc.) so the project menu gets coverage.

| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| Course/lab fit | No systems/SE/security/AI-agents teaching | Adjacent course exists | A course or lab whose existing syllabus maps onto the project menu below |
| Faculty contact | Cold | Second-degree intro available | Warm contact or prior interaction with the project |
| Student level | Intro-level only | Mixed | Upper-division / grad students who can work in a 680+-test Python codebase |
| Project cadence | No project component | Optional projects | Mandatory semester project or capstone with deliverables and grading |
| IP posture | University claims all student IP, no flexibility | Negotiable | Standard practice allows the CLA + license structure below |
| Infrastructure | Students lack machines/keys | Partial | Lab can provision API keys or local models (Ollama is a supported provider — students don't need paid keys) |

Disqualifiers regardless of score: a partner that requires Maverick be
relicensed open source, or that cannot accept the CLA structure for upstream
contributions.

## Outreach email templates

Plain text, short, no marketing language. Send from the maintainer, not a
no-reply address. _Sender name/contact: founder._

### Initial email

```
Subject: Semester projects on a production multi-agent runtime (Maverick)

Hi <name>,

I maintain Maverick, a proprietary self-hosted multi-agent runtime
(recursive agent swarm, hard budget caps, sandboxed execution, signed
audit log — ~2,000 tests in CI, Python 3.10-3.12). Repo:
https://github.com/Day-AI-Labs/maverick

I'm setting up a small number of university partnerships for <semester>:
your students take on scoped projects against the real codebase — new
sandbox backends, channel adapters, benchmark evaluation, red-team corpus
work, or formal verification of the sandbox interface (we already ship a
TLA+ spec they can extend). Each project is sized so a small team can land
it in a semester, and accepted work ships in the product with credit.

What we provide: a written educational license for course use (Maverick is
commercially licensed, so this is part of the agreement), a curated project
menu mapped to specific modules, code review on every PR, and an hour a
week of maintainer office hours for the cohort.

What we ask: a project slot in your course or lab, and that upstream
contributions go through our standard CLA.

Would a 30-minute call in the next two weeks work to see if there's a fit?

<name>
Maverick maintainer
```

### Follow-up (7-10 days later, once, then stop)

```
Subject: Re: Semester projects on a production multi-agent runtime (Maverick)

Hi <name>,

Following up once in case this got buried. The short version: scoped,
graded-deliverable-shaped projects on a real agent runtime, with an
educational license, a project menu, and weekly maintainer office hours
for your students.

The project menu is public if you'd like to gauge fit first:
https://github.com/Day-AI-Labs/maverick/blob/main/docs/programs/university-outreach.md

If the timing is wrong, a pointer to a colleague who runs project courses
would be just as welcome.

<name>
```

## Semester project menu

Each project is sized for a 2-4 student team over one semester, has a
testable definition of done, and names the real modules it touches. Paths
are relative to the repo root; `maverick/` means
`packages/maverick-core/maverick/`.

| # | Project | Repo area (verified) | Definition of done |
|---|---|---|---|
| 1 | New channel adapter (e.g. a campus chat system) | `packages/maverick-channels/maverick_channels/` — subclass `Channel` in `base.py`; wiring steps in [`CONTRIBUTING.md`](../../CONTRIBUTING.md) "Adding a channel" | Adapter + tests + wizard entry; messages round-trip in a live demo |
| 2 | New sandbox backend via the entry-point SDK | `maverick/sandbox/sdk.py` (`SandboxV2` protocol, `conformance()`, `maverick.sandboxes` entry-point group) | Backend passes `conformance()`, ships as a separate package, runs a real goal |
| 3 | New LLM provider adapter | `maverick/providers/` + registry in `providers/__init__.py`; steps in CONTRIBUTING "Adding a provider" | `complete()`/`complete_async()` + format-translation tests on the `FakeLLM` pattern |
| 4 | Compaction strategy research | `maverick/compaction_plugins.py` (named-strategy registry; `learned`/`multimodal`/`streaming`/`graph` ship today), `tests/test_compaction_plugins.py` | A new registered strategy + a benchmark comparison against `"heuristic"` on a fixed corpus |
| 5 | Benchmark evaluation study | `benchmarks/` — `harness.py`, `eval_gaia.py`, `eval_terminal_bench.py`, `eval_tau2.py`, `RESULTS.md` (append-only, `measured` vs `manual` rows) | Multi-seed measured rows + a written analysis; no single-run claims |
| 6 | Red-team corpus expansion | `packages/maverick-shield/maverick_shield/redteam_corpus.jsonl` (grow-by-PR; CI `redteam` job fails on missed attacks) + the `--calibrate` operating-curve sweep | ≥N new labeled attack/benign pairs (N agreed with maintainer) that survive the CI gate, + a calibration write-up |
| 7 | Formal methods: extend the sandbox TLA+ spec | `docs/specs/tla/` (`SandboxInterface.tla`, TLC-checked: 982 states) | A new safety or liveness property model-checked, or a second interface modeled (e.g. capability attenuation) |
| 8 | Skills authoring + evaluation | `SKILL.md` schema in `benchmarks/example-skills/README.md`; `maverick skill validate`; moderation gauntlet `python -m maverick.marketplace_moderation` | A themed skill pack that passes validator + moderation, with trigger-accuracy evaluation |
| 9 | TypeScript plugin development | `sdks/plugin-ts/` (`@maverick/plugin-sdk`, `defineTool`/`servePlugin`, NDJSON stdio protocol; host: `maverick/ts_plugin_host.py`) | A working TS tool plugin passing `python -m maverick.plugin_matrix --ci` and the moderation checks |
| 10 | Dashboard i18n for a new language | `packages/maverick-dashboard/maverick_dashboard/i18n_portal.py` (`scaffold(lang)`, `validate_catalog`) | A validated community catalog for a language the team speaks natively (feeds the localized-docs roadmap rows) |
| 11 | HCI study: approval friction | `maverick/ux_retrospective.py`, `maverick/consent_ergonomics.py`, `maverick/predictive_approvals.py` | An instrumented user study over the consent/approval UX with a written report; any code change is a bonus, the study is the deliverable |
| 12 | Security analysis: capability model | `maverick/capability.py`, `maverick/capability_boot.py`, `maverick/capability_fuzzer.py` (CI gate: 0 leaks in ~2000 probes) | New fuzzer probe families or a written attack analysis; any found leak responsibly disclosed per [`SECURITY.md`](../../SECURITY.md) |

## Evaluation rubric (per project, end of semester)

Used both for the partner's grading input and for our own go/no-go on
renewing the partnership. Score 0-2 per row.

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| Works | Doesn't run | Runs with caveats | Lands green on the full CI matrix (`lint`, `test 3.10/3.11/3.12`, `audit`, `docker`) |
| Tested | No tests | Happy path | Failure paths + the repo's house patterns (FakeLLM, sandbox-mediated shell) |
| Scoped | Sprawled or rewrote adjacent code | Mostly surgical | Surgical, matches existing style (per CONTRIBUTING house rules) |
| Honest | Claims exceed evidence | Minor over-claiming | Limitations section is accurate; benchmark claims multi-seed |
| Communicated | No write-up | Write-up exists | Write-up a maintainer could publish (and credit) as-is |

Partnership-level success after the semester: at least one project at ≥8/10,
and the faculty partner willing to run it again. Renew the ones that clear
the bar; replace the ones that don't.

## Maintainer commitment (cap it)

Per partner, per semester: a 1-hour kickoff, weekly 1-hour cohort office
hours (shared across teams), and code review on PRs. That is the whole
commitment — 5 partners ≈ 5-6 hours/week in season. If review load exceeds
this, shrink the menu, not the review depth.

## IP & licensing note (read before signing anything)

Maverick is **proprietary, commercially licensed** software
([`LICENSE`](../../LICENSE)): no use, modification, or derivative work is
permitted without written permission from the Licensor. A partnership must
therefore include, in writing:

1. **An educational/evaluation license** from the Licensor covering course
   use of the Software by the named cohort for the term — scope, duration,
   and any fee are **founder decisions** (recommendation: no-fee,
   semester-scoped, non-production, non-transferable). Without this grant,
   students cannot legally run or modify the code; do not start a cohort on
   a handshake.
2. **Contributions under the CLA.** Anything contributed upstream goes
   through the signed Contributor License Agreement
   ([`CLA.md`](../../CLA.md)), which assigns the Licensor the rights needed
   to relicense the contribution — exactly as
   [`CONTRIBUTING.md`](../../CONTRIBUTING.md) states. Confirm the
   university's IP policy permits students to sign it *before* projects
   start; this is the most common deal-breaker, hence the rubric row.
3. **Student-owned work.** Projects built against public extension surfaces
   (a separate sandbox-backend package, a TS plugin, a SKILL.md, a study or
   TLA+ analysis) are the students' own work and they keep it; running it
   *with* Maverick still requires the license in (1). Make this split
   explicit in the agreement so nobody is surprised.
4. **Trademark.** Course materials may say "built on Maverick" (nominative
   use); they may not name a course project "Maverick-anything" or imply
   official status ([`TRADEMARK.md`](../../TRADEMARK.md)).
5. **No open-source promise.** Do not promise a future open-source edition
   to close a deal — the "lite" edition is a stated possibility on the
   [roadmap](../ROADMAP.md), not a commitment, and partners must hear it
   framed exactly that way.
