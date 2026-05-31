# Pull request

<!--
Thanks for contributing to Maverick! Keep this PR small and focused.
See CONTRIBUTING.md for the dev setup and house rules.
-->

## What

<!-- One-line summary of the change. The diff shows what; this is the elevator pitch. -->

## Why

<!-- The motivation. Link the council finding, issue, or strategic gap that this closes. -->

## How

<!--
List of files touched and what changed in each. Keep it short -- reviewers can read the diff.
Only use this section to flag non-obvious design decisions or trade-offs.
-->

## Test plan

<!--
- [ ] `pytest -vvs` passes
- [ ] `maverick doctor` still healthy after changes
- [ ] If you touched the agent loop, added a FakeLLM-driven test
- [ ] If you added a tool / sink, it goes through `ctx.shield.scan_tool_call()`
- [ ] If you added a provider, the wizard catalog (`models.py`) is updated
- [ ] If you added a channel, the wizard `CHANNELS` list and `server.py` `_WIRES` are updated
- [ ] If you added a CLI command, `docs/getting-started.md` mentions it
-->

## Checklist

- [ ] **PR title is Conventional Commits** — `type:` prefix (`feat:`/`fix:`/`docs:`/`chore:`/`refactor:`/`test:`/`perf:`/`ci:`) and the subject **starts with a letter** (not a digit, quote, or backtick). The `lint-pr-title` check enforces this.
- [ ] **Tests added or updated** and `pytest -q` passes locally.
- [ ] **`ruff check .` is clean** (or run `pre-commit install` once and let it gate your commits).
- [ ] **No bare `import tomllib`** — it's 3.11+ stdlib and breaks CI on 3.10. Use the `try: import tomllib / except ModuleNotFoundError: import tomli as tomllib` fallback (see CLAUDE.md).
- [ ] **New capability → the wizard learns it.** If you added a channel/provider/sandbox/feature, `apps/installer-cli/` can enable it, or non-technical users can't reach it.
- [ ] **Safety invariants hold** (if you touched the agent loop or added a tool/sink): new tools go through `ctx.shield.scan_tool_call()`, long-running paths respect `Budget`, and all shell goes through `sandbox.exec()` (never `subprocess.run` directly).
- [ ] **Surgical change** — didn't reformat or "improve" adjacent code; matched the existing style.

## Council-flag triage

<!-- If this addresses a council review finding (architecture / security / UX / code quality
     / translator / channels / docs / tests / deployment / strategic), reference it: -->

- Council finding: ...
- Severity: ...
