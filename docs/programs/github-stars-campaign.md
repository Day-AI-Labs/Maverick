# GitHub Stars campaign — honest growth kit

**Roadmap ref:** 2027-H1 Distribution — "GitHub Stars campaign".
**Status:** kit complete; the remaining work is doing the tactics on a
cadence. Lightweight by design.

Stars are a discovery proxy, not the goal. The goal is qualified evaluators
finding the repo; stars follow good artifacts. This kit lists what we will
and won't do, because half the available tactics are fraud-shaped.

## What we will NOT do

- **No purchased stars, bots, or star-exchange rings.** Ever. It violates
  GitHub ToS, it's detectable, and an enterprise buyer running diligence on
  a *proprietary governance product* treats fake stars as disqualifying —
  correctly.
- **No "star us to get X"** gating (docs, downloads, support, or contest
  entries conditioned on starring).
- **No misleading positioning.** The repo is proprietary, commercially
  licensed software with visible source ([`LICENSE`](../../LICENSE)). We
  never present it as open source to ride OSS discovery channels; README and
  description say "proprietary" plainly.
- **No engagement-bait posts** ("we hit N stars 🚀" content treadmill), no
  vanity milestones in the README beyond the existing badges.
- **No astroturfing** — employees/contractors posting "as users" without
  disclosure, anywhere.

## What we will do

Each tactic is an artifact that earns attention, posted where the audience
already is, with disclosure that it's from the maintainer.

| Tactic | Cadence | Notes |
|---|---|---|
| Ship-driven posts: a real feature + a replayable demo trace | When something noteworthy ships | Source: `FEATURES.md` additions; traces via `MAVERICK_TRACE_DIR`, inspectable with `maverick diag replay` |
| Engineering write-ups (the decision docs are the seed) | ~Monthly | The repo already writes honest decision memos (`docs/specs/*-decision.md`, the TLA+ sandbox verification, the WAL contention audit) — publish them where engineers read |
| Show HN / lobste.rs / relevant subreddits, posted by the maintainer as the maintainer | Per major artifact, not per minor release | One post per venue per artifact; answer every question honestly, including "why proprietary" |
| Benchmark publications | When `benchmarks/RESULTS.md` gains multi-seed measured rows worth discussing | Measured rows only; comparator caveats included (the file's own `measured`/`manual` discipline) |
| Conference talks / podcasts | Opportunistic | Same claims policy as the [press kit](./press-and-case-studies.md) |
| README quality pass | Quarterly | The README is the landing page; keep the 90-second path (`pipx install` → `maverick init` → `maverick start`) true and fast |
| Cross-link the programs | Continuous | Office hours, summit, showcase wall — every program ends with "the repo is the front door" |

## Measurement

Track monthly (a 10-minute task, one spreadsheet): stars, unique
visitors/clones (GitHub traffic API), referrer breakdown, and —the one that
matters— evaluation-license inquiries. **No public star targets**; set an
internal expectation only after 3 months of baseline. If stars rise and
inquiries don't, the campaign is reaching the wrong audience: fix the
artifacts, not the amplification.

## Who

One owner (founder or a delegate) with posting rights and the claims policy
internalized. Everything posted under a real name. Budget: $0 required;
any paid promotion is a **founder decision** and follows the same honesty
rules.
