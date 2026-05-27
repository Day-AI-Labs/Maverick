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

## Submitting your own

PRs welcome. Criteria:

1. Self-contained: works against any reasonable repo, no
   user-specific setup.
2. Budget-bounded: < $1 on Sonnet 4.6 budget caps.
3. Documented expected output (what success looks like, what failure
   modes are common).
4. Tested at least once by the contributor against a real repo.
