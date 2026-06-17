# Maverick Codebase Review — June 2026

Ten parallel line-by-line reviews across the codebase (core agent loop,
CLI/config, LLM/providers, world-model/persistence, safety/sandbox/audit,
learning lifecycle, `tools/`, dashboard, shield/channels/mcp/evolve/knowledge,
and finance/skills/federation/grpc). Findings are concrete (`file:line`),
severity-tagged, and paired with a fix. This document is the deliverable — no
changes were applied.

---

## Executive summary — fix these first

Ordered by real-world impact across all ten areas:

1. **Dashboard authorization gaps (High).** Several global, non-goal-scoped
   mutating `/api/v1` endpoints authenticate but never authorize, so a
   read-only `viewer` can drive safety-critical controls in OIDC/RBAC mode:
   `halt` arm/clear (killswitch), tool enable/disable (safety overlay),
   approval approve/deny (consent gate), `facts`, `outcomes`, and
   `cache/purge`. See Area 8, items 1–5.

2. **Devcontainer backend leaks host secrets (High).**
   `sandbox/devcontainer.py:207-210` runs `subprocess.run` with no
   `env=scrub_env()`, so the docker client inherits `ANTHROPIC_API_KEY`, AWS
   creds, etc. — every sibling backend scrubs. See Area 5, items 1–2.

3. **Voice/RCS webhook auth can 500 on a crafted header (High).**
   `channels/voice.py:128` (and `rcs.py:136,203`) call
   `hmac.compare_digest(str, str)`, which raises `TypeError` on a non-ASCII
   bearer — the sole auth gate for Vapi. See Area 9, items 1 & 12.

4. **Evolve optimizes on garbage fitness signals (High).**
   `evolve/agent_adapter.py:117` scores subprocess failures as valid empty
   answers (ignores `returncode`/timeout), and `search.py` `min_improvement`
   is a documented no-op. See Area 9, items 2 & 7.

5. **MCP stdio loop crashes on a non-object JSON-RPC message (High).**
   `mcp/server.py:1352` calls `msg.get()` before validating that the parsed
   payload is a dict; a batch (`[...]`) or scalar kills the loop. `id: null`
   is also conflated with a notification (client hangs). See Area 9, items 3 & 9.

6. **MCP subprocess leak in orchestrator (Medium).**
   `orchestrator.py:604` starts MCP clients *outside* the try/finally that
   stops them (line 1436); any exception before the try body leaks the
   subprocesses. See Area 1, item 10.

7. **Postgres GDPR-erase deletes the wrong facts (High, multi-tenant).**
   `world_model_backends/postgres.py:1409` erases facts by episode
   attribution rather than user-scoped key prefix — can delete unrelated
   current facts while leaving the subject's actual facts intact. See Area 4.

8. **Empty `allowed_user_ids` inverts to allow-all (Medium).**
   `server.py:280` uses truthiness, so an explicit `allowed_user_ids = []`
   (lock-down intent) becomes `None` = allow everyone. Also `serve` binds the
   sandbox workdir to CWD. See Area 2, items 2–3.

9. **Skill-import frontmatter injection (Medium).**
   `skill_search.py:368` interpolates untrusted JSONL `name`/`description`
   into SKILL.md frontmatter without escaping newlines/`---`, allowing forged
   `tools_needed:` lines. See Area 10.

10. **`run_failing_tests` discards failure counts (High, learning quality).**
    `coding_mode.py:1626` drops the `failed` return from `_run`, so a
    mid-stream parse/sandbox failure can report a higher pass count than
    reality and let a PASS_TO_PASS regression score as clean. See Area 6, item 1.

Overall the codebase is mature and unusually defensive — extensive fail-open/
fail-closed reasoning, parameterized SQL throughout the core world model, real
hash-chained Ed25519 audit signing, IP-pinned SSRF defenses, and CSRF/webhook
signing done correctly. The recurring weak spot is **consistency**: a guard
that exists in one module is missing in its sibling (scrub_env, span
coalescing, authorization checks, fail-closed dedup, schema-skew tolerance).

---

## Area 1 — Core agent loop (`agent.py`, `orchestrator.py`, `reflexion.py`, `verifier.py`, `local_runtime.py`)

- **`orchestrator.py:604` + `:1436` — MCP clients leak (Medium).** `start_mcp_clients`
  runs outside the try whose `finally` stops them. An exception in
  `SwarmContext(...)` construction or the pre-try fact/history block leaks the
  started subprocesses. Fix: move the start inside the try, or wrap start+body
  in one try/finally.
