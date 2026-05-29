# Starter goals

Ten curated, runnable goals to bootstrap new users. Each is ~3 minutes
of agent runtime on Claude Sonnet 4.6 with a sensible budget.

Use any of these via `maverick start "<paste-the-goal>"`.

---

## 1. Code review

```
Review the most recent commit on this branch. Identify any logic bugs,
missing edge cases, or style issues. Output a numbered list of findings,
each with file:line references. Don't change any code.
```

## 2. Bug repro from issue text

```
We have a bug report: "<paste user-reported behavior>". Reproduce it
by writing the smallest failing test, then propose a fix. Don't apply
the fix yet -- show me the diff.
```

## 3. Refactor a function

```
Refactor <path/to/file.py>::<function_name> into smaller, testable
units. Preserve behavior. Add tests covering each split. Run the test
suite to verify nothing regressed.
```

## 4. Add a feature

```
Add a `--<flag>` option to `<command>` that <describe behavior>.
Update the CLI help text. Write a test that exercises the new flag.
Don't merge to main -- leave the change uncommitted.
```

## 5. Write tests for uncovered code

```
Find a file in this repo with low test coverage (use coverage.py to
identify candidates). Write tests covering the missing branches. Aim
to push coverage on that file to >=80%.
```

## 6. Research a library

```
We're considering adopting <library-name>. Read its docs, identify
its license, last release date, GitHub stars, and any unresolved
critical bugs. Compare it to <alternative>. Output a 1-page summary
with a recommendation.
```

## 7. Migrate dependency

```
We're on <library-name>==<old-version>. The latest is <new-version>.
Read the changelog, identify breaking changes, plan the migration as
a checklist, and apply non-breaking changes now. Stop and ask before
any breaking change.
```

## 8. Triage and label issues

```
Read the last 20 open issues in this repo. For each, propose a label
(`bug`/`feature`/`docs`/`question`/`good-first-issue`) and a one-line
status summary (needs-repro / clear-action / waiting-for-user / etc).
Don't apply labels -- output the list.
```

## 9. Draft a release post

```
Read the last 30 commits. Group them into themes (features / fixes /
internal). Draft a release blog post (~400 words) suitable for the
Maverick newsletter. Include a "What's next" section based on
docs/ROADMAP.md.
```

## 10. Investigate a failing test

```
Run the test suite (or just `pytest <failing-test>`). For each failure,
inspect the source, identify the root cause, and propose the minimal
fix. Don't apply yet -- summarize each failure with a recommended
action.
```

---

## Adding your own

Submit starter goals as a PR to this file. Criteria:

- Self-contained (works against any reasonable repo / project).
- Bounded scope (one focused task, not a multi-day project).
- Safe by default (no destructive ops without `ask first`).
- Honest about what success looks like.
