# Platform stress test — 2026-06-26

> "A heart attack in the middle of a hurricane with the water poisoned with GB
> and VX." The whole platform, every process, driven past its rated load and
> into adversarial / inconsistent-environment territory until something broke.

## TL;DR

| Axis | Result |
|------|--------|
| Full suite (13,673 tests) | **13,476 passed, 10 failed, 184 skipped, 3 xfailed** (519s) |
| Root causes behind the 10 | **1 real platform bug** (8 tests) + **2 stale tests** (2 tests) |
| Fix applied | `scrub_env()` git-config corruption — surgical fix + regression test |
| CI gates (all 10) | **green** |
| Concurrency / chaos / fuzz stress (7 campaigns) | **all held — zero violations** |

The dispatch substrate, budget accounting, authorization boundary, shared state
store, and dashboard all held under loads well past their defaults. The only
real defect surfaced was an environment-interaction bug in the git sandbox.

> **Follow-up (round 2).** Fixing Finding 2's stale risk assertion unmasked a
> **taxpayer-data confidentiality regression** (Finding 4) that the first failed
> assertion had been hiding — 12 client-data tax packs had been granted web
> egress, an exfiltration path. Round 2 resolves Findings 2, 3 and 4: the tax
> risk envelope, the compartment-scoped containment test, and the egress
> restructure. See the Round-2 section below.

---

## Finding 1 — `scrub_env()` corrupts git's env-config injection (FIXED)

**Severity:** medium · **Type:** portability / robustness · **Status:** fixed in this PR

**Symptom.** 8 tests failed, all git-backed:
`test_preview_diff_no_changes`, `test_preview_diff_shows_unstaged_changes`,
`test_apply_patch_dry_run_lists_files`, `test_apply_patch_applies_real_patch`,
`test_git_advanced_log_oneline`, `test_workspace_git_state`,
`test_workspace_git_state_disables_repo_fsmonitor`, `test_pin_and_readback`.
Every one died the same way:

```
error: missing config key GIT_CONFIG_KEY_0
fatal: unable to parse command-line config   (exit 128)
```

**Root cause.** Git reads env-based config injection as an **atomic protocol**:
`GIT_CONFIG_COUNT=N` declares exactly N `(GIT_CONFIG_KEY_i, GIT_CONFIG_VALUE_i)`
pairs. `sandbox/local.py::scrub_env()` strips by name pattern, and
`_SECRET_ENV_RE` matches the token `KEY` — so it stripped every
`GIT_CONFIG_KEY_*` while **keeping** `GIT_CONFIG_COUNT` and `GIT_CONFIG_VALUE_*`.
Git then saw `COUNT=3` with no `KEY_0` and aborted **every** command run through
the host-subprocess fallback in `tools/git_advanced.py`.

**Why it matters in the real world.** Env-based git-config injection is exactly
how GitHub Actions runners, Codespaces, and devcontainers wire up
`url.<base>.insteadOf` credential rewriting (this stress environment does too —
`GIT_CONFIG_COUNT=3`). On any such host the platform's entire `git_advanced`
toolset (log / diff / blame / apply_patch) and `trace_pin` workspace pinning
break. It only passed CI historically because the CI runner didn't inject git
config via env.

**Fix.** Keep the `GIT_CONFIG_COUNT/KEY_*/VALUE_*` family **all-or-nothing**: if
the secret filter dropped any member, drop them all so git cleanly falls back to
file config instead of choking on a dangling `COUNT`. This is also the *more*
secure outcome — a secret-bearing `GIT_CONFIG_VALUE_*` (e.g. an
`http.extraheader` auth blob, which the old regex did **not** catch) can no
longer survive into the child shell either. `packages/maverick-core/maverick/
sandbox/local.py`, with a regression test in `test_security_invariants.py`.

After the fix all 8 tests pass; the 81 existing secret-scrub / hardening tests
still pass.

---

