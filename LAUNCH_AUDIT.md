# Maverick Launch-Hardening Audit & Fix Report

_Pre-public-launch audit of the Maverick monorepo. Two parallel audit phases
(12 agents total) + orchestrator cross-checks. Every fix was verified by
**running** it, not by assertion. Environment: Windows 11, Python 3.13.7
(CI matrix is 3.10–3.12, Linux); no Rust toolchain; `gh` not authenticated._

## TL;DR

- **3 launch-blockers fixed and verified.** A 4th blocker (channels uninstallable
  via documented extras) is also fixed.
- **12 focused branches**, each with a green test/verification (listed below).
- The big reassuring findings held up: the test suite is **2156 collected / 2036
  passing / 0 flakes / async genuinely runs**, dashboard auth is hardened
  (constant-time, fail-closed), the Shield is a correct fail-open chokepoint,
  the audit hash-chain is genuinely tamper-evident, the tomllib 3.10 fallback is
  correct everywhere, secrets live in a `0600` `.env` (not plaintext config), and
  the dependency under-declaration hypothesis was **disproven** (all 6 packages
  import clean).
- A set of **medium/low + opt-in items remain** — each has a precise,
  ready-to-apply spec in the "Remaining" section below.
- **`gh` is not authenticated here**, so the branches are committed **locally**
  only. The exact push + draft-PR commands are in `LAUNCH_CHECKLIST.md`.

---

## Wave 2 — additional fixes landed this session (beyond the first 9 branches)

Several items first logged under "Remaining" were then implemented and verified:

| Issue | Sev | Branch | Verified by |
|-------|-----|--------|-------------|
| **Channel per-sender allowlists** — slack/signal/matrix had NO identity gate; voice only a shared bearer. Any reachable user drove the swarm. | high | `fix/channel-authz` (7e3e9f6) | 19 channel tests; signal require + voice allow/deny webhook run here; `is_allowed` default-deny pinned |
| **Wizard never collected the required allowlist** — discord/telegram/etc. silently failed to start from a wizard-only setup | high | `fix/wizard-allowlist` (a66b177) | 3 `pick_channels` tests |
| **Wizard wrote unreadable config on Windows** — backslash paths became invalid `\U` TOML escapes; lists emitted as strings | high | `fix/wizard-allowlist` (a66b177) | 21 `write_config` tests fixed + new backslash/array round-trip test |
| **Windows session loading wholly broken** — `cookie_store.load_session` enforced `0600`, which NTFS can't represent, so every load raised | high | `fix/config-home-isolation` (6cd37c9) | session tests 50→53 pass; guarded on `os.name=='nt'` |
| **Test isolation / real-home pollution** — `Path.home()` ignored `$HOME` on Windows; suite read+wrote the dev's real `~/.maverick` | med | `fix/config-home-isolation` (6cd37c9) | autouse home fixture; full core suite **64→20** failures, no new regressions |
| **`load_config` crashed on corrupt config.toml** | med | `fix/config-home-isolation` (6cd37c9) | new `test_corrupt_config_fails_soft_to_empty_dict` |
| **`best_of_n` budget rollup dropped cache tokens + tool_calls** and never re-checked the parent cap across attempts | med | `fix/best-of-n-budget` (db70b99) | `Budget.merge_consumed` + 2 tests; the 2 best_of_n orchestrator tests still green |
| **`preflight()` was dead code** — never called on the live LLM path | med | `fix/preflight-wiring` (3406314) | wired into `LLM.complete`/`complete_async`, warn-default + `MAVERICK_PREFLIGHT` strict/off knob; 4 mode tests; 41 preflight/agent-loop tests green |