- **`local_runtime.py:324/366` — zombie on replica restart (Low).** `Launcher.start`
  overwrites a dead `Popen` handle without `.wait()`/reaping it. Reap the dead
  process before spawning a replacement.
- **`orchestrator.py:1531` — best-of-N launches sub-$0.01 attempts (Medium).**
  `attempt_budget` is built without a minimum-viable per-attempt floor, so a
  tiny `remaining_dollars` still spins up a full agent run that immediately
  `BudgetExceeded`s (wasted episode row + MCP startup). Add a floor.
- **`agent.py:2956` — text block mixed into `tool_result` list (Medium, fragile).**
  Works today because all tool_result ids are present and the text is appended
  last, but the invariant is brittle. Worth an assertion/comment.
- **`verifier.py:320` — ensemble same-family fallback doesn't warn (Low).** The
  single-verifier path calls `_warn_same_family_verifier`; the ensemble
  fallback silently uses the same-family verifier. Add the warn for parity.
- Several low items (`reflexion.py` O(k²) re-tokenization, `strict=False`
  truncation, PRM nudge gate on resume) — quality/perf, not correctness.

*Health: unusually defensive; the MCP leak and replica-zombie are the only
items with real operational impact.*

---

## Area 2 — CLI & config (`cli.py`, `config.py`, `runtime_overrides.py`, `server.py`)

- **`server.py:280` — empty `allowed_user_ids` → allow-all (Medium).** Truthiness
  test drops an explicit empty list; an operator locking down to "nobody"
  silently opens to everyone. Use `is not None`.
- **`server.py:530` — `serve` sandbox workdir defaults to CWD (Medium).** Disagrees
  with `get_sandbox()`'s documented `~/maverick-workspace` default; a daemon
  launched from the repo root grants agents read/write there. Default to the
  same path as `get_sandbox()`.
- **`runtime_overrides.py:46` — `UnicodeDecodeError` uncaught in ACL path (Low).**
  A non-UTF-8 `runtime-overrides.toml` crashes `denied_tools()` in the security
  path; `config.py:100` guards this, this doesn't. Add `UnicodeDecodeError`.
- **`config.py:55` — `DEFAULT_CONFIG_PATH` cached at import (Low).** The module's
  own comment warns against caching `Path.home()`; the back-compat constant
  does exactly that and goes stale under `HOME` changes. Make it lazy.
- **`cli.py:2116` — `--best-of-n` silently ignored outside coding mode (Low).** Env
  var is set unconditionally but the run path is gated on coding mode; warn
  when given without `--coding-mode`.
- **`cli.py` is 5,986 lines / ~80 commands (Low, quality).** Correct but past
  maintainable size; consider splitting command groups into submodules.

*Health: mature and fail-soft; the two truthiness-vs-`is None` defaults that
widen access and the unguarded decode in the ACL path are the real risks.*

---

## Area 3 — LLM & providers (`llm.py`, `mcp_client.py`, `providers/`, `session_providers/`)

- **`providers/anthropic_provider.py:215` + `providers/__init__.py:60` —
  Anthropic `base_url` silently dropped (Medium).** The param is accepted but
  never put in `kw`, and `get_provider_client` omits it entirely. A
  `[providers.anthropic] base_url` (proxy/gateway) is ignored on both paths.
  Thread it through like the OpenAI client.
- **`llm.py:619` (and async `726`) — provider-health `dollars` delta wrong under
  shared budget (Medium).** `budget.dollars - _d0` races other concurrent
  sub-agents' `record_tokens`, inflating the recorded per-call spend and the
  `budget_dollars` metric. Return per-call spend instead of diffing a shared
  counter.
- **`retry.py:69` — `Retry-After-Ms` header ignored (Medium).** Only `Retry-After`
  (seconds) is parsed; a provider returning ms-only falls through to blind
  exponential backoff. Parse `retry-after-ms` (÷1000).
- **`providers/openai_provider.py:336` vs `anthropic_provider.py:445` — divergent
  missing-usage policy (Low).** OpenAI fails closed (`raise BudgetExceeded`);
  Anthropic coerces to `$0`. Budget enforcement becomes provider-dependent.
- **`session_providers/chatgpt_session.py:125` — fetched token never cached (Low).**
  Re-fetches `/api/auth/session` every `complete()` call. Cache it like
  `claude_session` caches `org_id`.
- **`llm.py:209` — model-resolution docstring stale (Low).** Doesn't list the
  dashboard-pin and local-first steps; could mislead. (No model is hard-coded —
  rule respected.)

