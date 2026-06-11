# AGENTS.md

Maverick: proprietary Python 3.10-3.12 uv-workspace monorepo. 8 pip packages
(`packages/*`, `apps/installer-cli`) + a TypeScript SDK (`sdks/plugin-ts`).

## Setup (verified)

    bash .devcontainer/post-create.sh   # editable-installs all 8 packages
    pip install 'pyjwt[crypto]' cffi    # CI parity; distro cryptography needs cffi

`pip install -e .` at the root FAILS (workspace pyproject has no [project]).

## Commands (verified)

- Test: `python3 -m pytest -q` from repo root — NEVER bare `pytest`
  (PATH pytest may be an isolated uv/pipx shim that can't see the packages).
- Lint: `python -m ruff check .` and `python -m vulture`
- Build: `python3 -m build --wheel` inside a package dir
- Smoke: `maverick version`, `maverick doctor`
- TS SDK: `cd sdks/plugin-ts && npm install && npm test`

## Hard rules (each backed by a real failure or CI gate)

1. Never bare `import tomllib` — use the try/except tomli fallback (3.10; CI greps).
2. No `shell=True` outside `maverick/sandbox/` — use `sandbox.exec()` (CI greps).
3. Never hard-code model ids — `maverick.config.get_role_model(role)`.
4. Never bypass `Budget` — and note `record_tokens` enforces ALL caps
   (tokens/$/wall/tools) at record time, not just `check()`.
5. Kernel must run without `agent-shield` installed — fail open with a warning.
6. New capabilities need a config knob + an installer-wizard step.
7. PR titles: Conventional Commits prefix and the subject starts with a
   letter (`feat: add the 2027 ...`, never `feat: 2027 ...`).
8. Don't fix/enable ruff bugbear (B) findings in unrelated PRs — deliberately off.
9. Don't add `/api/v1/health` — `/healthz`, `/livez`, `/readyz` exist,
   auth-exempt by design; `/healthz` 503s until a provider key is configured.
10. Relative imports inside packages, absolute in tests; renames must update
    `docs/FEATURES.md` too.
11. Dashboard tests need `TestClient(app, headers={"Origin": "http://testserver"})`
    and the tmp-path world-DB fixture.
12. pytest aborts everything on one collection error; a pyo3 PanicException
    usually hides a missing import on the stderr line above it.

Suite at HEAD: 9094 passed, 107 skipped, 1 xfailed (~2m40s). No type checker
configured; ruff is the only static gate.