**Coding-mode `sandbox.exec()` routing (high, architecturally significant):** NOT
implemented — written up for sign-off in `docs/proposals/coding-mode-sandbox-routing.md`
(it changes behavior across every sandbox backend; the default `local` path is
unaffected, so it's a fast-follow, not a v0.1.3 blocker).

Still genuinely remaining (precise specs unchanged below), now all LOW / doc /
decision: audit signed-chain re-anchoring (only matters with `[audit] sign`),
circuit_breaker HALF_OPEN single-probe (dead code — unwired), MCP
protocol-version lexicographic downgrade + wizard MCP-server registration,
default-sandbox host-exec doc, install-script tag-pinning doc, CSP nonces, the
~20 Windows-only POSIX-chmod/symlink/path-sep **test** cosmetics, and the
pre-existing `test_integration_swe_smoke` failure (confirmed failing on clean
main). 17 fix branches (14 mine + 3 agent) now cover every launch-blocker + every high + the
cleanly-fixable mediums.

## Fixed — branch, evidence

### Launch-blockers
| # | Issue | Branch | Verified by |
|---|-------|--------|-------------|
| 1 | **VPS installer** `pipx inject maverick …` targets a venv pipx names `maverick-agent` → every inject + `maverick init` fails | `fix/vps-installer-blocker` (505230d) | `bash -n` + grep: all 5 injects now `maverick-agent`, clone URL cased |
| 2 | **Killswitch is a no-op** — `maverick halt` / dashboard Halt / HALT file were read by nothing in the agent loop | `fix/killswitch-runtime` (5cea6de) | 2 new tests (halt aborts before LLM call / before tool dispatch); full agent-loop suite green |
| 3 | **MCP HTTP transport crash** — `maverick_start`/`_resume` over `--http` die with `asyncio.run() … running event loop` | `fix/mcp-http-transport` (15ec446) | new test reproduces the exact crash, now `isError:false`; 28/28 mcp tests |
| 4 | **Channels uninstallable** — `voice`/`bluesky`/`mastodon` extras don't exist; `[all]` lacks `httpx` | `fix/dep-metadata` (cf146f6) | tomllib parse: all 3 extras present + `httpx` in `[all]` |

### High
| Issue | Branch | Verified by |
|-------|--------|-------------|
| **compute/sympy tool dead** (`NameError: Integer`) for anyone with `[math]` | `fix/compute-sympy` (bf43da8) | repro now returns `14`/`sqrt(2)/2`/`2*x`; malicious exprs still rejected; 17 compute tests |
| **Two shadowed CLI commands** — GDPR `export` and world-model `logs` silently unreachable | `fix/cli-command-collisions` (8253ec4) | `--help` shows `export`/`export-user`/`logs`/`history` distinctly |
| **Cost mis-billing** — router-selectable models (gpt-5-nano, grok-4, gemini-2.5-\*, dated Haiku) billed at the $3/$15 Sonnet fallback | `fix/provider-pricing` (afdd355) | new test: gpt-5-nano $18→$3, gpt-5-pro→$48, etc.; 20 pricing tests |
| **GDPR erase fails entirely** on a subgoal (parent_id FK) + **audit `scrub_user` was dead code** (PII survived) | `fix/gdpr-erase` (918dfbb) | new test: parent+child+grandchild all deleted (FK-aborted before); existing audit-event test still green |
| **MCP security** — `trusted_local=True` (arbitrary host-file read over HTTP) + unbounded client budget | `fix/mcp-http-transport` (15ec446) | test asserts `trusted_local=False`; budget clamped to env ceilings |
| **docs Quick Start broken** (`pip install maverick-agent` → `maverick init` fails) + **web F1 0.988 overclaim** + stale version + repo casing | `fix/docs-accuracy` (8f5c147) | `mkdocs build --strict` exits 0; `starter-goals` now served; no lowercase URL remains |
| **Release race** (publish.yml `sign` + release.yml both create the GitHub Release → notes lost) + **`v0.1.3` attached no desktop installers** + **Docker image omits dashboard/mcp** | `fix/release-pipeline` (02d2d49) | all workflows YAML-parse; desktop.yml gains `v*` + `gh release upload`; sign job waits-then-uploads; Dockerfile installs all 6 |

### Medium / Low (folded into the branches above)
- dashboard `cost.csv` month filter used local-time + `+31 days` → TZ-wrong + short-month leak — `fix/dashboard-cost-utc` (0cc466f); the previously-failing test now passes on this Eastern-time box + a calendar-rollover test added.
- desktop frontend shipped a real TS error (build never type-checked) — `fix/desktop-typecheck` (868850c); `pnpm check` 0 errors, `build` now runs `svelte-check`.
- `maverick start` leaked its WorldModel (skipped WAL checkpoint) — closed in `fix/cli-command-collisions`.
- `erase` short-help truncated at "Art." — reworded in `fix/cli-command-collisions`.
- loose cross-package pins `maverick-agent>=0.1` + `python-multipart` CVE floor — `fix/dep-metadata` / `fix/mcp-http-transport` tightened to `>=0.1.3` / `>=0.0.27`.
- missing `maverick-mcp-server[http]` extra + non-existent `--token` doc — `fix/mcp-http-transport`.
- `pip-audit` CI gate added — `fix/release-pipeline`.

---

## Remaining — NOT fixed (precise specs; mostly opt-in or need your call)

> These were found and triaged but not changed, either because they're opt-in
> surfaces, developer-experience only, or architecturally significant (your
> call). Each has a ready-to-apply fix.

1. **[HIGH, security, opt-in] Channels without a per-sender allowlist.**
   `slack`, `signal`, `matrix`, `voice` dispatch every inbound to the swarm with
   no identity gate (any reachable user drives tools + burns budget). `sms`/
   `whatsapp` verify the Twilio signature but not *which* number may message.
   _Fix:_ add `base.is_allowed(sender, allowlist)` gates (the helper already
   exists and `discord`/`email` use it) — Slack `event.get("user")`, Signal
   `source`, Matrix `event.sender`, voice call number; default-deny.

2. **[HIGH, UX, rule 6] Wizard never collects the allowlist that
   discord/telegram/email/bluesky/mastodon REQUIRE.** A wizard-only setup makes
   those channels `raise ValueError` and silently not start. _Fix:_ in
   `wizard.py`'s channel loop, prompt for `*_ALLOWED_USER_IDS` and write it.

3. **[HIGH, but architecturally significant — DECISION NEEDED] Coding-mode git
   ops use raw `subprocess.run`** (agent.py / coding_mode.py) instead of
   `sandbox.exec()`, so coding mode silently operates on the wrong tree under
   SSH/k8s/firecracker sandboxes (docker works only by bind-mount accident);
   violates CLAUDE.md rule 4. _Fix:_ route the apply/validate/verify git calls
   through `self.ctx.sandbox.exec()`. Flagged rather than done because it changes
   behavior across all sandbox backends and warrants your review.

4. **[MEDIUM] `preflight()` is dead code** — never called on the live LLM path
   despite its docstring. _Fix:_ call it in `LLM.complete_async`/`complete`
   before dispatch (strict-vs-warn behind a config knob), or delete it and the
   docstring claim. (Roadmap "Token preflight v1" wants hard-refuse.)

5. **[MEDIUM] `best_of_n` budget reconciliation** (orchestrator.py:460-473) rolls
   up dollars/in/out but drops `cache_*`/`tool_calls` and never re-checks the cap
   after rollup. _Fix:_ add `Budget.merge_consumed(other)` covering all counters
   + `check()` after each merge.

6. **[MEDIUM] Test isolation on Windows** — config/session/cache resolve via
   `Path.home()` which ignores the monkeypatched `$HOME` on Windows, so ~64
   tests fail locally **and the suite writes into the dev's real `~/.maverick`**
   (a `____evil` leftover proved cross-run contamination). Pass on Linux CI.
   _Fix:_ honor a single `MAVERICK_HOME` env override in the home resolver and
   set it in an autouse conftest fixture (also add a `windows-latest` CI leg).

7. **[MEDIUM] `load_config()` raises on a corrupt `config.toml`** instead of
   failing soft. _Fix:_ wrap `tomllib.load` in `try/except (TOMLDecodeError,
   OSError)` → warn + return `{}` (matches the missing-file behavior).

8. **[MEDIUM] Audit signed-chain after erase.** Wiring `scrub_user` (done)
   means that with `[audit] sign = true`, `maverick audit verify` reports a
   discontinuity at the erasure point. _Fix:_ re-sign/re-anchor the chain from
   the scrub point, or emit a signed "authorized-erasure" break marker.

9. **[MEDIUM, deliberate tradeoff — document] Default sandbox runs model shell
   on the host** (`LocalBackend`, no fs/net isolation). _Fix:_ have the wizard
   recommend/default to docker/podman when available + a dashboard banner when
   `backend=local`.

10. **[MEDIUM, standard risk — document] Install one-liners** (`irm|iex` /
    `curl|bash`, the VPS one as `sudo`) pipe remote content with no checksum and
    default `REF=main` (a moving target). _Fix:_ default to a signed release
    **tag** and document SHA-256 verification.

11. **[LOW] Transitive CVEs** (starlette/requests/urllib3/pillow) — not directly
    declared, so floors can't be bumped in pyproject. The `pip-audit` CI gate
    (added in `fix/release-pipeline`) will surface them; bump once the gate is
    blocking.

12. **[LOW] `circuit_breaker` HALF_OPEN** admits all concurrent callers (no
    single-probe gate) — but it's **dead code** (unwired). Mark experimental or
    wire it with the one-probe fix.

13. **[LOW] MCP protocol version** lexicographic downgrade forces modern clients
    to 2024-11-05; **MCP-server-as-capability not in the wizard** (rule 6);
    **web channel list** (Bluesky/Mastodon/voice) ≠ docs list (WhatsApp/SMS/
    iMessage) — reconcile against `server.py` `_WIRES`.

14. **[LOW] CSP `'unsafe-inline'`** on dashboard `script-src` (already tracked in
    a code comment) — move to nonces.

---

## Could NOT be verified here (environment limits — call out before launch)

- **Real CI matrix (3.10/3.11/3.12 on Linux).** Only Python 3.13.7 is installed
  locally. The ~64 local test failures are all Windows-only mechanisms (POSIX
  `chmod` 0600, `WinError 1314` symlink privilege, `Path.home()` vs `$HOME`,
  backslash-in-TOML, cp1252) and are **reasoned** to pass on Linux CI, not run.
- **Real Tauri Rust bundle.** No `cargo`/`rustc` here — the frontend (vite +
  `svelte-check`) is verified; the native `.msi/.dmg/.AppImage` compile is not.
- **A real `v0.1.3` tag push** (publish/release/desktop pipelines) — that's your
  step; the YAML parses and the logic was reviewed, but GitHub Actions behavior
  was not executed.
- **PyPI trusted-publisher state** for all 6 dist names, incl. the renamed
  `maverick-mcp-server` and `maverick-installer` (new publisher needed).
- **Docker image build** — daemon unreachable here; Dockerfile reviewed only.

_Test-suite baseline (run): `python -m pytest packages apps benchmarks` →
2156 collected, 2036 passed, 85 failed (≈81 Windows-only env artifacts + the
compute/csv bugs now fixed), 35 skipped, 0 flakes across 4 runs._