*Health: good — budget accounting is careful, retry clamps negative
Retry-After, MCP clients close cleanly. Fix the dropped `base_url` and the
shared-budget dollar delta.*

---

## Area 4 — World model & persistence (`world_model.py`, `world_model_backends/`, `vector_store/`)

- **`world_model_backends/postgres.py:1409` — GDPR erase deletes wrong facts
  (High).** Erases facts by `source_episode_id IN (episodes of goal)`, but facts
  are global `UNIQUE(key)` memory — can delete unrelated current facts while
  leaving the subject's `user:<token>:` facts intact. Erase by user-scoped key
  prefix (as the SQLite cascade and `delete_facts_matching` do).
- **`world_model.py:1985/2029` — `Conversation(**dict(row))` not schema-skew
  tolerant (High).** Unlike every other reader it bypasses `_row_for`; a future
  added column (the PG backend already has `tenant_id`) makes every
  conversation read 500 with `TypeError`. Route through `_row_for`.
- **`vector_store/pgvector_store.py:79` — shared psycopg connection, no lock
  (Medium).** Reused across the FastAPI threadpool + background runner; psycopg
  connections aren't concurrency-safe. The PG world-model backend added an
  `RLock` for exactly this. Add a lock or use a pool.
- **`vector_store/qdrant_store.py:147` / `weaviate_store.py:122` — `delete` not
  tenant-scoped (Medium).** pgvector namespaces ids per tenant; these delete raw
  ids globally, so one tenant can delete another's vector. Namespace or scope.
- **`vector_store/chroma_store.py:124` / `qdrant_store.py:163` — `reset()` drops
  embedding config (Medium).** Chroma recreates without the original
  `embedding_function` (silently different embedding space); Qdrant never
  recreates (next query hits a missing collection). Recreate with the same
  config.
- **`world_model.py:903` — reclaim marker can overwrite withheld ciphertext
  (Medium, narrow).** In strict mode an unmigrated legacy `result` has its real
  ciphertext overwritten with the sealed placeholder + marker — irreversible.
  Skip the append when decryption yields the withheld sentinel.

*Health: core SQLite WorldModel is exemplary (WAL, RLock serialization,
fail-closed sealing, fully parameterized — no injection). The bugs live in the
secondary surfaces: PG erase, the non-`_row_for` conversation reads, and the
vector-store thread-safety/tenant/reset gaps.*

---

## Area 5 — Safety, sandbox, audit (`safety/`, `sandbox/`, `audit/`)

- **`sandbox/devcontainer.py:207` — host env not scrubbed (High).** `subprocess.run`
  with no `env=`; the docker client inherits the full host environment
  (API keys, AWS creds). Every sibling backend passes `env=scrub_env()`. Fix
  both the exec and the `_verify_docker` probe.
- **`sandbox/devcontainer.py:201` — `containerEnv` injected unvalidated (High,
  defense-in-depth).** Repo-supplied `.devcontainer/devcontainer.json` values go
  straight to `-e k=v`. Validate key shape; scrub secret-pattern names.
- **`safety/secret_detector.py:140` — `redact()` doesn't coalesce overlapping
  spans (Medium).** `pii_detector` coalesces for exactly this reason;
  `secret_detector` reverse-splices each match independently, so overlapping
  (non-identical) matches can corrupt offsets and leave secret material in
  cleartext. Latent, not confirmed-exploitable. Port the PII coalescing.
- **`safety/consent.py:189` — default auto-approve grants destructive actions
  (Medium, by-design).** With no `MAVERICK_CONSENT_MODE` and enterprise mode off,
  `rm-rf`/`force-push`/`dd`/mass-send are auto-granted. Ensure kernel
  destructive tools pass `allow_auto_approve=False` and the wizard prompts for
  a stricter mode.
- **`sandbox/kubernetes.py:92` — `--overrides` may not merge securityContext
  (Low, uncertain).** Override pins context onto container `"maverick"` while
  `kubectl run` names the container after the pod; if kubectl merges by name
  the hardening may silently not apply. Add a runtime assertion.
- **`audit/writer.py:222` — write failures swallowed to `return False` (Low).** A
  disk-full/permission failure becomes a silent audit gap; confirm callers or a
  watchdog surface persistent `record()==False`.

*Posture: strong and security-conscious — cap-dropping backends, real
hash-chained Ed25519 signing with fail-closed verification, deny-wins network
policy. The devcontainer env leak is the one concrete must-fix; the
secret-detector overlap gap is next.*