## Finding 2 — `test_tax_prep::test_roster_present_and_sealed` is stale (FIXED in round 2)

**Severity:** low · **Type:** test drift · **Status:** resolved — see Round-2 section

The test asserts every `tax_*` pack has `max_risk == "low"`. Yesterday's commit
`1b7b0a7` ("feat: deepen banking, real-estate, tax… (68 packs)") promoted **10
of 31** tax packs to `medium` (`tax_audit_defense`, `tax_international`,
`tax_transfer_pricing_tax`, `tax_sales_use`, `tax_state_apportionment`, …) —
which is defensible domain modeling (audit defense and transfer pricing *are*
higher-risk advisory work). The pack data and the test now disagree.

**Recommendation:** update the test to reflect the intended per-pack risk
envelope (or, if the blanket-low invariant is the real spec, revert those packs).
Left for the owner because it's a product/governance decision, not a defect.

---

## Finding 3 — `test_spawn_specialist…sealed_domain` exposes a containment-semantics gap (FIXED in round 2)

**Severity:** low-to-medium · **Type:** test drift + governance question · **Status:** resolved — seal by compartment (Round-2 section)

The test seals a **domain** (`quarantine.seal_domain(dom, "prior compromise")`,
`dom = sorted(enabled_domains())[0]` = `aero_airworthiness`) and asserts the
specialist for that domain never runs. It runs anyway.

**Root cause.** Specialists are quarantined by **compartment**, not domain:
`_register_child_with_quarantine` records `child.domain`, which for a specialist
is `profile.compartment`. The profile for `aero_airworthiness` has
`compartment == "aero_mro"`. So `seal_domain("aero_airworthiness")` never matches
the specialist's registered compartment (`aero_mro`), `is_sealed()` returns
`False`, and the child executes. This drifted when commit `6572a7c`
("query-based specialist routing over the 1,118-pack roster") reshaped the
domain→compartment mapping so the first enabled domain's compartment no longer
equals its name.

**The real question for the owner:** when an operator seals a *domain* because it
was compromised, should specialists whose *compartment* differs from the domain
name still be allowed to run? If yes, the test is simply stale and should seal by
compartment. If no, this is a containment hole and `seal_domain` (or the spawn
guard) should also seal by domain identity. Flagged rather than silently
"fixed" because it changes governance semantics.

---

## Finding 4 — taxpayer-data confidentiality regression: client packs with web egress (FIXED)

**Severity:** high · **Type:** data-confinement / exfiltration surface · **Status:** fixed in round-2 PR

**How it surfaced.** pytest stops at the first failed assertion, so Finding 2's
risk-tier failure was masking a second, more serious break in the *same* test.
Once the risk assertion was fixed, the egress assertion failed.

**The invariant.** The tax suite was designed so taxpayer data can never leave:
a tax pack is **either** a client-data pack (reads the client `tax` corpus, no
web egress) **or** a web-research pack (the `tax_law` firm library, no client
corpus). Originally exactly one pack — `tax_law_watch` — had web access, and it
holds no client data.

**The regression.** Yesterday's "68 packs" commit added **12 tax packs that hold
the client `tax` corpus AND `web_search`** (`tax_audit_defense`,
`tax_international`, `tax_transfer_pricing_tax`, `tax_provision_prep`,
`tax_sales_use`, `tax_state_apportionment`, `tax_research_tax`, …). A pack that
can both read client taxpayer documents and call `web_search` is a structural
exfiltration path — a prompt-injected agent can encode client data into search
queries and it leaves the trust boundary.

