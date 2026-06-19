# University curriculum kit — 12-week course

**Roadmap ref:** 2028-H1 Distribution — "university curriculum kit".
**Status:** kit complete; an instructor adopting it is the remaining
operational work. Pairs with [`university-outreach.md`](./university-outreach.md)
— **the educational license grant in that kit's IP note is a prerequisite**
for running this course (Lightwork is proprietary; coursework needs the
written grant).

A semester course — *Building and Governing Autonomous Agent Systems* — for
upper-division/graduate students, taught over the real codebase: ~680 test
files, CI on Python 3.10-3.12, and the architecture documented in
[`docs/architecture.md`](../architecture.md). Lectures teach the concept;
labs read and extend the shipped implementation of it. Module paths are
relative to `packages/maverick-core/maverick/`; tests are under
`packages/maverick-core/tests/`.

**Course-wide setup (week 1, keep it working all term):** the CONTRIBUTING
dev setup (`pip install -e './packages/maverick-core[dev]'` + sibling
packages), `pytest -q` green, `maverick doctor` green. Students use local
models (Ollama is a supported provider) or instructor-issued low-limit keys;
every lab that runs goals sets `--max-dollars`. The `FakeLLM` fixture
(`tests/conftest.py`) is the house pattern — no lab burns API credits in
tests.

## Weekly outline

| Wk | Topic | Reading | Lab (graded artifact) |
|---|---|---|---|
| 1 | What an agent runtime is; the OS lens | `docs/architecture.md`; README | Install from source; run a goal with `maverick start` + `maverick monitor`; submit the trace (`MAVERICK_TRACE_DIR`) with a written walk-through of the plan tree |
| 2 | The agent loop & recursive swarm | `orchestrator.py`, `agent.py`, `swarm.py`; `tests/test_orchestrator.py` | Trace a goal end-to-end in code: diagram which module owns each step from CLI verb to sub-agent result; identify the fan-out caps and where they bind |
| 3 | Budgets as a hard resource | `budget.py`; `tests/test_budget.py`, `test_budget_from_config.py` | Write 3 new budget tests (a cap interaction the suite doesn't cover); make them pass against the real `Budget.check()` |
| 4 | Persistent state: the world model | `world_model.py`; `tests/test_world_model_concurrency.py`, `test_query_plans.py`, `test_wal_contention.py` | Profile one hot query with `EXPLAIN QUERY PLAN`; explain why the query-plan regression test exists; propose (don't ship) an index change with measurements |
| 5 | Sandboxed execution | `sandbox/` (esp. `sdk.py`, `local.py`, `docker.py`); `tests/test_sandbox_sdk.py`, `test_sandbox_network_policy.py` | Implement a toy sandbox backend against the `SandboxV2` protocol as an entry-point package; pass `conformance()` |
| 6 | Tools & extension surfaces | `tools/decorator.py`; `plugins.py`, `docs/plugin-api-v2.md`; `sdks/plugin-ts/` | Build one tool twice: as a `@tool`-decorated Python function and as a TS-SDK plugin; pass `python -m maverick.plugin_matrix --ci` |
| 7 | Safety I: the shield | `docs/safety.md`; `packages/maverick-shield/maverick_shield/` (`builtin_rules.py`, `redteam.py`, `redteam_corpus.jsonl`) | Add ≥5 labeled attack/benign pairs to a corpus copy; run the red-team gate; write up a miss and why the heuristic missed it |
| 8 | Safety II: capabilities & consent | `capability.py`, `capability_boot.py`, `safety/consent.py`; `tests/test_capability.py`, `test_capability_fuzzer.py` | Run the capability fuzzer; design 2 new probe families; argue (in writing) whether each could leak and verify with the fuzzer |
| 9 | Audit & compliance engineering | `audit/` (signing, retention, federation); `tests/test_audit_verify_cli.py`, `test_audit_tenancy.py` | Tamper with a copied audit log byte-by-byte; show `maverick audit verify` catching each manipulation class; map which it can't and why |
| 10 | Context engineering | `compaction.py`, `compaction_plugins.py`, `context_compactor.py`; `tests/test_compaction_plugins.py` | Register a custom compaction strategy; benchmark it against `"heuristic"` on a fixed transcript corpus (tokens kept vs. task success) |
| 11 | Multi-tenancy & isolation | `workspace.py`, `paths.py`, `tenant_kms.py`; `tests/test_multitenant_isolation.py` | Extend the isolation suite with one new cross-tenant probe; explain the tenant wall it exercises |
| 12 | Evaluation & the honest benchmark | `benchmarks/` (`harness.py`, `EVAL.md`, `RESULTS.md` conventions) | Run one benchmark multi-seed under a cap; submit measured rows + an analysis that states variance and limitations |

**Weeks 13-15 (if the term allows): project block** — teams pick from the
[outreach project menu](./university-outreach.md) and are graded on its
evaluation rubric.

## Assessment

- Labs 60% (each graded on the outreach rubric's *works / tested / scoped /
  honest / communicated* dimensions, scaled down).
- Project or final benchmark study 30%.
- Participation in code review 10% — students review each other's lab PRs
  against the CONTRIBUTING house rules; reading review is a course outcome.

## Instructor notes

- **What needs no instructor build:** every lab gate is shipped tooling
  (pytest, the fuzzer, `plugin_matrix`, the red-team runner, `conformance()`,
  `audit verify`). The course has no bespoke autograder to maintain.
- **Hardware:** any laptop that runs Docker handles weeks 1-12; week 5's
  container backends degrade to the local backend where Docker isn't
  available.
- **Honesty norms are course content.** The repo's own discipline —
  measured-vs-manual benchmark rows, decision docs that record declines,
  "empty sections say so" — is taught explicitly in weeks 9 and 12; it's
  the part students won't get elsewhere.
- **Contribution path:** lab work that clears the bar can be PR'd upstream
  under the [CLA](../../CLA.md) — optional, never required for grade
  (universities differ on whether required assignments may be assigned;
  the outreach kit's IP note covers this).
- **Materials status:** slide decks are an instructor deliverable; this
  outline + the cited readings are self-sufficient for an instructor who
  reads code. _Maintainer office-hours support per the outreach kit's
  commitment cap._