---

## Area 6 — Learning lifecycle (`dreaming.py`, `self_learning.py`, `assessment.py`, `coding_mode.py`, `edit_format.py`)

- **`coding_mode.py:1626` — `run_failing_tests` discards `failed` counts (High).**
  Both call sites drop the `failed` return; a mid-stream parse/sandbox failure
  reports a higher pass count than reality, letting a PASS_TO_PASS regression
  score as clean. Capture and use `failed` (or treat `passed+failed < total` /
  non-empty error as incomplete).
- **`coding_mode.py:614` — forbidden-test regex false-positives production files
  (Medium).** Hard-blocks `testbed.py`, `testkit.py`, `testdata.py`,
  `testcontainers.py` etc. (only `testing/testutils/testimonials` whitelisted).
  Narrow the match to real test-discovery patterns or warn instead of hard-block.
- **`edit_format.py:442` — step-2 (rstrip) fuzzy match lacks an ambiguity guard
  (Medium).** The strong `count >= 2` guard only covers the exact needle; the
  rstrip step edits the first match without checking for multiple rstrip-equal
  locations. Add `content_rs.count(needle_rs) == 1`.
- **`edit_format.py:524` — `apply_blocks` rollback swallows restore failures
  (Medium).** On atomic failure a failed restore `write_bytes` is `except OSError:
  pass`, leaving a mutated file while the summary reports rollback. Surface
  rollback failures; use temp + `os.replace` for atomic per-file restore.
- **`dreaming.py:360` — `__legacy_scope_unknown__` sentinel persisted to disk
  (Low/Medium).** Any rewrite serializes the loaded sentinel as a literal
  channel/user_id, turning the "ambiguous legacy" marker into an
  indistinguishable real scope. Strip it before `to_dict()`.
- **`self_learning.py:165` — `max(1, limit)` floors `min_cluster=0` to 1 (Low).**
  Recurs across several helpers; for `cluster_failures` it turns every one-off
  failure into a persisted "insight." Clamp at the config boundary, not silently.

*Health: defensive and well-annotated; the discarded `failed` counts (#1) is the
one bug that corrupts the fitness signal, with the regex false-positive and the
two edit_format gaps next.*

---

## Area 7 — Tools (`tools/`, 289 files; reviewed the 18 highest-risk)

- **`notebook_exec.py:50` — code execution from an unconfined host path (High).**
  `Path(path).expanduser()` with no `sandbox.workdir` confinement, then executes
  the notebook's cells. Every sibling tool confines (`pandas_query._safe_path`,
  `pdf_reader`, `view_image`). A model-supplied `~/anything.ipynb` is read off
  the host and run. Resolve under `sandbox.workdir` and reject escapes.
- **`ffmpeg_tool.py:56` — option-injection guard skipped when a sandbox is
  present (Medium).** The `sandbox is None` branch rejects leading-dash paths;
  the sandbox branch doesn't. `_safe_path` is reused by `sql_query`/`image_edit`
  where the stated invariant silently doesn't hold. Apply the dash rejection in
  both branches.
- **`http_fetch.py:128` — SSRF pre-flight fails OPEN on DNS failure (Medium).**
  `_is_private_ip` returns `False` (allowed) on `gaierror`; only the separate
  pinning layer saves it. Treat resolution failure as blocked, like
  `_resolve_pinned`.
- **`git_advanced.py:163` — `worktree_add` not confined to workspace (Medium).**
  Only rejects leading-dash; can create a worktree at an arbitrary absolute path
  outside the sandbox. Resolve under `workdir` and reject escapes.
- **`currency.py:42` — FX requests bypass the SSRF/pinning layer (Low).** Direct
  `httpx.get(..., follow_redirects=True)`; a 3xx from the provider could redirect
  to an internal address. Route through `_ssrf.safe_get`.
- **`apply_patch.py:104` — patch tempfile can leak into the repo workdir on
  interruption (Low).** Orphaned `.patch` shows up in later `git status`/diffs.
  Bracket tempfile creation in try/finally or write outside the repo.

*Health: good — the high-traffic file/shell/git/SSRF tools are well-hardened
(traversal guards, IP pinning, no `shell=True`, all shell via `sandbox.exec`).
`notebook_exec` is the outlier that executes from an unconfined path; the rest
are defense-in-depth inconsistencies.*

---

## Area 8 — Dashboard (`packages/maverick-dashboard/`)

