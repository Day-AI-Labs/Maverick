# Maverick cookbook

End-to-end recipes you can paste into `maverick start "..."` (or into a
GitHub issue body when using the `agent-on-pr` reusable workflow).

Each recipe is:

- **Self-contained**: doesn't assume you have anything beyond a fresh
  Maverick install (`pip install maverick-agent` + `maverick init`).
- **Bounded**: ~3 minutes of agent runtime on Claude Sonnet 4.6,
  budget-capped at $1.
- **Real**: copy-paste-and-run, no placeholder TODOs in the goal text.

| Recipe | When to use |
|--------|-------------|
| [PR review](./pr-review.md)            | After pushing a branch; surface logic bugs before asking a human |
| [Dependency migration](./dep-migrate.md) | Bump a library across a major version with breaking changes |
| [Repo onboarding](./repo-onboarding.md) | First-day-on-the-job tour of a codebase you didn't write |
| [Issue triage](./issue-triage.md)      | Inbox of GitHub issues you want to label and group |
| [Research deep-dive](./research.md)    | Pick a paper / library / topic and produce a 1-page brief |
| [Flaky-test hunt](./flaky-test-hunt.md) | A test fails intermittently; find + fix the root cause (no retries) |
| [Dependency CVE triage](./cve-triage.md) | A scanner flagged a CVE; decide if it's reachable here + the safe bump |
| [CSV cleanup](./csv-cleanup.md)        | Normalize + flag a messy CSV without fabricating values |
| [Bug report → failing test](./bug-repro.md) | Turn a bug report into a minimal failing regression test (TDD step 1) |

## Quick hits (under 60 seconds)

Single-shot recipes that finish in well under a minute, budget-capped
below $1. Great for muscle-memory tasks you'd otherwise do by hand.

| Recipe | When to use |
|--------|-------------|
| [Commit message](./commit-message.md)   | Write a Conventional-Commits message for the staged diff |
| [Explain an error](./explain-error.md)  | Paste a stack trace; get the root cause + most likely fix |
| [Regex builder](./regex-builder.md)     | Describe a pattern in English; get a tested regex back |
| [Changelog entry](./changelog-entry.md) | Turn a commit range into one user-facing CHANGELOG line |
| [Docstring pass](./docstring-pass.md)   | Add/fix docstrings on one file's public functions |
| [Test naming](./test-naming.md)         | Rename vague tests to describe what they assert |
| [Env-var audit](./env-audit.md)         | Diff env vars read by code against what's documented |

## Submitting your own

PRs welcome. Criteria:

1. Self-contained: works against any reasonable repo, no
   user-specific setup.
2. Budget-bounded: < $1 on Sonnet 4.6 budget caps.
3. Documented expected output (what success looks like, what failure
   modes are common).
4. Tested at least once by the contributor against a real repo.
