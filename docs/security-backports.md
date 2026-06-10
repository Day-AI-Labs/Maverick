# Security backports & the LTS safety branch

How security fixes flow to releases that aren't `main`, and what the LTS
safety branch guarantees. The tooling half lives in
`maverick/backport_tool.py` (`python -m maverick.backport_tool`).

## Policy

- **What qualifies.** A commit is backport-eligible when it fixes a
  vulnerability or hardens a safety boundary (shield chokepoints, sandbox
  mediation, capability/consent gates, secret scrubbing, audit integrity) —
  marked by `security:`/`fix(security)` in the subject or a
  `Security-Backport: yes` trailer.
- **LTS safety branch.** Each major/LTS-designated release gets a branch
  `lts/<major.minor>` that receives **safety and security fixes only** (no
  features, no refactors) for **2 years** from its cut date. Cutting the
  branch is a maintainer act:
  `git branch lts/<v> <release-tag> && git push origin lts/<v>`.
- **Cadence.** Eligible fixes are backported within 7 days of landing on
  `main`; a critical (actively-exploited) fix immediately.
- **Verification.** A backport PR must keep the LTS branch's full test suite
  green and may not bump minimum dependency versions except where the fix
  requires it (documented in the PR).

## Tooling

`python -m maverick.backport_tool`:

- `scan <since-ref>` — list backport-eligible commits on `main` since a ref
  (subject markers + trailers), with the files they touch.
- `plan <lts-branch> <since-ref>` — the eligible commits **not yet** on the
  LTS branch (by patch-id, so an already-cherry-picked fix isn't re-flagged),
  as an ordered cherry-pick plan.
- `check <lts-branch>` — CI-friendly: exit non-zero when an eligible fix older
  than the 7-day SLA is missing from the branch — the gate that keeps the
  2-year promise honest.

The tool only **reads** git history and prints plans; the cherry-picks and
pushes are the maintainer's reviewed acts.