**Root cause for items 1–5:** the app applies authn (`require_principal`) as a
router dependency but `require_permission` (authz) only per-route, inconsistently.
Mutating endpoints on *global, non-goal-scoped* state slip the gate.

- **`api.py:937,953` — `halt` arm/clear, no authorization (High).** Any
  authenticated `viewer` can arm/clear the global killswitch. Add
  `require_permission(request, "operate")`.
- **`api.py:1639,1654` — tool enable/disable, no authorization (High).** A
  `viewer` can disable safety-critical tools or re-enable disabled ones.
- **`api.py:1698,1706` — approval approve/deny, no authorization (High).** A
  `viewer` can approve a high-risk action the platform escalated to a human,
  defeating the consent gate.
- **`api.py:460,468` — `facts`/`outcomes` writes, no authorization (Medium).**
  Any user can poison fleet memory / the training reward signal.
- **`api.py:2246` — `cache/purge`, no authorization (Medium).** Resource-
  amplification DoS by a `viewer`.
- **`app.py:749` — rate-limit bucket collapses to the proxy IP (Low).** Behind the
  supported reverse proxy, all users share one bucket (one user can 429 the
  rest). Prefer the authenticated principal.
- **`auth.py:336` vs `app.py:493` — two hand-maintained exempt-path sets can
  drift (Low).** Derive one from the other.

*Posture: authentication, CSRF, webhook signing, SQL, traversal, and template
escaping are notably well-engineered. The one real weakness is inconsistent
**authorization** on global mutating routes — close with a route audit or a
default-deny dependency for non-`view` methods.*

---

## Area 9 — Shield / channels / mcp / evolve / knowledge

**maverick-channels**
- **`voice.py:128` — `hmac.compare_digest(str, str)` TypeError on non-ASCII bearer
  (High).** The sole Vapi auth gate 500s on a crafted header (retries amplify).
  Compare encoded bytes. Same pitfall at `rcs.py:136,203` (Low).
- **`whatsapp_cloud.py:187` / `sms.py:143` / `whatsapp.py:153` — dedup-claim
  fails OPEN (Medium).** On WorldModel/dedup-DB outage every provider redelivery
  re-runs and re-bills; `threads.py:135` chose fail-closed for the same case.
  Fail closed or gate behind a knob.
- **No webhook timestamp/replay check (Medium).** Signed bodies replay
  indefinitely (id-dedup can itself fail open); RCS passes its token as a URL
  query param (`?clientToken=`), leaking via logs/Referer. Add a skew window;
  require the RCS token in a header.
- **`mastodon.py:81` — allows plaintext `http://` for token-bearing requests
  (Low).** Force/validate `https://`.

**maverick-mcp**
- **`server.py:1352` — non-object/batch JSON crashes the stdio loop (High).**
  `msg.get()` before validating dict-ness; a batch or scalar kills `run()`.
  Validate `isinstance(msg, dict)` and handle list batches.
- **`http_transport.py:475` / `server.py:1362` — `id: null` conflated with
  notification (Medium).** A request with explicit `"id": null` is owed a reply
  but never answered (client hangs). Distinguish `"id" not in body` from
  `body["id"] is None`.
- **`tasks.py:187` — `task.future` assigned outside the insert lock (Medium).**
  A concurrent `cancel()`/`_purge_expired()` sees `future is None` and can evict
  a starting task. Assign under the same lock.
- **`server.py:393` — missing `protocolVersion`/`jsonrpc` not rejected (Low).**

**maverick-shield**
- **`guard.py:266` — `scan_tool_call` ignores operator constitution rules
  (Medium).** `scan_input`/`scan_output` compose `_constitutional_scan`;
  `scan_tool_call` (the most dangerous sink) doesn't. Apply the constitution.
- **`output_policy.py:73` — O(len(snippet)·len(haystack)) regurgitation scan
  (Low).** CPU sink on every `scan_output` for multi-KB prompts. Cap probe
  windows or use a rolling hash.

**maverick-evolve**
- **`agent_adapter.py:117` — subprocess failures scored as empty answers
  (High).** Ignores `returncode`/timeout, so a crashed run feeds `0.0` into the
  harness indistinguishably from a real empty answer. Check `returncode`, raise
  or use a distinct sentinel.
- **`search.py:29` — `min_improvement` is a documented no-op (Medium).** Children
  admitted unconditionally; implement the margin or remove the param.
- **`loop.py:50` — all-rounds-skipped returns `best=None` despite a valid seed
  (Medium).** Seed the archive before the loop.