**Fix (restructure, per owner decision).** Reading the personas, all 12 are
genuinely *client-grounded* ("ground every conclusion in the company's own
documents"); the only true no-client web-research pack is `tax_law_watch`. So
web egress was removed from all 12 (their live-authority lookups route through
the no-client `tax_law_watch` surface), their `web_search` workflow hints
retargeted to the in-boundary `knowledge_search`, and the denial made explicit
in `deny_tools`. The roster test is now **corpus-driven** — it enforces "client
`tax` corpus ⟹ no web egress" and "`tax_law` corpus ⟹ no client data, no
read_file" structurally, so a *future* pack that grants both fails the test, not
just the ones we happened to name.

Verified: 0 client-data tax packs permit web egress; `tax_law_watch` remains the
sole web-enabled pack (no client corpus). 64 tax tests + 475 domain/quarantine/
egress tests pass.

*(Open option for the owner: if any advisory function genuinely needs live web
authority lookups of its own, the heavier path is a dedicated per-domain
research companion with no client corpus — offered but not built, to avoid
speculative surface.)*

---

## Round-2 resolutions (Findings 2, 3, 4)

| Finding | Decision | Change |
|---------|----------|--------|
| 2 — tax risk envelope | accept per-pack tiering | assert `max_risk in {low, medium}` (still forbids high/critical) |
| 3 — sealed-domain test | stale test, not a hole | seal by **compartment** (the real containment unit); no behavior change |
| 4 — tax web egress | restructure | strip web from 12 client packs; corpus-driven invariant |

---

## Stress campaigns that HELD (the platform earning its keep)

Every campaign below was driven well past its production defaults. All passed
with zero invariant violations.

| Campaign | Load applied | Result |
|----------|--------------|--------|
| **JobQueue exactly-once** (multiprocess, true OS parallelism) | 5,000 jobs · **48 real processes** (12× cores) racing `claim()` | 0 duplicates, 0 lost — the `WHERE status='pending'` guard holds under genuine contention |
| **Control/data-plane soak** (the CI gate, cranked) | 2,000 goals · 24 concurrent workers | zero-loss, exactly-once, clean drain in 15s |
| **Budget accounting integrity** | 32 threads × 5,000 `record_tokens`, barrier-synced | 160,000 == 160,000 — no lost updates; the per-instance lock is sound |
| **Budget cap enforcement** | 16 threads racing a 10k-token cap | cap fired on every thread; no silent overshoot escape |
| **Capability authorization fuzz** | **399,131 probes** across 200 seeds × 2,000 rounds against `Capability.permits()` | **0 leaks** — no probe escaped the allow/deny envelope |
| **Chaos game-day** | injected transient + hard-outage faults w/ virtualized backoff | PASS (flake absorbed, hard outage fails fast, chaos-off clean) |
| **Dashboard under load** | 3,000 concurrent probes across `/healthz` `/livez` `/readyz`, 24 workers | 0 exceptions (503 on health/ready is the documented degraded-mode behavior w/o a provider key) |
| **WorldModel concurrency** | 16 connections × 200 goals create+transition on a shared SQLite DB | 3,200 unique goals, all transitioned, 0 errors |
| **Platform-wide import smoke** | every module in all 7 packages (785 core + 77 others) | 0 import failures |
| **CLI + TS SDK** | `maverick version`/`doctor`; `plugin-ts` suite | version OK; doctor exit-1 is by-design (no key/config); SDK 12/12 |

### CI gates — all green
`control_data_plane_e2e`, `control_data_plane_soak`, `grpc_api.contract --check`,
`migration_governance --ci`, `schema_migrations --ci`, `plugin_matrix --ci`,
`deprecations --ci`, `a11y_audit --ci`, `ruff check .`, `vulture`.

---

## Reproduce

```bash
# Baseline
python3 -m pytest -q

# The fix's regression test
python3 -m pytest -q packages/maverick-core/tests/test_security_invariants.py \
  -k git_config_injection

# Concurrency / chaos / fuzz harnesses (committed under scripts/stress/)
python3 scripts/stress/mp_jobqueue_stress.py
python3 -m maverick.control_data_plane_soak --ci --goals 2000 --workers 24
python3 -m maverick.chaos_gameday
python3 -m maverick.capability_fuzzer --rounds 2000
```
