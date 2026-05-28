# Contributing to Maverick

Thanks for being here. Maverick is built by accretion -- every commit
should make the foundation stronger without forcing a rewrite. Read
these guidelines before opening your first PR.

## Quick start (dev setup)

```bash
git clone https://github.com/cdayAI/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install --no-deps -e ./packages/maverick-shield
pip install --no-deps -e ./packages/maverick-channels
pip install --no-deps -e ./packages/maverick-dashboard
pip install --no-deps -e ./packages/maverick-mcp
pip install --no-deps -e ./apps/installer-cli
pip install pytest pytest-asyncio fastapi uvicorn jinja2 questionary rich

pytest -q
```

Make sure `maverick --help` works and `maverick doctor` prints a
status table.

## Project shape

```
packages/
  maverick-core/       Python agent kernel (recursive swarm, world model,
                       multi-provider LLM dispatch, skills, sandboxes)
  maverick-shield/     Agent Shield integration with builtin fallback rules
  maverick-channels/   9 channel adapters (Telegram, Discord, Slack, ...)
  maverick-dashboard/  FastAPI local web UI (goals/skills/facts/spend)
  maverick-mcp/        Model Context Protocol server (stdio JSON-RPC)
apps/
  installer-cli/       Interactive Python TUI wizard
  installer-desktop/   Tauri-based native GUI installer
deploy/
  docker/  vps/  desktop/
docs/                  User-facing guides
benchmarks/            Long-horizon eval suite + example skills
```

New capability → new package under `packages/`. New entry point → new
app under `apps/`. The wizard MUST learn to enable any new capability,
or non-technical users can't reach it.

## House rules

1. **Surgical changes.** Don't "improve" adjacent code. Match existing
   style even if you'd do it differently.
2. **Shield wired or it doesn't count.** If you add a new tool / sink,
   it goes through `ctx.shield.scan_tool_call()` before execution.
3. **Budget caps are non-negotiable.** Every long-running path must
   respect `Budget`. No bypassing `budget.check()`.
4. **Sandbox-mediate all shell.** Never call `subprocess.run` from a
   tool directly -- go through `sandbox.exec()`.
5. **Per-role model choice is user-controlled.** Never hardcode a model
   in the agent loop. Read from `maverick.config.get_role_model(role)`.
6. **Fail-open with a warning, never silently.** A broken scanner or
   missing optional dep must log loudly.
7. **Defaults belong in code; overrides in `~/.maverick/config.toml`.**

## Tests

- Every package has a `tests/` directory with `test_*.py` files.
- Use the `FakeLLM` fixture in `packages/maverick-core/tests/conftest.py`
  for any test that touches the agent loop -- never burn API credits in CI.
- Tests run via `pytest -vvs --tb=long` in CI on Python 3.10/3.11/3.12.

## Adding a provider

1. Create `packages/maverick-core/maverick/providers/<name>_provider.py`
   with a class implementing `complete()` and `complete_async()` that
   accept Anthropic-format messages/tools and return `LLMResponse`.
2. Register in `packages/maverick-core/maverick/providers/__init__.py`
   under `get_provider_client` and `KNOWN_PROVIDERS`.
3. Add to the wizard catalog at
   `apps/installer-cli/maverick_installer/models.py`.
4. Add tests for any format-translation logic.

## Adding a channel

1. Subclass `Channel` in `packages/maverick-channels/maverick_channels/<name>.py`.
2. Wire it in `server.py` (`_wire_<name>` + `_WIRES` dict).
3. Add to the wizard `CHANNELS` list.
4. Document setup steps in `docs/deployment.md`.
5. If it needs a Python SDK, add to `pyproject.toml` optional extras.

## Adding a skill

Write a `SKILL.md` (see `benchmarks/example-skills/README.md` for the
schema) and put it in `benchmarks/example-skills/`. Users install with
`maverick skill install gh:...`.

## Commit style

- Conventional commit subject (`feat:`, `fix:`, `docs:`, `refactor:`,
  `test:`, `chore:`).
- Body explains the *why*, not the *what*. The diff shows what.
- Reference the council finding or issue if applicable.

## Reporting bugs

Use the issue templates. Include `maverick doctor` output and the
relevant section of your `~/.maverick/config.toml` (with secrets
redacted).

## License

MIT. By contributing, you agree your contributions are licensed under
the same terms.