**maverick-knowledge**
- **`store.py:61` — SQLite connection never closed (Medium).** No
  `close()`/`__del__`/context-manager; per-store construction leaks handles and
  can hold a file lock. Add lifecycle cleanup.

*Health: shield is genuinely strong (fail-open contract honored, base scan
always the floor) bar the tool-call constitution gap; channels have good
default-deny allowlists but recurring auth-edge/fail-open-dedup/replay risks;
mcp is thoughtful but exposed on JSON-RPC envelope edges; evolve's fitness-
signal bugs should be fixed before trusting long runs; knowledge just needs
resource hygiene.*

---

## Area 10 — Finance / skills / federation / grpc (`tax_prep.py`, `finance/`, `skills.py`, `skill_search.py`, `federation.py`, `a2a_tasks.py`, `plugins.py`, `grpc_api/`)

- **`skill_search.py:368` — frontmatter injection from untrusted JSONL (Medium).**
  `name`/`description` interpolated into SKILL.md frontmatter without escaping
  newlines/`---`; a record can forge `tools_needed: [shell]` or terminate the
  block early, and `validate_skill_file` doesn't catch a forged second section.
  Escape/reject newlines and `---` (mirror `build_skill_md`'s single-line
  collapse).
- **`grpc_api/maverick_v1_contract.json` — stale golden leaves `capability_json`
  unpinned (Medium).** `RunGoalRequest` declares fields 6 (`max_depth`) and 7
  (`capability_json`, a security-relevant grant) but the golden lists only 1–5;
  a future renumber/type-change of field 7 wouldn't be caught. Run
  `python -m maverick.grpc_api.contract --regen`.
- **`plugins.py:392` — plugin factory runs in-process before isolation (Medium).**
  `_isolated_factory` sandboxes only the returned `tool.fn`; the factory itself
  (arbitrary plugin top-level/`__call__`) executes in-process once at discovery
  regardless of `[plugins] isolation`. Run the factory under isolation or
  document that allowlisting is the only real trust boundary.
- **`grpc_api/contract.py:84` — `depth=1` reset breaks on nested message/enum/
  oneof (Low).** Safe only because the gated `maverick.proto` is flat; `oneof` in
  `plugin_host.proto` would mis-track braces. Use a brace-depth stack.
- **`tax_prep.py:743` — blank-state withholding mis-attributed to resident state
  (Low).** A 1099-R/1099-G with withholding but blank box-15 is credited to the
  resident return, overstating a refund. Emit an open item instead.
- **`tax_prep.py:549` — duplicate fingerprint omits several money fields (Low).**
  Omits `retirement_taxable`, `tuition`, `student_loan_interest`,
  `broker_proceeds` despite the "every extracted money figure" docstring.
- **`federation.py:583` — `reply` referenced unbound after `_abort` (Low).** Safe
  only because real gRPC `context.abort()` raises; a non-raising mock yields
  `NameError` masking the auth error. `return` inside the `except`.

*Health: tax/financial math is fundamentally sound — bracket boundaries (`<=`),
CTC phaseout rounding, and standard-deduction logic are correct, and the
float-based money handling is acceptable for a labeled "first-pass draft" a CPA
reviews. The actionable issues are non-math: skill-import frontmatter injection,
the unpinned `capability_json` gRPC field, and in-process plugin factory
execution.*

---

## Cross-cutting themes

- **Sibling-guard drift.** The same protection exists in one module but is
  missing in its twin: `scrub_env` (devcontainer vs other backends), span
  coalescing (pii vs secret detector), `require_permission` (goal-scoped vs
  global routes), fail-closed dedup (threads vs whatsapp/sms), `_row_for`
  schema-skew tolerance (most readers vs conversations), tenant-scoped delete
  (pgvector vs qdrant/weaviate). A lint/grep rule or shared helper would catch
  these.
- **Truthiness vs `is None`.** Empty-collection configs (`allowed_user_ids = []`)
  silently invert to permissive defaults. Audit security-relevant config reads
  for `if x:` where `if x is not None:` is meant.
- **`hmac.compare_digest(str, str)`.** Raises on non-ASCII. Standardize on a
  bytes-encoding helper across all channel webhook verifiers.
- **JSON-RPC envelope edges.** `id: null`, batch arrays, and non-object payloads
  are under-handled in the MCP transports.
- **Fail-open on infra outage.** Dedup, SSRF pre-flight DNS, and audit writes
  fail open; each is individually defensible but together they widen the blast
  radius of a transient dependency failure.
