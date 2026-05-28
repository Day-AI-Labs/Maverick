# CLAUDE.md

Guidelines for AI coding assistants working in this repo.

## Project context

Maverick is the combination of two existing projects:

- **Maverick Agent** (Python): recursive multi-agent swarm — `packages/maverick-core/`. Optimized for long-horizon work and true multi-agent coordination.
- **Agent Shield** (JS primary; Python SDK): safety detection layer — integrated via `packages/maverick-shield/` (thin Python wrapper).

The combined product is positioned at general consumers but must perform at the level of the technical tools (OpenClaw, Hermes).

## Behavioral guidelines

### Think before coding
- State assumptions explicitly. If uncertain, ask.
- Present multiple interpretations rather than picking silently.
- Push back when a simpler approach exists.

### Simplicity first
- Minimum code that solves the problem. Nothing speculative.
- No abstractions for single-use code.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

### Surgical changes
- Touch only what you must.
- Don't "improve" adjacent code, comments, or formatting.
- Match existing style, even if you'd do it differently.
- Remove imports/variables your changes orphaned; leave pre-existing dead code alone unless asked.

### Goal-driven execution
Transform tasks into verifiable goals before implementing:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"

## Maverick-specific rules

1. **The agent kernel runs without the shield.** Tests, research, and the kernel itself never *require* `agent-shield` to be installed. The shield is a chokepoint, not a hard dependency. Fail-open with a warning.
2. **Users own model choice.** Never hard-code a model in the agent loop; read from `~/.maverick/config.toml` via `maverick.config.get_role_model(role)`. Defaults live in `maverick.llm.ROLE_MODELS` and are last-resort fallbacks.
3. **Budget caps are not optional.** Every long-running path must respect `Budget`. Don't bypass `budget.check()`.
4. **Sandbox-mediate all shell.** Never call `subprocess.run` from a tool directly; go through `sandbox.exec()` so tests can swap backends.
5. **No new top-level dependencies without a config knob.** If you add a feature (channel adapter, new provider, new sandbox), the installer wizard should be able to enable/disable it.
6. **The wizard is the source of truth for UX.** When you add a capability, also add it to `apps/installer-cli/maverick_installer/`. Otherwise non-technical users can't reach it.

## Python version compatibility

CI runs the test matrix on 3.10, 3.11, and 3.12. A few stdlib modules are 3.11+ only — using one of them unconditionally breaks CI on 3.10. This has bitten three PRs in a row with `tomllib`. The rule:

**Never `import tomllib` (or any other 3.11+ stdlib) without a fallback.** Use this exact pattern:

```python
try:
    import tomllib  # 3.11+
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]
```

`tomli` is already in the dependency graph via `maverick-agent`'s `tomli>=2.0; python_version<'3.11'` marker, so no extra install is needed. The `.github/workflows/ci.yml` `lint` job greps for bare `import tomllib` and fails the build — if you see that check fail, add the fallback.

## PR titles

The `lint-pr-title` CI check (`amannn/action-semantic-pull-request`) enforces Conventional Commits. It has failed twice on the same mistake. Two rules:

1. **Use a type prefix**: `feat:`, `fix:`, `perf:`, `chore:`, `ci:`, `docs:`, `refactor:`, `test:`.
2. **The subject after the prefix must start with a letter.** Not a digit (`feat: 2027 ...` fails), not a quote (`feat: "What ..." ...` fails), not a backtick. Lead with a word: `feat: add the 2027 ...`, `feat: add a permissions page ...`.

## Where things live

```
packages/maverick-core/        Agent kernel (the brain)
packages/maverick-shield/      Agent Shield integration (the guardrails)
apps/installer-cli/            Interactive setup wizard
apps/installer-desktop/        GUI installer (planned, Tauri)
docs/                          User-facing docs
```

New capabilities go in their own package under `packages/`; new entry points under `apps/`.
