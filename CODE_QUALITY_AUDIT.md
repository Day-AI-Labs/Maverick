# Lightwork / Maverick — Exhaustive Code-Quality Audit

**"Vibe-coded slop" vs. true enterprise code — a full-codebase review.**  
Prepared 2026-06-27 · ahead of the Grant Thornton partner meeting.

> **Read this first.** This is an honest engineering review, not a sales doc. The headline is 
> reassuring: of 125 reviewed code regions, **100 rated *enterprise-grade* and 25 *mostly-solid* 
> — none rated *mixed*, *weak*, or *slop*.** The kernel (governance, budget, audit log, capability 
> tokens, multi-tenant crypto, exactly-once job processing) is the real thing and stands up to 
> scrutiny. The slop is **localized to the periphery** (alternative sandboxes, language ports, a 
> second-tier backend, a few privacy/ML features) and — most dangerously for a diligence meeting 
> — **to the prose**, where the pitch deck and some docs claim more than the code delivers. The 
> single highest-leverage thing you can do before the meeting is **make the deck and docs match 
> the code.**

---

## Methodology & scope

- **Coverage:** every line of non-test source — **232,479 LOC across 988 files** in 5 languages 
  (Python, Rust, Go, TypeScript, Swift), in 125 directory-coherent chunks. Test files (~170K LOC) 
  were excluded from the deep read by design.
- **Method:** 125 independent reader agents (one per chunk, reading every line of its files); a 
  claims-vs-reality track verifying the boldest README/ARCHITECTURE/pitch claims against the code; 
  an **adversarial verification pass on every high-severity finding** (each re-read by a skeptic 
  prompted to *refute* it); and synthesis. ~180 agent-analyses, ~10M tokens.
- **Calibration against false positives:** agents were told many trigger-words here are legitimate 
  (`simulate_action` is a real dry-run feature; `naive_effect` is a real statistics term; the 
  kernel's documented fail-open design is intentional). The goal was *defensible* findings.
- **What verification changed:** of the 13 high-severity findings, **8 were confirmed, 4 
  downgraded, and 1 refuted** on independent re-read. (The auto-generated synthesis narrative 
  below was written *before* verification and says "Refuted: 0" — that line is wrong; see the 
  **Verification corrections** box right after it.)
- **Honesty caveat:** the high-severity findings are independently verified. **Medium/low findings 
  carry only the original auditor's confidence and were not independently re-verified** — treat them 
  as a high-quality worklist, not gospel.

- **Findings (after verification):** 260 active — **0 critical, 8 high, 74 medium, 178 low**, across 200 files; plus 1 reviewed-and-dismissed.
- **Claims tested:** 24 — 8 🟡 Partial / overstated, 16 ✅ Substantiated.

---

## ⚠️ Verification corrections (authoritative — overrides the narrative below)

The synthesis narrative further down was generated before the adversarial verification pass ran, so 
it lists some findings at a severity the re-read did not sustain. The corrected verdicts:

| # | Finding | Auditor said | Verified verdict |
|---|---|---|---|
| 0 | Go port returns raw error strings to client, dropping the Python original's mandatory secr | high | ✅ confirmed |
| 1 | Trajectory donation claims a PII-redaction step that does not exist; only secret-shaped st | high | ✅ confirmed |
| 2 | gRPC dispatcher sends bearer token over a hardcoded insecure (plaintext) channel, ignoring | high | ✅ confirmed |
| 3 | Unconditional, hardcoded governance/compliance claim surfaced to buyers regardless of actu | high | ✅ confirmed |
| 4 | "Compaction v6 hybrid" learned strategy picker is dead code — never wired into any product | high | ✅ confirmed |
| 5 | Documented inbound transcript-injection screen has zero production callers (dead safety co | high | 🔻 downgraded → **medium** |
| 6 | Firecracker microVM 'isolation' runs commands against an empty rootfs — the agent's worksp | high | 🔻 downgraded → **low** |
| 7 | Differential-privacy noise is seedable and uses a non-crypto PRNG, defeating the privacy g | high | 🔻 downgraded → **low** |
| 8 | Weaviate adapter claims server-side vectorization but creates a vectorizer-less collection | high | ✅ confirmed |
| 9 | Memory Guard trust-tiering (OWASP ASI06) is silently defeated on the Postgres backend | high | ✅ confirmed |
| 10 | RLS NULL-tenant data-safety preflight is swallowed, then FORCE RLS runs anyway | high | ❌ refuted |
| 11 | retitle_goal / reparent_goal reach into SQLite-only WorldModel internals and 500 under the | high | ✅ confirmed |
| 12 | Rust verifier trusts any lone <key_id>.pub, dropping the Python source's forged-pubkey def | high | 🔻 downgraded → **low** |

**The three that moved most, and why** (these are the ones *not* to lead with in the room):

- **`postgres.py` RLS preflight "fail-open" — REFUTED.** The NULL-tenant hazard is detected on the 
  preflight's *success* path and hard-fails the boot; the swallowed `except` only covers infra read 
  errors, and the downstream `FORCE ROW LEVEL SECURITY` is itself fail-closed inside a rolled-back 
  transaction. There is no path where legacy rows are silently frozen. Drop this one.
- **`dp_stats.py` differential-privacy "backdoor" — DOWNGRADED to low.** The seed is a *caller-supplied* 
  parameter that defaults to OS entropy and is **never emitted in the output**, so a consumer of a 
  published statistic can't know it — the "adversary who knows the seed" is a non-threat. The real 
  (minor) issue is that it uses Mersenne-Twister rather than a CSPRNG: a legitimate hardening note.
- **`firecracker.py` empty-rootfs "isolation" — DOWNGRADED to low.** Real gap, but the module is 
  explicitly labelled `SCAFFOLD`, is opt-in (not the default sandbox), and **fails closed** with an 
  explanatory error when its kernel/rootfs images are absent (the default on every host). No user is 
  silently told a blank-VM run succeeded.
- **`rust verify-audit` lone-pubkey trust — DOWNGRADED to low.** Real divergence from the Python 
  verifier, but the tool's docs explicitly scope the byte-exact parity claim to `--pubkey` mode and 
  warn that `--keys-dir` trusts local files; the exploit needs the documented-as-weaker mode *plus* 
  attacker write access to the keys dir.
- **`voice_safety.py` dead inbound screen — DOWNGRADED to medium.** Genuinely dead code and the 
  `FEATURES.md` present-tense claim is dishonest, but the module is roadmap-labelled and there's no 
  live end-user voice flow it would have protected today.

---

## Executive narrative

> *Auto-generated synthesis. Accurate on the big picture and the confirmed findings; for the high-
> severity verdicts, defer to the corrections box above.*

### 1. Bottom line

This is a **real-but-uneven codebase** — genuinely substantial engineering, not theater, but with a marketing-vs-code credibility gap that a sharp partner will find. The core governance, budget, audit, capability-token, and multi-tenant encryption subsystems are the real deal: ~214K lines of hand-written Python (plus ~84K of declarative pack config), with load-bearing controls that are actually wired into execution paths and survive fault-injection and concurrency stress at the cited numbers. Of 24 audited headline claims, **16 are fully substantiated and 8 are partial — none were outright refuted** — which is a strong ratio for a seed-stage platform. The single biggest risk is **internal inconsistency between the pitch deck and the running product**: the SEED-DECK explicitly promises "every number here is real and verifiable," yet states 1,118 packs / 26 suites while the code, README, and on-disk count all say 2,020 / 53 — and a partner running the very command the deck cites as proof gets the contradicting number. The secondary risk is a cluster of **13 high-severity "fake feature / dead control" findings** in second-tier subsystems (Postgres backend, alternative sandboxes, ports to Rust/Go, donation/DP privacy claims) where a documented capability is inert, defeated, or diverges from the Python source of truth. The flagship demo holds up under live execution; the slop is in the periphery and in the prose, not the kernel.

### 2. Smoking guns

Lead with the claim-vs-code contradictions — these are what a diligence partner is trained to catch:

1. **Pitch deck contradicts the product** — `pitch/SEED-DECK.md` / `ONE-PAGER.md` say 1,118 packs / 26 suites while code+README+disk say 2,020 / 53; the deck's own "every number is verifiable" line makes this self-undermining.
2. **`world_model_backends/postgres.py:2096` — anti-memory-poisoning control silently defeated**: the live `facts` table has no trust-tier columns, so the read path hardcodes tier-3 (fully trusted) for *every* fact; the ASI06 memory-guard floor never fires on the enterprise/HA backend.
3. **`rust/maverick-verify-audit/src/lib.rs:238` — "byte-exact port" weakens the audit guarantee**: the Rust verifier trusts any lone `<id>.pub`, dropping the Python source's forged-pubkey defense, so a tampered chain prints "OK" where Python reports a break — in the one tool whose entire job is tamper detection.
4. **`go/model-proxy/handle.go:38` — "byte-for-byte port" leaks secrets the Python original scrubs**: the Go proxy returns raw upstream error strings to the (potentially compromised) client; Python deliberately runs `scrub()` on both error paths.
5. **`sandbox/firecracker.py:189` — "microVM isolation" runs against an empty rootfs**: the agent's workspace is never copied into the VM, so `pytest`/edits operate on a blank filesystem and produce confidently-wrong results; workspace transfer is an admitted "scaffold."
6. **`donation.py:10 / 255` — phantom PII redaction**: the docstring promises secret-scrubbing *and* PII redaction before trajectories leave the box; only the regex secret-scrubber exists — names/emails/SSNs/transcripts ship intact.
7. **`tools/dp_stats.py:16 — differential privacy is breakable by design**: Laplace noise uses a non-crypto Mersenne-Twister PRNG with a *public seed* argument, so an adversary who knows the seed recovers the true value exactly.
8. **`worker_review.py:133 — hardcoded compliance assurance**: a constant string telling buyers every action "passed the shield" and is "signed/tamper-evident," rendered verbatim into the dashboard — true even when the shield is absent (a supported posture) and signing has degraded to unsigned.
9. **`world_model_backends/postgres.py:835` — a fail-OPEN safety gate**: the RLS NULL-tenant preflight that is documented to "refuse to boot" swallows its own errors and then runs the destructive `FORCE ROW LEVEL SECURITY` anyway.
10. **`grpc_dispatcher.py:82` — bearer token over hardcoded plaintext**: the dispatcher ignores the project's own mTLS helper and dials `grpc.insecure_channel`, sending the shared secret and all goal payloads in cleartext with no path to enable TLS.
11. **`dashboard/api.py:2991` — Rename/Move-goal is dead on Postgres**: `retitle_goal`/`reparent_goal` reach into SQLite-only private internals and `?` placeholders, so they `AttributeError`/500 on the documented HA backend.
12. **`compaction/hybrid.py` — "shipped self-improving compaction" is orphaned**: a full bandit + logistic-regression picker that nothing in the execution graph ever calls; flipping the config flag changes no behavior.
13. **`safety/voice_safety.py` — documented inbound voice-injection screen has zero callers**: a "safety floor" that exists only on paper and in a passing unit test.
14. **`vector_store/weaviate_store.py` — "server-side vectorization" with no vectorizer**: collection created with `vectorizer=none`, so `add()` stores no vectors and `near_text()` cannot work; the only tests mock the entire module.

### 3. Claims vs reality

**Substantiated (16/24)** — and impressively so under reproduction: the 2,020-pack / 53-suite roster with 0-error/0-warning lint; the signed hash-chained audit log (with an honestly-disclosed local-key custody caveat); causal "provable learning" (real stratified ATE + permutation placebo + fail-closed trust gate); snapshot/rollback + hindsight; exactly-once zero-loss job processing (reproduced at 5,000 jobs × 48 processes); hard budget caps under concurrency; capability attenuate-only monotonicity (399,131 probes / 0 leaks reproduced exactly); the out-of-process model proxy; per-tenant envelope encryption + Postgres RLS that fails closed; encryption-at-rest by default; Sigstore keyless signing; the 514-skill library + agent factory; the live governance demo ($60k DENY / $6k REQUIRE-HUMAN / loop CAP / no self-approve); and the ~310K-LOC anti-wrapper thesis (with the fair note that ~28% is declarative pack TOML).

**Partial / overstated (8/24)** — real implementations with material caveats a partner must hear:
- **"Each invariant fault-injected at 1,000,000 iterations"** — fabricated; the actual loops are 1–5,000 (off by up to 200×). The invariants and full-roster coverage are real; the number is marketing fiction.
- **"8 packages on PyPI, installable today"** — false against the live index: names are reserved, zero release artifacts, nothing is `pip install`-able now.
- **Egress lock / "even prompt-injection can't move data out"** — application-layer only and opt-in; the shell/sandbox path escapes it. Real and valuable, but narrower than the absolute wording.
- **Confidential-compute "attestation"** — it's spoofable *indicator detection* (touch `/dev/sev-guest` and it flips true), not a verified hardware attestation report.
- **Per-call zero-trust token exchange** — genuine crypto, but a no-op on the default install (opt-in, fails open).
- **WORM erasure proof "across every store"** — the proof reuses the DSAR export, which doesn't cover the dreaming store, attachments, or LLM cache the erase path scrubs.
- **`proof-pack`** — real measured+signed bundle, but the literal command isn't registered and "shield results" silently skip on the wheel path.
- **STRESS_TEST.md scoreboard (13,476 / 10 failed / all gates green)** — optimistic: an independent run shows 14 failures (different ones) and 6 cosmetic ruff errors. The core dispatch/budget/authz/crypto guarantees do hold.

**Refuted: 0.** Nothing claimed was found to be wholly fabricated at the kernel level.

### 4. Systemic patterns

The recurring slop habits, by rough prevalence across 172 low / 73 medium / 13 high findings:

- **Misleading docstrings / overstated claims (79 findings)** — the dominant pattern: code that does *less* than its docstring or marketing says (PII redaction, "byte-for-byte" ports, "shipped" features that are orphaned, hardcoded compliance strings). This is the single biggest credibility liability because it's exactly what diligence greps for.
- **Reliability gaps (65)** — backend split-brain: features built and tested on SQLite that break on the documented Postgres/HA path (Rename/Move-goal, trust-tiering). The public-API discipline that protects the kernel isn't enforced at the dashboard/edge layer.
- **Swallowed exceptions (57)** — broad `except: pass`/return that turns safety gates fail-open (the RLS preflight is the worst instance). Pervasive enough to be a code-review standard worth adding.
- **Security divergences in ports (17)** — the Rust and Go reimplementations drop security behavior present in the Python source they claim to mirror (forged-pubkey defense, error scrubbing, TLS).
- **Fake features / theater / dead code (14)** — concentrated in second-tier subsystems (alternative sandboxes, alternative vector stores, learned-compaction, voice safety) where elaborate scaffolding exists but isn't wired in.
- **Simulated/weakened guarantees** — DP noise from a seedable non-crypto PRNG; "attestation" that's indicator presence. Low count but high reputational damage.

Crucially: **the kernel (`maverick-core` budget/audit/capability/governance) is largely clean of these patterns.** The slop clusters at the edges and in the prose.

### 5. Subsystem scorecard

| Subsystem / area | Quality | Notes |
|---|---|---|
| `maverick-core` kernel (agent loop, budget, audit, capability, governance, providers, cache, retry, replay, tenant) | **Enterprise** | The real moat; controls wired in, fault-injection + concurrency proven. |
| `maverick-dashboard`, `maverick-mcp`, `maverick-knowledge`, `maverick-shield` | **Enterprise** | Mostly solid; one high-sev backend split-brain in dashboard `api.py`. |
| Desktop/mobile/editor apps, extensions, SDK, benchmarks | **Enterprise** | Broad, clean surface area; low finding density. |
| `world_model_backends/postgres.py` | **Weak (high-sev)** | Trust-tiering inert, fail-open RLS gate — the worst single file. |
| `sandbox/` (firecracker), `vector_store/` (weaviate), `compaction/hybrid.py`, `safety/voice_safety.py`, `tools/dp_stats.py`, `donation.py` | **Weak** | Where the fake-feature / dead-control findings concentrate. |
| `rust/maverick-verify-audit`, `go/model-proxy` | **Weak (security divergence)** | "Faithful port" claims contradicted by dropped security behavior. |
| `compaction/`, `marketplace/`, `vector_store/`, `world_model_backends/`, `sandbox/`, `training/`, installer-cli | **Mostly solid** | Functional but with the medium-sev reliability/swallowed-error patterns. |

### 6. What to do before the meeting

Prioritized by credibility-leverage:

1. **Fix the pitch-deck numbers tonight.** Change every 1,118/26 to 2,020/53 in `ONE-PAGER.md` and `SEED-DECK.md`. This is a five-minute edit that removes the single most damaging "your own command refutes your own deck" moment. Non-negotiable.
2. **Delete or de-claim the fabricated "1,000,000 iterations" line** and the "8 packages installable today on PyPI" line. Replace with the true, still-impressive numbers ("property-fuzzed up to 5,000 iterations," "PyPI names reserved; install from source / via installer in alpha"). Don't let a partner catch a number that's off by 200× or a `pip install` that fails live.
3. **Pull the inert/contradicting controls out of the buyer-facing surface.** The hardcoded "passed the shield / signed audit" string (`worker_review.py:133`), the Postgres trust-tiering, and the fail-open RLS gate are the three that read as compliance theater in a SOC2/security lens. Either make them honest (inspect actual state) or remove the assurance text. The RLS fail-open is also a genuine data-safety bug — fix it to fail closed.
4. **Add `EXPERIMENTAL` / `roadmap` banners to the orphaned subsystems** (firecracker sandbox, weaviate store, hybrid compaction, voice safety) so a partner reads them as scaffolding-in-progress rather than shipped-but-broken. "Planned" is defensible; "documented as shipped, actually dead" is not.
5. **Reconcile the "byte-for-byte port" claims** in the Rust verifier and Go proxy — either restore the dropped security behavior (forged-pubkey defense, error scrubbing) or downgrade the docstring to "Python is the source of truth; this port covers the happy path." A security-divergent "faithful port" is the kind of thing a partner remembers.
6. **Prepare three honest talking points** you can volunteer before being asked: (a) the audit log is tamper-evident against anyone without host/key access, with an enterprise KMS path for true off-host anchoring; (b) egress-lock and per-call tokens are opt-in Enterprise-mode controls, not defaults; (c) confidential-compute is indicator-detection-plus-gate today, with real attestation on the roadmap. Disclosing these first converts "gotcha" risk into "this founder knows their threat model."

Net message for the founder: **the engineering is real and the kernel is strong — your exposure is almost entirely in prose that overshoots the code and in second-tier subsystems shipped before they were wired in.** Both are fixable before the meeting; the deck-vs-code number is the one you cannot leave unfixed.

---

## The confirmed high-severity findings, in detail

These 8 findings survived an independent skeptic's attempt to refute them. They are 
the ones to take seriously before the meeting. Each includes the verifier's reasoning.

### "Compaction v6 hybrid" learned strategy picker is dead code — never wired into any production path, yet docs say it shipped

- **File:** `packages/maverick-core/maverick/compaction/hybrid.py` (lines 1-431)
- **Category:** Theater (scaffolding, no impl) · **Verdict:** ✅ confirmed high (verifier confidence 0.9)

**Claim vs. reality.** Claims a shipped, ledger-learning, optionally model-trained strategy picker that adapts compaction to conversation shape from this instance's outcomes. Reality: the code is fully implemented and unit-tested but invoked by nothing in the running system; flipping `[compaction] hybrid=true` / `MAVERICK_COMPACTION_HYBRID=1` changes no behavior because no caller consults pick_strategy/HybridPicker.

**Why it's slop.** Elaborate, plausible-looking ML scaffolding (epsilon-greedy bandit + 300-step logistic regression trainer) that a founder could demo as 'self-improving compaction,' but it is orphaned. In due-diligence this is the textbook gap between a roadmap doc claiming 'shipped' and code that is not in the execution graph.

**Evidence.**
```
Whole module (extract_features, bucket_key, HybridPicker, the pure-Python logistic fit() trainer, pick_strategy) is referenced only by tests/test_compaction_hybrid.py. The live agent compaction path (agent.py:2260 `from .compaction.plugins import compact_with`) routes through compaction/plugins.py -> compaction/strategies.py, which never imports hybrid. Meanwhile docs/ROADMAP.md:133 says "compaction v6 hybrid shipped" and docs/FEATURES.md:2162 describes it as an active "strategy picker learned from this deployment's own outcomes."
```

**Enterprise fix.** Either wire HybridPicker into compaction/strategies.compact_with_strategy (gate selection on enabled()), or, if not ready, demote the ROADMAP/FEATURES claims from 'shipped/active' to 'experimental, not wired' and mark the module accordingly. Do not present unreferenced code as a live capability.

> **Verifier (skeptic):** Independently reproduced. The hybrid module's public surface (pick_strategy, HybridPicker, fit, enabled) is referenced by NOTHING outside hybrid.py itself and tests/test_compaction_hybrid.py. Grep for `compaction.hybrid` / `from .hybrid` / `pick_strategy` / `HybridPicker` over all non-test .py in the repo (including apps/ and sdks/) returns zero hits beyond the module's own internal log strings.

The live compaction path is exactly as the auditor cited: agent.py:2260 `from .compaction.plugins import compact_with` -> plugins.py `compact_with` -> `_StrategyAdapter` -> strategies.py `compact_with_strategy`. Both plugins.py and strategies.py hardcode the strategy universe as `("learned", "multimodal", "streaming", "graph")` (plugins.py:112 `for _name in (...)`; strategies.py:29 `STRATEGIES = (...)`). "hybrid" is not in either tuple and is not registrable via `[context] compaction_strategy`. There is no code path from the agent loop into hybrid.py.

The `[compaction] hybrid` / `MAVERICK_COMPACTION_HYBRID` knob is read ONLY by hybrid.enabled() (hybrid.py:61,66), which is consulted ONLY by pick_strategy()/HybridPicker — neither of which has a production caller. So flipping the knob changes no behavior, exactly as claimed.

Docs overstate it: ROADMAP.md:133 "compaction v6 hybrid shipped (`compaction/hybrid.py`, ledger-learned strategy picker, fail-open)" and FEATURES.md:2162 "Compaction v6 hybrid (`compaction/hybrid.py`): the strategy picker learned from this deployment's own outcome


### retitle_goal / reparent_goal reach into SQLite-only WorldModel internals and 500 under the Postgres backend

- **File:** `packages/maverick-dashboard/maverick_dashboard/api.py` (lines 2991-3053)
- **Category:** Reliability gap · **Verdict:** ✅ confirmed high (verifier confidence 0.9)

**Claim vs. reality.** The endpoints purport to rename / re-parent a goal on whatever backend `_world()` returns. `_world()` (in _shared.py) explicitly returns a PostgresWorldModel when `is_postgres_configured()`. But PostgresWorldModel (world_model_backends/postgres.py) defines NO `_writing`, `_read_all`, or `_read_one` (grep confirms zero matches) and uses `%s`, never `?`, placeholders. So on a Postgres deployment these two endpoints raise AttributeError on `w._writing()` / `w._read_all()` before any SQL runs — the graph-editor Rename and Move-goal features are simply dead there.

**Why it's slop.** The dashboard layer bypasses the world-model's public domain API and writes raw SQL with SQLite-only private internals and SQLite-only `?` placeholders, against a goals table whose schema and placeholder dialect it does not own. open_world()'s docstring only guarantees the PUBLIC surface mirrors across backends. The feature works in dev (SQLite) and is broken in the documented HA/Postgres deployment — exactly the kind of split-brain the rest of _shared.py was written to prevent.

**Evidence.**
```
retitle_goal (3008-3013): `with w._writing() as conn: conn.execute("UPDATE goals SET title = ?, updated_at = ? WHERE id = ?", ...)`; reparent_goal (3042): `for r in w._read_all("SELECT id, parent_id FROM goals")` then (3049-3053) `with w._writing() as conn: conn.execute("UPDATE goals SET parent_id = ?, ...", ...)`. The retitle docstring (2994-2998) even admits: "The world model has no title-update method ... so this updates the row through the world's write lock".
```

**Enterprise fix.** Add public `set_goal_title(goal_id, title)` and `reparent_goal(goal_id, parent_id)` (plus a cycle/descendant helper) to the WorldModel ABC and implement them in BOTH the SQLite and Postgres backends with each backend's own placeholder dialect and at-rest sealing; have api.py call those public methods instead of `_writing`/`_read_all`/raw SQL.

> **Verifier (skeptic):** Independently reproduced the full call path; the auditor's claim-vs-reality holds.

THE ENDPOINTS (api.py:2991-3053): retitle_goal does `with w._writing() as conn: conn.execute("UPDATE goals SET title = ?, updated_at = ? WHERE id = ?", (_enc_field(title[:200]), time.time(), goal_id))`. reparent_goal does `w._read_all("SELECT id, parent_id FROM goals")` then `with w._writing() as conn: conn.execute("UPDATE goals SET parent_id = ?, ... WHERE id = ?", ...)`. Both use SQLite `?` placeholders and the private `_writing`/`_read_all` internals.

BACKEND RESOLUTION: `w = _world()`. In dashboard `_shared.py:99-106`, `_world()` does `if is_postgres_configured(): cached = open_world(); return cached`. `open_world()` (world_model.py:2595-2598) does `if is_postgres_configured(): from .world_model_backends import open_postgres_world; return open_postgres_world()`, which (postgres.py:3128-3130) does `return PostgresWorldModel(dsn=dsn)`. So under the documented HA Postgres backend, `w` IS a PostgresWorldModel.

THE MISSING INTERNALS: Grep for `_writing|_read_all|_enc_field` across the entire PostgresWorldModel class (postgres.py:694-3128) returns only a module-level `_enc_field` import at line 653 — ZERO `_writing` and ZERO `_read_all` methods. The full method list (lines 701-2327+) has create_goal/get_goal/set_goal_status/etc. but no _writing/_read_all. open_world's own docstring says the Postgres backend's "public surface mirrors WorldModel" — only the PUBLIC API is guaranteed; these endpoi


### Trajectory donation claims a PII-redaction step that does not exist; only secret-shaped strings are scrubbed

- **File:** `packages/maverick-core/maverick/donation.py` (lines 10-13, 255-257)
- **Category:** Misleading name / docstring / comment · **Verdict:** ✅ confirmed high (verifier confidence 0.85)

**Claim vs. reality.** Purports: donated trajectory text (uploadable when donate_text=true) is run through both a secret-scrubber AND a PII-redaction step before it leaves the user's machine. Reality: only a regex secret-scrubber runs; personal data (names, emails, addresses, SSNs, raw prompt/result transcript content) is left intact in the outbox JSON and in any later `maverick donate-upload`.

**Why it's slop.** This is a privacy assurance in a feature whose entire value proposition is shipping user agent-trajectories off-box. A diligence partner reading the assurance and then grepping the code finds the PII step is vapor, which directly undermines the data-governance story. The promise vs. behaviour gap is exactly what an audit looks for.

**Evidence.**
```
Module docstring (lines 10-13): "2. **Client-side scrubbed.** Every text field passes through the secret-scrubber + a PII-redaction step BEFORE landing in the outbox." The only transformation in write_record is: `payload = _scrub_payload(asdict(record))` (line 257), and _scrub_payload (lines 133-146) recurses into strings calling `scrub(value)` from maverick.secrets, whose own docstring is "Secret scrubber for logs + error messages" and only redacts API keys / tokens / PEM blocks / URL credentials to [REDACTED:<kind>]. There is no call to any PII redactor anywhere in donation.py (grep for pii/email/redact/secret_detector finds only the docstring line 11). Even maverick.safety.secret_detector, which donation.py does NOT use, states "This is not a replacement for a real DLP tool" and matches only credentials.
```

**Enterprise fix.** Either (a) implement an actual PII-redaction pass (emails, phone numbers, names via NER or at minimum regex for emails/phones/credit-cards/SSNs) and run it inside _scrub_payload before write, or (b) if PII redaction is deliberately deferred, change the docstring to state only secret-pattern scrubbing is applied and that donate_text=true may export raw PII, plus surface that warning in the installer wizard opt-in. Do not leave the stronger claim in the shipped docstring.

> **Verifier (skeptic):** Independently reproduced. The docstring (donation.py lines 10-13) promises: "Every text field passes through the secret-scrubber + a PII-redaction step BEFORE landing in the outbox." But the only privacy code in the module is `from .secrets import scrub` (line 38), and write_record applies exactly one transform before persisting: `payload = _scrub_payload(asdict(record))` (line 257). `_scrub_payload` (lines 133-146) recurses strings to `scrub(value)`. I read secrets.py: `scrub`'s `_PATTERNS` are exclusively SECRET-shaped (private_key PEM, url_credentials, anthropic/stripe/openai/google/aws keys, github/slack tokens, bearer headers, KEY=value env secrets, JWT, URL query secrets). There is NO pattern for names, emails, phone numbers, or SSNs. So a raw email/SSN/transcript in task_brief_text passes through scrub untouched. No PII redactor is imported or called anywhere in donation.py.

The codebase proves a real PII facility exists and was simply not wired in here: `maverick.privacy` (anonymize_dict/anonymize_field, docstring "email addresses, phone numbers, SSNs (via pii_detector)") and `safety.secret_detector.redact` (parity test asserts it emits `[REDACTED:ssn]` and `[REDACTED:email]`). donation.py imports none of them — it could have, and the docstring claims it does.

I traced both write_record call sites (orchestrator.py:1419 and :1605). Both populate `task_brief_text=(goal.title + "\n" + (goal.description or ""))` — raw user-authored goal text that can contain PII — and h


### gRPC dispatcher sends bearer token over a hardcoded insecure (plaintext) channel, ignoring the project's own client-TLS helper

- **File:** `packages/maverick-core/maverick/grpc_dispatcher.py` (lines 82-95)
- **Category:** Security · **Verdict:** ✅ confirmed high (verifier confidence 0.85)

**Claim vs. reality.** The module docstring presents GrpcDispatcher as the production seam for moving goal execution to a remote worker over gRPC, with a `[grpc_dispatch] token` that 'must match the worker's [grpc] token'. In reality the client unconditionally dials `grpc.insecure_channel(self.target)` and attaches that shared-secret token as `authorization: Bearer ...` metadata, so the credential and all goal payloads cross the network in cleartext, with no code path to enable TLS even when the operator sets `[grpc] tls_required`.

**Why it's slop.** The sibling module maverick/grpc_tls.py already provides `channel_credentials(section)` (grpc.ssl_channel_credentials with CA pinning + mTLS) and a `tls_required` fail-closed posture, and the gRPC server (grpc_api/server.py:399 bind_port) uses it. The dispatcher silently bypasses all of it. An enterprise worker configured to require TLS cannot be dialed securely by this dispatcher, and a static bearer token sent over plaintext is trivially sniffable on the wire — exactly the kind of gap a due-diligence partner probes.

**Evidence.**
```
def _build_stub(self):
    if self._stub_factory is not None:
        return self._stub_factory()
    import grpc
    from .grpc_api.server import _load_stubs
    pb2, pb2_grpc = _load_stubs()
    channel = grpc.insecure_channel(self.target)
    return pb2_grpc.MaverickStub(channel), pb2

def _metadata(self):
    if self.token:
        return [("authorization", f"Bearer {self.token}")]
    return []
```

**Enterprise fix.** Build the channel via grpc.secure_channel(self.target, grpc_tls.channel_credentials('grpc')) when TLS is enabled/required, falling back to insecure only when grpc_tls allows it (loopback / explicit MAVERICK_ALLOW_INSECURE_GRPC), and refuse to attach a bearer token over a non-loopback insecure channel. Mirror the fail-closed logic in grpc_tls.tls_required so a configured-secure worker is never dialed in plaintext.

> **Verifier (skeptic):** Independently reproduced. grpc_dispatcher.py:82-90 (_build_stub) unconditionally does `channel = grpc.insecure_channel(self.target)` — it never imports grpc_tls, never calls channel_credentials(), and never checks tls_required(). Then _metadata() (lines 92-95) attaches `[("authorization", f"Bearer {self.token}")]`, so the static bearer crosses that plaintext channel. The [grpc_dispatch] config block exposes only target/token/timeout_s (constructor lines 65-77) — there is genuinely NO config knob to enable TLS, confirming "no path to enable TLS."

The decisive comparison the finding rests on is accurate. The established sibling client path, federation.py:954-969, does it correctly: `creds = channel_credentials("federation")`; `if creds is not None: channel = grpc.secure_channel(...)`; and crucially FAILS CLOSED: `if tls_required("federation"): raise FederationError("refusing to dial peer ... without TLS")`, only falling back to insecure_channel when TLS is neither configured nor required. The dispatcher omits all three behaviors. The server it dials (grpc_api/server.py serve() -> grpc_tls.bind_port(server, address, "grpc")) fully supports TLS/mTLS and even fail-closes on a plaintext non-loopback bind (grpc_tls.py:168-174) — so the worker can run [grpc] tls=true while this client cannot reach it securely at all. grpc_tls.py's own docstring states the threat model the dispatcher reintroduces: "the federation client dialed insecure_channel — bearer tokens ... crossed the wire in 


### Weaviate adapter claims server-side vectorization but creates a vectorizer-less collection (near_text cannot work)

- **File:** `packages/maverick-core/maverick/vector_store/weaviate_store.py` (lines 1-16,86-91,121-141)
- **Category:** Fake / hollow feature · **Verdict:** ✅ confirmed high (verifier confidence 0.85)

**Claim vs. reality.** Purports to be an embedding-backed semantic store that vectorizes text server-side via Weaviate's vectorizer module. In reality the collection is created with weaviate-client v4's default (vectorizer=none), so add() stores objects with no vectors and near_text() has no module to embed the query against — the core semantic-search capability is not wired.

**Why it's slop.** An exported, roadmap-listed enterprise capability whose central promise (server-side embedding) is unimplemented; the only tests (test_weaviate_store.py) mock the entire weaviate module and assert create is called with just a name, so they can never surface that a real backend would reject near_text without a vectorizer.

**Evidence.**
```
Docstring (l.12-14): "Vectorization is delegated to Weaviate's configured vectorizer module, so the collection embeds text server-side". But _ensure_collection (l.88-89) does: `self._client.collections.create(self._collection)` with NO vectorizer_config; then query() (l.125) calls `coll.query.near_text(query=text, ...)`.
```

**Enterprise fix.** Pass an explicit vectorizer/vector config to collections.create (e.g. Configure.Vectorizer.text2vec_* or a named vectorizer the deployment runs), make it configurable, and add at least one integration test against a real embedded Weaviate so a vectorizer-less collection fails loudly instead of shipping a dead semantic path.

> **Verifier (skeptic):** Independently reproduced the auditor's claim by reading the file and comparing against the Qdrant adapter the docstring invokes as its analog.

DOCSTRING CLAIM (lines 12-13): "Vectorization is delegated to Weaviate's configured vectorizer module, so the collection embeds text server-side — the same 'no extra wiring' stance as the Qdrant adapter's fastembed integration."

REALITY: _ensure_collection (line 89) calls `self._client.collections.create(self._collection)` with ONLY the class name — no `vectorizer_config`. In weaviate-client v4, collections.create with no vectorizer_config defaults to Configure.Vectorizer.none() (no module). add() (lines 116-119) passes only `properties` and `uuid`, never a precomputed vector — so with vectorizer=none, objects are stored WITHOUT vectors. query() (line 125) then calls `coll.query.near_text(query=text, ...)`, which requires a server-side vectorizer module to embed the query text; against a vectorizer-less collection near_text errors at the backend. A repo-wide grep confirms the ONLY "vectorizer" tokens in the whole vector_store/ package are the docstrings — there is no vectorizer_config call anywhere.

THE QDRANT ANALOGY IS FALSE, which is the load-bearing misdirection. QdrantStore genuinely works without explicit vector config because qdrant-client's client.add/client.query ship built-in fastembed and embed CLIENT-side (qdrant_store.py lines 14-15, 132, 148; reset() recreates with get_fastembed_vector_params(), line 201). Weaviate's a


### Unconditional, hardcoded governance/compliance claim surfaced to buyers regardless of actual shield/audit state

- **File:** `packages/maverick-core/maverick/worker_review.py` (lines 133-136)
- **Category:** Misleading name / docstring / comment · **Verdict:** ✅ confirmed high (verifier confidence 0.82)

**Claim vs. reality.** Purports that EVERY action in the department review passed the shield and is recorded in a signed, tamper-evident audit log. In reality this string is a constant returned for any review; kernel rule 1 (CLAUDE.md) and the codebase explicitly run WITHOUT the shield and fail open with a warning, and audit signing can degrade to unsigned (audit/writer.py resolves signing conditionally; compliance-posture CI references 'audit_log: no_crypto' / UNSIGNED). The note never inspects whether the shield was installed or whether signing actually held for the counted actions.

**Why it's slop.** It is a compliance assurance stated as fact, rendered verbatim into the buyer-facing dashboard workforce page (maverick-dashboard/templates/workforce.html:114). A partner in due-diligence could deploy without agent-shield (a stated, supported posture) and still see the product assert in writing that every action 'passed the shield' and is 'signed/tamper-evident' — an unsubstantiated control claim, the kind that fails a SOC2/security audit.

**Evidence.**
```
"governance_note": (
    "Every action counted here passed the shield's input/tool/output "
    "checks and is recorded in the signed, tamper-evident audit log."
),
```

**Enterprise fix.** Derive the note from actual state: check whether the shield package is loaded/active and whether audit signing is enabled (e.g. via compliance_profiles.requires_floor(FLOOR_AUDIT_LOG) plus the resolved signing flag), and emit the precise posture ('shield active; audit signed' vs 'shield not installed (fail-open); audit unsigned'). Never assert a control that may be off.

> **Verifier (skeptic):** Read worker_review.py:116-137 directly. review() composes a dict whose 'governance_note' is a hardcoded constant: "Every action counted here passed the shield's input/tool/output checks and is recorded in the signed, tamper-evident audit log." The function inspects NOTHING about shield backend, the audit-signing extra, or per-row signature state before emitting it — it only assembles department/delivery/authority/learning and appends the string unconditionally. The render claim is confirmed: workforce.html:114 outputs `esc(r.governance_note)` verbatim into the per-department performance-review modal shown to buyers.

I tried hard to refute the auditor's "reality" claim and instead corroborated both halves from the repo itself: (1) Shield absence/fail-open — ARCHITECTURE.md:66 ("If agent-shield is not installed, Maverick falls back to ~20 high-impact built-in rules") and benchmarks/security/corpus.py:123 ("The shield fails open: if a backend errors, the scan returns allow and logs at ERROR"), plus CLAUDE.md kernel rule 1 / AGENTS.md:29 ("Kernel must run without agent-shield — fail open with a warning"). So an action can be counted without passing the full shield, or any check at all. (2) Audit signing degrades to unsigned — wizard.py:1532 ("Needs the [audit-signing] extra; falls back to unsigned if absent") and control_plane.py:151,191-192 which has a first-class status branch returning {"status": "unsigned", ..., "signed": False} when "every row flagged unsigned." Thus the lo


### Memory Guard trust-tiering (OWASP ASI06) is silently defeated on the Postgres backend

- **File:** `packages/maverick-core/maverick/world_model_backends/postgres.py` (lines 2096-2100)
- **Category:** Fake / hollow feature · **Verdict:** ✅ confirmed high (verifier confidence 0.82)

**Claim vs. reality.** Purports to return each fact's real trust tier so memory_guard.filter_facts() can drop poisoned/external memory below min_recall_trust (orchestrator.py:464-465 feeds this directly into the guard). Reality: it hardcodes tier 3 (first-party/operator) for EVERY fact, so the trust floor never fires on Postgres — an externally-poisoned fact that should be tier 0 and dropped is surfaced to the agent as fully trusted.

**Why it's slop.** The live PG `facts` table (SCHEMA lines 92-101) has no source/trust_tier/sensitivity columns at all, so upsert_fact (lines 2014-2083) accepts source/trust_tier/sensitivity kwargs but persists them nowhere on the live row (only into fact_history, and only when [memory] temporal is enabled — off by default). The read side then fabricates tier 3. The comment frames this as 'fail-open', but failing open on an anti-memory-poisoning control means admitting untrusted memory — the opposite of safe for a security control. The enterprise/HA backend therefore ships with this ASI06 control inert.

**Evidence.**
```
def get_facts_with_trust(self) -> dict[str, tuple[str, int]]:
    # Provenance columns are sqlite-first; treat every Postgres fact as
    # first-party (3) so the Memory Guard fail-opens (keeps them) rather
    # than silently dropping memory it can't tier.
    return {k: (v, 3) for k, v in self.get_facts().items()}
```

**Enterprise fix.** Add source/trust_tier/sensitivity columns to the PG `facts` table (a new migration), persist the trust_tier/source/sensitivity kwargs in upsert_fact's live INSERT, and return the real stored tier from get_facts_with_trust (defaulting only legacy NULL rows to 3). Until then, the guard's behavior must be identical across backends or the deployment must refuse to advertise ASI06 coverage on Postgres.

> **Verifier (skeptic):** Independently reproduced. The cited code (postgres.py:2096-2100) is exactly: `def get_facts_with_trust(self) -> dict[str, tuple[str, int]]: ... return {k: (v, 3) for k, v in self.get_facts().items()}` — every fact hardcoded to tier 3 (FIRST_PARTY, the MOST trusted). The live Postgres `facts` table schema (lines 93-98 + `ALTER TABLE facts ADD COLUMN ... source_episode_id`/tenant_id) has NO trust_tier column, and `upsert_fact` (lines 2075-2083) writes trust_tier only into `fact_history` (and only when temporal memory is enabled), never onto the live `facts` row it later reads. So the live row genuinely cannot recover a real tier.

This DIVERGES from the SQLite original: world_model.py:1851-1857 selects the real `trust_tier` column and returns `(value, int(trust_tier))`. test_temporal_facts.py:84-85 proves SQLite round-trips a poisoned tier-0 fact as `("x", 0)`, and test_server.py:500-508 proves an MCP-client fact is stored/recalled as TOOL tier `("ship it", 1)` precisely "so the Memory Guard tiers on this." The same facts on Postgres come back as tier 3.

The control is really wired and really defeated: orchestrator.py:464-465 calls `_facts_meta = world.get_facts_with_trust(); facts = _mg.filter_facts(_facts_meta)` on the brief-assembly hot path. filter_facts (memory_guard.py:215-237) drops any fact whose tier is below `min_recall_trust()` (default TOOL=1, memory_guard.py:94-102). With every Postgres fact reported as tier 3, the floor NEVER fires: a tier-0 EXTERNAL/inbound fact


### Go port returns raw error strings to client, dropping the Python original's mandatory secret-scrubbing

- **File:** `go/model-proxy/handle.go` (lines 38-43)
- **Category:** Security · **Verdict:** ✅ confirmed high (verifier confidence 0.7)

**Claim vs. reality.** proxy.go:9-11 states the decision logic is a "faithful, byte-for-byte port of the Python original." Python's handle() (model_proxy.py:233-244) wraps BOTH error paths in scrub(str(e)) — explicitly because "a credential-shaped string in a URL/error can't leak into either sink" — and the 502 body is f"proxy error: {safe}". The Go port returns hostErr.Error() and err.Error() completely raw, with no scrub() equivalent, so the bodies are NOT byte-identical and the security-critical redaction is gone.

**Why it's slop.** This is the inference data path holding a real provider key. A net/http upstream error can embed the upstream URL or response detail; if that ever carries a credential-shaped token the Go proxy ships it verbatim to the (potentially compromised) agent client, while the Python original it claims to mirror deliberately redacts it. The divergence undermines the stated security model and the central "byte-for-byte" claim.

**Evidence.**
```
if hostErr, ok := err.(*HostNotAllowedError); ok { // blocked host / bad request
			return 403, cloneTextPlain(), []byte(hostErr.Error())
		}
		return 502, cloneTextPlain(), []byte("proxy error: " + err.Error())
```

**Enterprise fix.** Port maverick.secrets.scrub to Go (or call it) and apply it to both error bodies before returning, matching Python: return scrubbed hostErr.Error() for the 403 and "proxy error: "+scrub(err.Error()) for the 502. Add a parity fixture case that drives an error string containing a bearer-shaped token through both implementations.

> **Verifier (skeptic):** The divergence is real and independently reproduced. Python handle() (model_proxy.py:233-244) wraps BOTH error paths in scrub(): line 237 `return 403, ..., scrub(str(e)).encode("utf-8")` and lines 242-244 `safe = scrub(str(e)); ... return 502, ..., f"proxy error: {safe}".encode()`. The Go port (handle.go:38-43) returns both raw: `return 403, cloneTextPlain(), []byte(hostErr.Error())` and `return 502, cloneTextPlain(), []byte("proxy error: " + err.Error())`. I grep'd the entire go/model-proxy/ directory: there is NO scrub equivalent anywhere, and the listener (server.go:82-88) writes Handle's bytes straight to `w.Write(out)` with no scrubbing layer between Handle and the client. So the control is genuinely dropped on a component whose stated purpose (proxy.go:1-15) is to hold the provider API key out of the agent's address space. The auditor's faithful-port claim is also accurate: proxy.go:9-11 asserts byte-for-byte parity.

Two caveats that temper the auditor's framing but do not refute it: (1) The 403 / HostNotAllowedError path is not actually a leak risk — errors.go:16-23 builds the message from hostnames and config allow-hosts only (`upstream host 'h' not in allow-set [...]`), never the key, so scrubbing it is a no-op. The auditor overstated by treating both paths as equivalently dangerous. (2) The material path is the 502 / err.Error(): this error comes from BuildRequest or HTTPUpstream.Do (a Go *url.Error from http.Client.Do). The injected credential is an Authorization/


---

## Reviewed-down and dismissed (for completeness)

**🔻 downgraded → medium: Documented inbound transcript-injection screen has zero production callers (dead safety control)** — `packages/maverick-core/maverick/safety/voice_safety.py`  
The core factual claim is independently confirmed: scan_transcript() (voice_safety.py:43-69, exported in __all__ line 99) is fully implemented but has ZERO production callers. Grep across the whole repo for `scan_transcript` returns only: its definition, the __all__ export, and tests/test_voice_image_safety.py (4 call sites). No production module imports it.

The inbound voice path provably bypasses it. In live_mic.py:run_live_mic the utterance is taken raw — `utterance = (transcriber(chunk) or "").strip()` (line 92) — then handed straight to `match_utterance(grammar, utterance)` (line 95) with no screen. In voice_only.py:VoiceOnlySession.run the utterance is whitespace-normalized, stop-phra

**🔻 downgraded → low: Firecracker microVM 'isolation' runs commands against an empty rootfs — the agent's workspace is never copied into the VM** — `packages/maverick-core/maverick/sandbox/firecracker.py`  
The auditor's literal code observations about lines 189-242 (`_firectl`) are accurate: args are built as `["firectl","--kernel",str(kernel),"--root-drive",str(rootfs),...]` then `args += ["--","/bin/sh","-c",cmd]` (lines 207-227); there is genuinely no reference to `self.workdir` in `_firectl` (the only `self.workdir` use is line 260 inside `_docker_fallback`); and the docstring at lines 149-159 admits "copy workdir in via vsock... For now (scaffold)". So the workspace-transfer gap is real.

But the high-severity "fake_feature / user gets confidently-wrong runs against a blank VM" framing does NOT hold, because the path is gated to fail CLOSED rather than fabricate a successful run:
1. The m

**🔻 downgraded → low: Differential-privacy noise is seedable and uses a non-crypto PRNG, defeating the privacy guarantee** — `packages/maverick-core/maverick/tools/dp_stats.py`  
The auditor's load-bearing claim is a misread; the category (fake_feature) and high severity do not hold, but a minor real hardening concern remains, so I downgrade rather than fully refute.

FACTS CONFIRMED (auditor accurate on these): dp_stats.py:16 `import random`; line 22-28 `_laplace` uses `u = rng.random() - 0.5`; line 36 `rng = random.Random(seed)`; line 87 schema exposes `"seed": {"type": "integer", ...}`; test_dp_stats.py:15-18 pins `seed=7` reproducibility. A sibling tool maverick/tools/differential_privacy.py uses the identical `random.Random(seed if isinstance(seed,int) else None)` pattern — this is a consistent design choice, not a divergent port.

WHY THE HEADLINE IS REFUTED ("

**🔻 downgraded → low: Rust verifier trusts any lone <key_id>.pub, dropping the Python source's forged-pubkey defense** — `rust/maverick-verify-audit/src/lib.rs`  
The auditor's raw technical observation is correct: a real divergence exists. Python verify_chain's keys-dir path (signing.py:619-636) implements a forged-pubkey defense — it trusts a .pub ONLY when the private .key sibling exists OR an .injected marker is present: `pub_path, priv_path = _key_paths_for_id(key_id); if pub_path is None or not pub_path.exists(): return None; marker = _injected_marker_for_id(key_id); if not priv_path.exists() and (marker is None or not marker.exists()): return None`. The Rust load_key_from_dir (lib.rs:238-245) has NO such check: `let pub_path = dir.join(format!("{key_id}.pub")); let bytes = std::fs::read(pub_path).ok()?; load_verifying_key(&bytes)`. Both Python 

**❌ refuted: RLS NULL-tenant data-safety preflight is swallowed, then FORCE RLS runs anyway** — `packages/maverick-core/maverick/world_model_backends/postgres.py`  
The auditor's literal flow is correct (preflight raises -> caught at line 835 -> return -> _apply_rls runs), but its load-bearing claim-vs-reality ("the swallow causes the exact action the gate exists to prevent: silently hiding/freezing NULL-tenant rows") is wrong. Two facts refute it:

(1) The NULL-tenant hazard is detected on preflight's SUCCESS path, not its exception path. pg_rls.preflight (pg_rls.py:67-101) runs `SELECT count(*) FROM {t} WHERE tenant_id IS NULL` and returns a clean integer count; NULL rows never raise. The gate then collects offenders from `report["tables"][t]["null_tenant_rows"]` and RAISES a RuntimeError refusing boot (postgres.py:838-851). So the dangerous condition

---

## Claims vs. reality — full table

The capability claims a due-diligence partner would probe, each checked against the code. **16 of 24 fully substantiated; 8 partial/overstated; none outright false at the kernel level.**

| Status | Claim | What the code actually shows |
|---|---|---|
| 🟡 Partial / overstated | Roster-wide governance invariant suite verifies SIX invariants across ALL 2,020 packs, each fault-injected at 1,000,000 iterations with a non-vacuous control. | The substance of the claim is genuinely delivered: six distinct, real, passing governance invariant suites cover the full 2,020-pack roster, each with a demonstrably non-vacuous fault-injection control (empirically confirmed by mutating attenuate() and watching the control detect the escalation). This is real engineering, not stubs. However, the specific qua |
| 🟡 Partial / overstated | maverick proof-pack emits an Ed25519-signed evidence bundle (governance guarantees + reliability cert + performance SLA + shield results), verifiable offline. | This is a genuinely real, working artifact — not theater. The decisive test for the "static template vs measured" concern is unambiguous: the perf-SLA and reliability numbers are computed at runtime (I observed machine-specific p95 latencies and an 88.8% drill success rate), persisted into the manifest, and protected by a real Ed25519 signature whose verific |
| 🟡 Partial / overstated | Egress lock / air-gap: 'even a successful prompt-injection can't move data out of your boundary'; runs fully offline with no required egress. | This is not theater — it is a substantial, well-designed, tested control that genuinely blocks the two highest-value Python exfiltration paths (the LLM call itself and every built-in HTTP tool/connector), is fail-closed by construction (cloud providers, off-box local endpoints, and IMDS all denied; failover can't escape it), and fires before any data leaves  |
| 🟡 Partial / overstated | Per-call zero-trust token exchange: each tool call exchanges the run-long grant for a freshly minted, single-tool-scoped, 30s, single-use, Ed25519-signed token, so a mid-run compromise can wield only  | This is a genuine, non-theatrical implementation: real Ed25519 signing/verification, real per-tool attenuation, real 30s TTL, real single-use replay cache, and it is actually invoked before tool dispatch with a real audit row recorded — not a stub. I verified this both by reading the wired-in call sites and by running the crypto end-to-end. It is NOT hollow. |
| 🟡 Partial / overstated | WORM audit export to S3 Object-Lock (COMPLIANCE/GOVERNANCE) making the historical trail immutable (not just tamper-evident), with `maverick audit worm verify` proving every closed day-file is durably  | This is a genuine, working implementation — not theater. The S3 Object-Lock integration uses the correct boto3 put_object parameters (ObjectLockMode COMPLIANCE/GOVERNANCE + retain-until), s3 is a real distinct provider (not a local mirror relabeled), and `worm verify` actually re-fetches and re-hashes objects rather than trusting the manifest, so "durably sh |
| 🟡 Partial / overstated | Confidential-compute attestation: detects whether the process runs inside AMD SEV-SNP / Intel TDX hardware confidential VMs and can gate deployment on hardware memory encryption (exits non-zero when n | The code is real, wired into `maverick confidential-compute`, and tested — the deployment gate (non-zero exit when not confidential) genuinely works, and there is a thoughtful security distinction: raw AMD SEV CPU capability flags are deliberately NOT accepted as guest proof, because a host/container can expose them without protecting this process. So this i |
| 🟡 Partial / overstated | Self-hosted / air-gapped with no hyperscaler dependency and no telemetry; 8 packages on PyPI, native installers for Win/macOS/Linux, GitHub Action, all installable today (alpha). | Split result. The CORE self-host promise — no telemetry, no required egress, no hyperscaler dependency — is substantiated in real code: trajectory donation is opt-in/default-OFF and only ever writes to a local outbox (the upload path is an unimplemented docstring TODO), plugin telemetry is a local-only file tally, the dashboard analytics widget is same-origi |
| 🟡 Partial / overstated | STRESS_TEST.md claims the full 13,673-test suite runs 13,476 passed / 10 failed and that all 10 CI gates plus 7 concurrency/chaos/fuzz campaigns held with 'zero violations.' | This is a substantially real, working stress harness — not theater — but the headline numbers do not reproduce exactly, so it is partial rather than substantiated. What is genuinely real: the suite collects cleanly (13,896 tests, 0 import errors once the env matches post-create.sh) and passes 13,663; all seven concurrency/chaos/fuzz campaigns are substantive |
| ✅ Substantiated | Internal inconsistency on the headline number: investor pitch claims '1,118 least-privilege specialist packs across 26 suites' while the README/FEATURES/code claim 2,020 packs across 53 suites. The on | The asserted facts check out exactly. The code is the ground truth: `available_domains()` returns 2,020 real (non-stub) packs and `suite_for()` resolves them into 53 distinct suites, matching README.md and docs/FEATURES.md verbatim, and matching the raw on-disk file count of 2,020. The investor-facing pitch/ONE-PAGER.md and pitch/SEED-DECK.md instead state 1 |
| ✅ Substantiated | "2,020 prebuilt specialists across 53 business suites … 0 errors, 0 warnings" via maverick domains-lint; every pack has a least-privilege tool envelope, risk ceiling, and hard prohibited-use refusals. | The claim is backed by real, working, enforcing code that genuinely delivers what the README/FEATURES assert. I independently reproduced every headline number: 2,020 packs, 53 suites, 0 lint errors AND 0 lint warnings, and the audited "0 drafting agents can reach a state-mutator" invariant. Critically (the partner's live-run concern), the lint is a substanti |
| ✅ Substantiated | Signed, hash-chained, append-only audit log with offline verification (maverick audit verify); altering one audited row is caught, leaving a tamper-evident receipt. | This is a genuine, working tamper-evidence implementation, not a stub: signatures are actually verified, mid-chain edits/reorders/deletions are all caught, the CLI gates CI with a non-zero exit, and a second signed ledger covers whole-file deletion. It substantively delivers the headline claim. The ONE-PAGER demo line ("altering one audited row is caught --  |
| ✅ Substantiated | Causal 'provable learning' flywheel: triages failures by causal impact using stratified ATE with confidence intervals, placebo refutation, and a trustworthiness gate; every causal guardrail must survi | This is genuine causal inference, not marketing over a heuristic. The decisive question — is "stratified ATE + placebo" real statistics, and does a failing placebo actually block promotion — resolves yes on both. The stratified estimator is the textbook subclassification/g-formula adjustment (per-stratum difference of means, size-weighted, positivity-enforce |
| ✅ Substantiated | Closed audited learning loop with snapshot + rollback and a per-cycle signed audit row; maverick hindsight detects if learning ever regressed by replaying past goals against prior snapshots. | Every component of the claim is backed by real, working, test-covered code. Snapshot/rollback is not theater: it copies actual store files and atomically restores them, verified by a dedicated full-revert test that reads back snapshot bytes and confirms post-snapshot creations are deleted. The "signed audit row" uses real Ed25519 + SHA-256 hash-chaining, and |
| ✅ Substantiated | Exactly-once, zero-loss out-of-process job processing proven under concurrency: 5,000 jobs across 48 real OS processes with 0 duplicates / 0 lost, plus a CI gate (control_data_plane_soak) at 2,000 goa | The capability is genuinely real and working, not hollow. The claim() guard is the correct SELECT-then-guarded-UPDATE optimistic concurrency pattern that SQLite's per-statement atomicity under WAL makes race-safe, and I empirically reproduced 0 duplicates / 0 lost at the exact headline numbers (5,000 jobs x 48 processes) plus the soak gate at 2,000/24. I am  |
| ✅ Substantiated | Encryption at rest on by default (AES-256-GCM, auto-key) plus audit-log signing on by default under "secure defaults." | This is a real, working implementation that genuinely delivers the headline claim — not theater. AES-256-GCM authenticated encryption (verified producing real ciphertext + GCM tag, detecting tampering), auto-generated 32-byte key, and Ed25519/SHA-256 hash-chained audit signing with a verifier that actually checks signatures, all defaulting ON under secure_by |
| ✅ Substantiated | Multi-tenant per-tenant envelope encryption (DEK wrapped by KEK), pluggable KMS with BYOK (AWS/GCP/Vault), operable+resumable fleet KEK rotation, and database-native Postgres Row-Level Security that f | Every component of the claim is backed by real, working code, not stubs. The encryption is genuine AES-256-GCM envelope (DEK wrapped by KEK) with AEAD context binding that demonstrably prevents cross-tenant DEK transplantation — the load-bearing isolation guarantee. BYOK backends genuinely delegate to AWS/GCP/Vault KMS APIs and bind tenant context as the clo |
| ✅ Substantiated | Capability tokens are attenuate-only: a spawned child can never exceed its parent's grant (capability monotonicity), proven by fuzzing — "0 leaks in ~2000 probes" / "399,131 probes, 0 leaks." | This is a genuine, working, well-engineered implementation — not theater. The attenuation algebra is correct (intersection of allow-lists, union of deny-lists, min of risk ceilings, inherited expiry) with the dangerous "empty set means all" convention handled correctly via a NUL sentinel so disjoint whitelists collapse to deny-all rather than failing open. T |
| ✅ Substantiated | Out-of-process model proxy so the agent process never holds the provider API key — "a prompt-injected agent can't exfiltrate a key it doesn't have." (docs/FEATURES.md 1214-1225) | This is a genuine, working credential-isolation boundary, not theater. The key never enters the agent's address space: it lives only in the separate proxy process's MAVERICK_PROXY_KEY env, and the agent authenticates to the proxy with a DISTINCT client token that grants no upstream access (the proxy strips it and substitutes the real key only on the outbound |
| ✅ Substantiated | GitHub Releases binaries are "Sigstore-signed keyless (cosign via GitHub OIDC), logged to Rekor, with a per-release CycloneDX SBOM," verifiable via deploy/verify-release.sh (ARCHITECTURE.md L162-163). | The flow is technically correct and real, not theater. Keyless Sigstore signing is properly wired: `id-token: write` is on the release job (required for OIDC), cosign is invoked with `sign-blob` producing detached `.sig` + `.pem` per artifact, and `cosign verify-blob` inherently consults/records to Rekor in keyless mode — so "logged to Rekor" follows from th |
| ✅ Substantiated | ~310K lines of code ("it's ~310,000 lines of infrastructure … not a prompt over an API") across 8 packages, used as the core defensibility / anti-wrapper proof. | The "~310K LOC … not a prompt over an API" claim is genuinely backed. A real count yields ~214K LOC of hand-written, non-test source Python plus ~84K LOC of substantive declarative pack config (~298K combined, ≈ the rounded "~310K"). This is NOT a thin wrapper: the largest files are core engine code (agent loop, orchestrator, world model, two persistence bac |
| ✅ Substantiated | Library of 514 reusable, validator-compliant skills (SKILL.md) any pack can activate by trigger, plus an 'agent factory' (learn-demo / factory-learn) that builds agents from demonstrations and improve | Every component of the claim checks out as real, working code rather than scaffolding. The 514 skills are genuine, unique, substantive documents (no duplicated stubs or empty templates), and the "validator-compliant" assertion is verifiable: a real linter passes all 514 with zero failures. Trigger-based activation is implemented and demonstrably resolves nat |
| ✅ Substantiated | Live governance demo: a finance specialist boots SEALED, a $60k wire is DENIED, a $6k release REQUIRES A HUMAN, a runaway loop is CAPPED, the agent cannot self-approve, and altering one audited row is | Every falsifiable receipt fires for real. I executed the exact demo a partner would run and each verdict is produced by production enforcement code, not a scripted print: the capability ceiling actually narrows the child agent, `governance.evaluate` applies genuine per-action dollar tiers (proven by the $4k ALLOW vs $6k REQUIRE_HUMAN vs $60k DENY differentia |
| ✅ Substantiated | Hard, never-bypassable budget caps (tokens/$/wall-clock/tool-calls) enforced across the entire swarm, proven under concurrency (32 threads, 160,000==160,000 no lost updates; 16 threads racing a 10k ca | This is a genuine, working implementation that delivers the claim — not theater. The lock is real and proven sound; I independently reproduced the exact stress numbers (160,000==160,000 no lost updates; cap fired on all 16 racing threads, 0 escapes). All four cap dimensions (tokens, dollars, wall, tool-calls) are enforced at record time inside a lock, fail-c |
| ✅ Substantiated | Shield screens every input, tool call, and output at 3 chokepoints — but the shield is fail-OPEN and, without the agent-shield SDK installed, falls back to only ~20 built-in rules (full ~115 patterns  | This claim is a disclosure of a limitation, and the code honestly backs that disclosed posture — so it is substantiated. All three chokepoints exist as real, executing code (not stubs): scan_tool_call actually blocks destructive commands at agent.py and writes an audit record; scan_input/scan_output run across the orchestrator and many ingestion sinks. The d |

---

## Subsystem scorecard

Every reviewed code region with its quality rating. Non-`enterprise` regions are listed first.

| Quality | Directory / region | LOC | Findings | Note |
|---|---|---|---|---|
| 🟡 mostly-solid | `apps/desktop/src-tauri/src` | 176 | 3 | A genuinely thin, well-documented Tauri shell (lib.rs + trivial main.rs) with accurate doc comments and no fake features, fake crypto, or simulated behavior; the only rea |
| 🟡 mostly-solid | `apps/installer-cli/maverick_installer` | 4290 | 6 | A genuinely careful, well-commented installer wizard whose config-writing and file-permission handling are enterprise-grade; the real weaknesses are API-key validators th |
| 🟡 mostly-solid | `apps/installer-msi` | 85 | 2 | A single, well-documented static contract test backing real WiX v4 / cmd / PowerShell installer artifacts that all exist and whose invariants the test genuinely validates |
| 🟡 mostly-solid | `benchmarks` | 4494 | 6 | Unusually high-quality, battle-tested benchmark code with honest "producer not grader" framing and real governance wiring; the few issues are hardcoded model IDs in the p |
| 🟡 mostly-solid | `benchmarks` | 1668 | 3 | These benchmark harnesses are genuinely enterprise-grade: real grading logic, real seams into verified production functions (run_goal_sync, _cap_tool_output, Budget, tool |
| 🟡 mostly-solid | `benchmarks/_common` | 495 | 4 | Honest, well-tested benchmark plumbing whose biggest weakness is that the headline "manifest is the contract" registry (budget/threshold fields) is never read by the harn |
| 🟡 mostly-solid | `benchmarks/security` | 791 | 3 | Genuinely honest, well-documented benchmark code that runs the real shield scanners (no fake/random/canned results) and carefully separates train vs held-out signal; the  |
| 🟡 mostly-solid | `go/model-proxy` | 1034 | 3 | A genuinely well-engineered, parity-tested security component (real SSRF guard, constant-time auth, key injection) whose only real defect is that the Go port silently dro |
| 🟡 mostly-solid | `packages/maverick-core/maverick` | 4341 | 2 | This chunk is overwhelmingly genuine, well-tested enterprise code (governance policy engine, eBPF supervisor, capability fuzzer, model-key proxy, job worker, attachment s |
| 🟡 mostly-solid | `packages/maverick-core/maverick` | 1948 | 2 | A genuinely strong chunk — honest scope docstrings, deterministic pure functions, real stdlib HMAC session crypto, compliance floors that are actually enforced at runtime |
| 🟡 mostly-solid | `packages/maverick-core/maverick/compaction` | 2070 | 6 | Genuinely strong, well-documented compaction code with real implementations one level down (real bandit, real fastembed embedder, real heuristic triple extractor, atomic  |
| 🟡 mostly-solid | `packages/maverick-core/maverick/marketplace` | 1139 | 4 | Genuinely strong marketplace code — real Ed25519 pinned-key fail-closed federation, real secret/prohibited-pattern moderation, atomic locked stores — marred mainly by a b |
| 🟡 mostly-solid | `packages/maverick-core/maverick/providers` | 1844 | 4 | Genuinely strong, real provider-translation code (Anthropic prompt-caching, OpenAI format bridging, fail-closed budget accounting) with only a few minor issues: hardcoded |
| 🟡 mostly-solid | `packages/maverick-core/maverick/safety` | 388 | 2 | Genuinely enterprise-grade safety code overall — every module delegates to real implementations (HMAC hash-chained screenshot ledger, substantive regex jailbreak/unicode/ |
| 🟡 mostly-solid | `packages/maverick-core/maverick/sandbox` | 2663 | 6 | The container backends (docker/podman/kubernetes/devcontainer/local/ssh) and the pool/SDK/network-policy modules are genuinely strong, hardened, well-commented production |
| 🟡 mostly-solid | `packages/maverick-core/maverick/tools` | 4321 | 6 | These are genuinely well-engineered third-party tool wrappers with real API integration and unusually thoughtful security hardening (SSRF/redirect protection, path-traver |
| 🟡 mostly-solid | `packages/maverick-core/maverick/tools` | 2705 | 3 | Genuinely solid, security-conscious tool wrappers around real APIs (GitHub/ServiceNow/S3/Dropbox/Plausible/HASS, git apply, SQLite, simctl, Playwright, mesh parsing) with |
| 🟡 mostly-solid | `packages/maverick-core/maverick/tools` | 1885 | 2 | These 14 agent tools are overwhelmingly honest, well-validated, deterministic helpers whose docstrings accurately label their scope ("pure," "deterministic, offline," "no |
| 🟡 mostly-solid | `packages/maverick-core/maverick/tools` | 1454 | 4 | Overwhelmingly honest, well-bounded stdlib tools with accurate docstrings (correct HMAC/constant-time compares, honestly-labeled assumptions, explicit "stateless"/"does n |
| 🟡 mostly-solid | `packages/maverick-core/maverick/training` | 1891 | 4 | Genuinely honest, well-engineered training code: real gradient descent (prm_linear, reward_model), correct DPO math (rlaif), no hardcoded model ids, no fake crypto, and u |
| 🟡 mostly-solid | `packages/maverick-core/maverick/vector_store` | 802 | 6 | Competent, idiomatic adapter code with real backend calls and tenant scoping, but the Weaviate adapter creates a vectorizer-less collection while its docstring promises s |
| 🟡 mostly-solid | `packages/maverick-core/maverick/world_model_backends` | 3309 | 5 | A genuinely substantial, careful Postgres backend (real tenant scoping, advisory-lock migrations, fail-closed RLS, parameterized SQL) marred by one materially-defeated se |
| 🟡 mostly-solid | `packages/maverick-dashboard/maverick_dashboard` | 4167 | 5 | Both files are genuinely enterprise-grade — real auth gating, real OIDC verification, real HMAC-signed sessions, PKCE/state/one-time-tx CSRF defenses, owner-scoping and i |
| 🟡 mostly-solid | `packages/maverick-evolve/maverick_evolve` | 1212 | 3 | A genuinely well-engineered, dependency-injected config-evolution package with real wiring (real calibration gate, real atomic/locked writes, real env knobs consumed by t |
| 🟢 enterprise | `apps/desktop/src-tauri` | 3 | 0 | The sole file in this chunk (apps/desktop/src-tauri/build.rs) is the canonical 3-line Tauri v2 build script invoking tauri_build::build(), correctly wired via the tauri-b |
| 🟢 enterprise | `apps/desktop/ui` | 108 | 0 | A single 108-line splash controller (apps/desktop/ui/app.js) that is clean, idiomatic vanilla JS with honest, accurate comments and no fake features, swallowed errors, or |
| 🟢 enterprise | `apps/installer-desktop` | 15 | 0 | The single assigned file is a 16-line, idiomatic Vite config for the Tauri+Svelte installer that is fully consistent with package.json and standard Tauri conventions; no  |
| 🟢 enterprise | `apps/installer-desktop/src` | 7 | 0 | The single assigned file (apps/installer-desktop/src/main.ts) is the standard 8-line idiomatic Svelte entry-point boilerplate with no fake features, swallowed errors, har |
| 🟢 enterprise | `apps/installer-desktop/src-tauri` | 34 | 0 | A single, idiomatic Tauri build script that derives a build-provenance install ref from env or a real git rev-parse with proper error handling and no fakes, secrets, or s |
| 🟢 enterprise | `apps/installer-desktop/src-tauri/src` | 156 | 2 | A small, well-engineered Tauri shell: it shells out to already-tested bootstrap scripts (single source of truth), pins the install to a build-time-baked commit SHA, valid |
| 🟢 enterprise | `apps/mobile-companion` | 85 | 1 | App.tsx is a clean, honest ~86-line React Native navigation root whose docstring claims (read-only, GET-only, dependency-light) are all verified true against the real src |
| 🟢 enterprise | `apps/mobile-companion/src` | 256 | 2 | A small, genuinely solid read-only React Native client: every API endpoint and security claim in the comments was verified against the real dashboard (api.py) and VS Code |
| 🟢 enterprise | `apps/mobile-companion/src/screens` | 371 | 1 | These four mobile-companion screen files are genuine, honest, idiomatic React Native code: every docstring claim (read-only API, secure-store keychain, real offline cache |
| 🟢 enterprise | `apps/mobile-skills` | 85 | 2 | A genuinely honest, well-constructed contract test for a clearly-labeled mobile feasibility scaffold; it exercises real pure-Python skill code via subprocess isolation an |
| 🟢 enterprise | `apps/mobile-skills/kivy-shell` | 101 | 1 | A single small, unusually honest "feasibility scaffold" file that loads and runs a genuinely-implemented real skill (answer_entropy, correct normalized Shannon entropy);  |
| 🟢 enterprise | `apps/visionos-plan-tree/MaverickPlanTree` | 164 | 1 | Two small, honest, fully-functional Swift files: the model fetches a real, schema-matched endpoint (/api/v1/goal-tree, confirmed in api.py/goal_tree.py) and the view does |
| 🟢 enterprise | `apps/vscode-extension/src` | 371 | 1 | A small, honestly-scoped VS Code extension that safely shells out to the maverick CLI and tails SSE; no fakery, no hardcoded secrets, intact TLS, injection-safe spawn, ca |
| 🟢 enterprise | `apps/watch-glance/MaverickGlance` | 90 | 0 | A small, honest watchOS glance client: real HTTPS-or-localhost enforcement, bearer-token auth, genuine URLSession networking, and user-surfaced error handling backed by a |
| 🟢 enterprise | `apps/zed-extension/src` | 41 | 1 | A 42-line Zed WASM extension that honestly returns a `maverick mcp` Command for Zed to spawn; every claim it makes is verifiable against the real CLI, with candid status  |
| 🟢 enterprise | `benchmarks` | 2314 | 3 | Benchmark code is genuinely high-quality: hermetic deterministic tests over real machinery, honest about limitations (empty leaked-corpus shipped deliberately), real path |
| 🟢 enterprise | `benchmarks` | 659 | 2 | The benchmarks/ chunk is genuinely enterprise-grade: tests drive the real kernel (skills, action_gate, capability, agent_trust, audit/verify_chain, distillation, sandbox) |
| 🟢 enterprise | `deploy/reference-architectures/demo-cluster` | 86 | 0 | A single, honest, well-documented demo-data seeder that calls the real production world-model API correctly and is correctly isolated under deploy/reference-architectures |
| 🟢 enterprise | `deploy/relay` | 136 | 2 | A small, dependency-free, security-conscious HMAC relay whose signing scheme was independently verified to match maverick.webhooks._sign/verify_signature and the real /we |
| 🟢 enterprise | `extensions/browser` | 490 | 1 | This three-file Manifest V3 browser extension is genuinely enterprise-grade: comments accurately match behavior, security is carefully reasoned (loopback-only host permis |
| 🟢 enterprise | `extensions/webgpu-vision` | 234 | 0 | Two small, self-aware JavaScript files (WebGPU grayscale/Sobel compute shaders and an integer-only 8x8 average-hash) that explicitly scope themselves down, contain no fak |
| 🟢 enterprise | `extensions/widget` | 173 | 2 | A single self-contained, XSS-safe embeddable widget grounded in the real /api/v1/goals endpoint (verified GoalOut fields), surfacing errors honestly, with an unusually th |
| 🟢 enterprise | `go/model-proxy/cmd/model-proxy` | 58 | 1 | main.go is an honest, well-documented thin CLI wrapper that delegates all security-critical logic to a genuinely-implemented, parity-tested proxy package (real SSRF host  |
| 🟢 enterprise | `packages/maverick-channels/maverick_channels` | 3506 | 4 | This is genuinely enterprise-grade channel-adapter code: every webhook adapter does constant-time HMAC/token verification, default-deny sender allowlists, atomic message- |
| 🟢 enterprise | `packages/maverick-channels/maverick_channels` | 1237 | 1 | Genuinely enterprise-grade channel adapters: real platform-SDK integrations (discord.py, slack_sdk, matrix-nio, signal-cli, AppleScript, chat.db), default-deny per-sender |
| 🟢 enterprise | `packages/maverick-core/maverick` | 3182 | 2 | agent.py is genuinely enterprise-grade: real implementations verified one level down (model resolution, capability/governance gates, verifier, PRM), dense accurate scar-t |
| 🟢 enterprise | `packages/maverick-core/maverick` | 2677 | 3 | A genuinely enterprise-grade SQLite world store: real AES-256-GCM at-rest encryption with fail-closed sealing, careful WAL/lock/migration concurrency engineering, fully p |
| 🟢 enterprise | `packages/maverick-core/maverick` | 3723 | 3 | Both files (coding_mode.py, orchestrator.py) are genuinely careful, well-reasoned production code with extensive change-rationale comments, real wired-in implementations, |
| 🟢 enterprise | `packages/maverick-core/maverick` | 4005 | 2 | All three modules (dreaming.py, mcp_client.py, federation.py) are genuinely enterprise-grade: real Ed25519 signature verification with replay/freshness protection, real a |
| 🟢 enterprise | `packages/maverick-core/maverick` | 4111 | 3 | These four core modules (config, llm facade, self-learning, tax-prep) are genuinely enterprise-grade: real validation, real cited computation, real failover/budget plumbi |
| 🟢 enterprise | `packages/maverick-core/maverick` | 4073 | 1 | These five files are genuinely enterprise-grade — careful default-deny/fail-closed security posture, real Ed25519 signature verification, SSRF guards, path-traversal defe |
| 🟢 enterprise | `packages/maverick-core/maverick` | 4020 | 1 | Six genuinely enterprise-grade modules: real AES-256-GCM at-rest encryption with a rotation keyring and fail-closed semantics, a fuzzy SEARCH/REPLACE engine with discipli |
| 🟢 enterprise | `packages/maverick-core/maverick` | 4265 | 3 | This chunk is genuinely enterprise-grade: real implementations throughout (atomic budget accounting with TOCTOU/lock handling, fail-closed verifier, validated dashboard o |
| 🟢 enterprise | `packages/maverick-core/maverick` | 4163 | 2 | This chunk is genuinely enterprise-grade: real Ed25519 capability signing, an asymmetric-only alg-confusion-hardened OIDC verifier, a fail-closed self-improvement promoti |
| 🟢 enterprise | `packages/maverick-core/maverick` | 4115 | 2 | All 10 files are genuinely enterprise-grade: real cryptography (Ed25519/HMAC-SHA256/AES-256-GCM), consistently fail-closed security boundaries, atomic/TOCTOU-safe file pu |
| 🟢 enterprise | `packages/maverick-core/maverick` | 4278 | 2 | All 13 modules are genuine, well-engineered enterprise code with real crypto (Ed25519, HMAC-SHA256), atomic ledgers (flock + os.replace), fail-closed signature verificati |
| 🟢 enterprise | `packages/maverick-core/maverick` | 3988 | 2 | An unusually clean, genuinely enterprise-grade chunk: every module is a real implementation (consistent-DB-copy backups with integrity verification, real PKCE/OAuth flows |
| 🟢 enterprise | `packages/maverick-core/maverick` | 3729 | 0 | All 14 modules are genuinely enterprise-grade — real Ed25519/HMAC-SHA256 signing and verification, real causal-inference and fairness math, atomic/locked writes, SSRF and |
| 🟢 enterprise | `packages/maverick-core/maverick` | 3523 | 3 | Genuinely enterprise-grade chunk: real Ed25519 crypto with fail-closed verification (plugin_ca, handoff, federation_envelope, tool_token), honest scope disclaimers (specu |
| 🟢 enterprise | `packages/maverick-core/maverick` | 3253 | 2 | This chunk is genuinely enterprise-grade: real Ed25519 handoff signing/verification, real least-squares calibration math, atomic 0600 persistence, fail-closed client bind |
| 🟢 enterprise | `packages/maverick-core/maverick` | 3051 | 1 | Genuinely enterprise-grade kernel code across all 14 files: real sigstore fail-closed verification, salted-HMAC anonymization, subprocess plugin isolation with scrubbed e |
| 🟢 enterprise | `packages/maverick-core/maverick` | 2868 | 1 | This chunk is genuinely enterprise-grade: real AES-256-GCM envelope encryption (KMS/DEK), real HMAC-signed expiring/one-time tokens with constant-time compare and nonce c |
| 🟢 enterprise | `packages/maverick-core/maverick` | 2737 | 2 | This chunk is genuinely enterprise-grade: real cloud-KMS delegation, fail-closed gRPC TLS/mTLS, real Ed25519 signature verification on federated insights, careful path-tr |
| 🟢 enterprise | `packages/maverick-core/maverick` | 2549 | 2 | This chunk is genuinely strong, defensively-written enterprise code (real crypto, real SGD verifier head, real governed gates, atomic writes, cross-process locks, redacti |
| 🟢 enterprise | `packages/maverick-core/maverick` | 2406 | 2 | This chunk is overwhelmingly genuine enterprise-grade code (real deterministic stats, geometry, monotonic-deadline message bus, difflib DOM diff, honest cost/migration ca |
| 🟢 enterprise | `packages/maverick-core/maverick` | 2184 | 1 | Across all 14 files this chunk is genuinely enterprise-grade: real implementations (hash-chained governance, bootstrap-CI statistics, hostile-MCP schema scanning, honestl |
| 🟢 enterprise | `packages/maverick-core/maverick` | 2032 | 1 | Across all 14 modules this is genuinely enterprise-grade, honestly-scoped code: real Ed25519 verification, real fixpoint redaction, real statistics, deterministic injecte |
| 🟢 enterprise | `packages/maverick-core/maverick` | 1821 | 2 | Genuinely enterprise-grade: pure dependency-injected modules, ReDoS-hardened secret scrubbing with documented rationale, real failover wiring into llm.py, and honest upfr |
| 🟢 enterprise | `packages/maverick-core/maverick` | 1629 | 0 | All 14 modules are dependency-free, well-documented primitives with honest design notes, fail-soft posture, input bounds, and matching tests; I found no fake features, sw |
| 🟢 enterprise | `packages/maverick-core/maverick` | 1469 | 3 | Across all 14 files this chunk is genuinely enterprise-grade: dependency-light, thread-safe, deterministic, with fail-soft paths that are deliberately commented and real  |
| 🟢 enterprise | `packages/maverick-core/maverick` | 1229 | 2 | This chunk is genuinely enterprise-grade: every module has a real, correct implementation (atomic writes with flock, online z-score anomaly detection, locale-aware money  |
| 🟢 enterprise | `packages/maverick-core/maverick` | 1038 | 3 | Honest, well-scoped utility code: docstrings disclose limits ("ships the FRAMEWORK + a reference connector", "detection slice, not full attestation", "roadmap"), real imp |
| 🟢 enterprise | `packages/maverick-core/maverick` | 684 | 0 | All 13 modules are small, single-purpose utilities with real, correct implementations and honest docstrings; nothing here would fail technical due-diligence. |
| 🟢 enterprise | `packages/maverick-core/maverick (chunk 43)` | 4161 | 3 | These 11 modules are genuine enterprise code: config-driven model resolution, real signed/measured proof-pack collectors, honest compliance status logic, SSRF-guarded web |
| 🟢 enterprise | `packages/maverick-core/maverick/audit` | 3646 | 2 | This is genuinely enterprise-grade, security-conscious code: real Ed25519 hash-chained signing with off-host/KMS key custody, real AES-256-GCM at-rest sealing, atomic+fsy |
| 🟢 enterprise | `packages/maverick-core/maverick/automation_import` | 1508 | 3 | A genuinely well-engineered automation-import subsystem with real per-platform translators (graph BFS, topological sort, blueprint flattening), real credentialed HTTP cli |
| 🟢 enterprise | `packages/maverick-core/maverick/benchmarks` | 479 | 1 | A genuinely solid, deterministic offline reproducibility harness with real HMAC-SHA256 signing (constant-time compare), a real content-diffing verifier, and honest docstr |
| 🟢 enterprise | `packages/maverick-core/maverick/cache` | 1322 | 4 | Genuinely high-quality, defensively-written cache modules (atomic writes, 0600 perms, LRU+TTL, secret-scanning on store, fail-open) with honest roadmap labeling; the only |
| 🟢 enterprise | `packages/maverick-core/maverick/cli` | 6039 | 3 | A 6,040-line CLI dispatcher that is overwhelmingly thin, well-documented click wrappers delegating to real implementations, with security-conscious file permissions, fail |
| 🟢 enterprise | `packages/maverick-core/maverick/cli` | 1584 | 0 | These seven CLI files are thin, honest click command-dispatch wrappers that delegate to real implementation modules; docstrings accurately describe behavior (including ho |
| 🟢 enterprise | `packages/maverick-core/maverick/cost` | 1387 | 3 | This is genuinely enterprise-grade code: every "feature" (cost-aware routing, contextual-bandit v3, OLS cost-curve fitting, cost forecasting, tag chargeback, retrospectiv |
| 🟢 enterprise | `packages/maverick-core/maverick/finance` | 509 | 2 | Genuinely enterprise-grade compliance code backed by real crypto/signing/screening implementations one level down, with honest disclaimers; the only real defect is three  |
| 🟢 enterprise | `packages/maverick-core/maverick/grpc_api` | 880 | 2 | Genuinely enterprise-grade gRPC surface: fail-closed bearer auth with constant-time HMAC, a real agent-trust plane, capability intersection (callers can only narrow), per |
| 🟢 enterprise | `packages/maverick-core/maverick/providers` | 24 | 0 | The sole file is a clean, honest 25-line thin subclass of a carefully-written OpenAIClient; every class attribute and constructor argument maps to real, verified parent b |
| 🟢 enterprise | `packages/maverick-core/maverick/replay` | 502 | 3 | Genuinely solid, defensively-written replay/export module — real PII+secret redaction, 0o600 permission hardening, corruption-tolerant trace reader, and a real ffmpeg pip |
| 🟢 enterprise | `packages/maverick-core/maverick/retry` | 333 | 3 | Genuinely solid, defensively-written retry/backoff code with real edge-case handling (negative Retry-After clamping, equal-jitter to avoid retry storms, overflow guards,  |
| 🟢 enterprise | `packages/maverick-core/maverick/safety` | 3265 | 2 | A genuinely enterprise-grade safety package: real regex/Luhn/entropy-aware detectors, documented adversarial-hardening history, correct fail-closed ACLs and fail-open shi |
| 🟢 enterprise | `packages/maverick-core/maverick/skill` | 1497 | 2 | This skill module family is genuinely enterprise-grade: real BM25 search, an injected (testable) HF fetcher, a hardened untrusted-dataset import path with path-traversal/ |
| 🟢 enterprise | `packages/maverick-core/maverick/tenant` | 1075 | 3 | Genuinely enterprise-grade tenant control-plane: real AES-256-GCM envelope encryption with AEAD context binding, fail-closed cloud-KMS resolution, O_EXCL/atomic-write rac |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 4350 | 0 | Genuinely enterprise-grade tooling; only minor nits found. |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 4247 | 3 | This chunk (packages/maverick-core/maverick/tools) is genuinely enterprise-grade: real SSRF/DNS-rebinding pinning, symlink-TOCTOU-safe file I/O, careful path confinement, |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 3569 | 2 | This tools chunk is overwhelmingly genuine, working enterprise code: real REST/GraphQL integrations (Linear, GitHub, PagerDuty, GDrive, Elasticsearch, Discord), real CLAP |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 3277 | 4 | This chunk is genuinely enterprise-grade integration-tool code — real SSRF connection-pinning, SMTP header-injection blocking, confirm-gated mutations, connection-pool cl |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 3110 | 0 | All 14 tool modules are genuine, well-engineered integrations (real HTTP/boto3/ffmpeg/sysfs calls, honest docstrings, path-traversal and option-injection guards, redirect |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 2927 | 2 | A uniformly high-quality set of integration tools (Datadog, Zoom, MS Graph, Twilio, Calendly, GitLab, HuggingFace, OCR, ImageMagick, spreadsheet, clipboard, spend report, |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 2506 | 2 | This is a genuinely strong, enterprise-grade chunk: real offline algorithms (Hamilton apportionment, Kahn topo-sort, k-anonymity/l-diversity grouping, semver comparison w |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 2329 | 2 | This chunk (tools/) is genuinely enterprise-grade: real SSRF/DNS-rebinding protection and streaming size caps in view_image, path-traversal guards via _safe_resolve, a ca |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 2187 | 4 | Genuinely strong chunk: real integrations (boto3, httpx-backed DeepL/Libre/NewsAPI/ERP, pyserial, dnspython, youtube-transcript-api), real math (hand-rolled least-squares |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 2074 | 1 | A set of small, single-purpose, deterministic/offline (or properly SSRF-guarded) tools that are honestly documented and free of fake features, swallowed errors, hardcoded |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 1984 | 3 | This chunk of tools is genuinely enterprise-grade: every tool is honest about its scope (pure/offline/no-model stated plainly in docstrings, not disguised as ML/semantic) |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 1833 | 2 | This chunk of 14 tools is overwhelmingly genuine, honest enterprise code: the "deterministic/offline" calculators correctly implement their stated math and transparently  |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 1772 | 2 | All 14 tools are genuinely implemented, deterministic, offline (or real authenticated HTTP clients), with docstrings that accurately match behavior and consistent explici |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 1704 | 2 | This chunk of 14 tool modules is genuinely enterprise-grade: every docstring honestly discloses scope ("deterministic, offline, no LLM", "schema only, no SDK/network", "d |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 1624 | 1 | A uniformly strong set of small, deterministic, well-validated tool wrappers (real SSRF/DNS-rebinding defense, a real SQL tokenizer, real AST-based mutation planning, car |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 1536 | 2 | A uniformly strong batch of deterministic, honestly-documented tool helpers (clean set/regex/stats logic; real authenticated HTTP for oracle/bigquery; path-traversal-guar |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 1276 | 1 | All 14 tools in packages/maverick-core/maverick/tools are honest, deterministic-where-claimed, input-validated, sandbox-routed, and SSRF-protected enterprise-grade helper |
| 🟢 enterprise | `packages/maverick-core/maverick/tools` | 436 | 2 | Nine thin, honest tool-wrappers that delegate to genuinely-implemented backing modules; every strong claim (provable redaction, live compliance posture, threat hunt, mone |
| 🟢 enterprise | `packages/maverick-dashboard/maverick_dashboard` | 4980 | 0 | test |
| 🟢 enterprise | `packages/maverick-dashboard/maverick_dashboard` | 3985 | 3 | This chunk is genuinely enterprise-grade: SCIM 2.0, SAML, OIDC, RBAC, multi-tenant scoping, atomic 0600 writes, constant-time token compares, owner-scoping, and pure unit |
| 🟢 enterprise | `packages/maverick-dashboard/maverick_dashboard` | 283 | 0 | All four files (session revocation, i18n chrome, pluggable themes, package __init__) are genuinely enterprise-grade: the revocation store fails CLOSED on corruption/unrea |
| 🟢 enterprise | `packages/maverick-dashboard/maverick_dashboard/static` | 129 | 1 | A small, self-contained, honest web component that talks to real, verified backend endpoints with matching response shapes, escapes all user-influenced strings, surfaces  |
| 🟢 enterprise | `packages/maverick-knowledge/maverick_knowledge` | 1051 | 0 | The maverick_knowledge package (vector store, embedders, parsing, OCR, chunking) is genuinely enterprise-grade: parameterized SQL with a charset-validated identifier on t |
| 🟢 enterprise | `packages/maverick-mcp/maverick_mcp` | 2850 | 1 | This MCP server chunk (server.py, http_transport.py, tasks.py, publish.py) is genuinely enterprise-grade: real MCP 2025-11-25 protocol handling, constant-time bearer auth |
| 🟢 enterprise | `packages/maverick-shield/maverick_shield` | 2727 | 3 | This is genuinely strong, audit-defensible defensive-security code — real regex detectors with adversarial reasoning (phase-aligned base64 decode, order-independent budge |
| 🟢 enterprise | `rust/maverick-verify-audit/src` | 658 | 1 | Genuinely enterprise-grade crypto-verification code with accurate docs, real tests, and no fake/hollow logic; the one substantive issue is a security-relevant trust-model |
| 🟢 enterprise | `rust/mvk-scan-py/src` | 77 | 0 | A clean, idiomatic PyO3 binding (rust/mvk-scan-py/src/lib.rs) that thinly and faithfully delegates to the genuinely-implemented mvk-scan crate (real Unicode/Trojan-Source |
| 🟢 enterprise | `rust/mvk-scan-wasm/src` | 149 | 1 | A clean, correct, well-documented thin wasm-bindgen FFI layer that faithfully delegates to a real, test-covered core crate (mvk-scan); the only original logic (codepoint→ |
| 🟢 enterprise | `rust/mvk-scan/src` | 741 | 2 | A genuinely enterprise-grade, well-documented native Rust port of real Python safety scanners (PII/secret/perceptual-hash/unicode-filter) with real algorithms (Luhn, aver |
| 🟢 enterprise | `scripts/stress` | 775 | 2 | These are genuine, high-quality CI stress harnesses that import and exercise the real safety-critical subsystems (crypto-at-rest, Budget, Capability attenuation, the real |
| 🟢 enterprise | `sdks/plugin-ts/src` | 263 | 1 | A single, self-contained, idiomatic TypeScript SDK file with real protocol handling, real input validation, and bounds that verifiably mirror the browser extension's cont |
| 🟢 enterprise | `web/widget` | 105 | 2 | A single 105-line, dependency-free, XSS-safe embeddable chat widget that is honest about what it does, has no hardcoded secrets/eval/swallowed errors, and targets a real, |

---

## Appendix A — Medium-severity findings

*74 findings.*

### Misleading name / docstring / comment (30)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `apps/installer-cli/maverick_installer/bridge.py`:1-117 | Tauri sidecar claims to mirror CLI consumer mode 'exactly' but silently drops API-key validation | Have the sidecar call the same _consumer_api_key validation/caching logic (or factor key-validation into write_consumer_config) and emit the bad-key s | 0.7 |
| `apps/installer-cli/maverick_installer/wizard.py`:290-311 | Anthropic key 'validation' returns ok=True on nearly every failure, including import failure and any non-auth exception | Distinguish auth/permission/bad-request errors (return False) from genuine connectivity errors (return a third 'unknown/skipped' state shown distinctl | 0.78 |
| `apps/installer-msi/test_wxs.py`:72-80 | Launcher regression guard regex is malformed and never matches the form it forbids | Match the family of forbidden module invocations explicitly, e.g. assert re.search(r"\bpy(\s+-3[.\d]*)?\s+-m\s+maverick\b", cmd) is None and likewise  | 0.9 |
| `apps/mobile-skills/test_mobile_skills.py`:65-68 | Checksum test asserts the TODO placeholder exists, so it breaks when the real checksum is filled in | Make the test conditional: if a 'sha256 = <hex>' pin is present, assert it matches the known-good Pyodide 0.26.4 digest; only if absent, tolerate the  | 0.82 |
| `benchmarks/_common/cost_tracker.py`:104-122 | pareto_frontier() does no Pareto filtering — returns every pipeline including dominated ones | Either rename to pipeline_summary()/per_pipeline_cost_accuracy(), or add the actual dominance filter: after computing (pipeline, cost, rate), drop any | 0.7 |
| `packages/maverick-core/maverick/cache/llm.py`:13-15 | Module docstring documents a cached_complete() integration API that does not exist | Either implement `cached_complete()` (wrap the provider call with cache_key/lookup/store) and export it, or change the docstring to state plainly that | 0.9 |
| `packages/maverick-core/maverick/cli/__init__.py`:5904-5906 | `cost --model` filter is non-functional; matches a `model=X` outcome format the system never writes | Persist the model id in a dedicated, queryable column on the episode row (the spend ledger already records cost/tokens) and filter on exact equality ( | 0.85 |
| `packages/maverick-core/maverick/compaction/hybrid.py`:194-211, 356-381 | Hybrid picker emits strategy names (truncate/structural/retrieval/summarize) that the real dispatcher cannot execute | Pick one strategy vocabulary. If the hybrid picker is meant to choose among executable strategies, make STRATEGIES match strategies.STRATEGIES (or add | 0.8 |
| `packages/maverick-core/maverick/marketplace/moderation.py`:29-31,407-409 | Documented CLI entry point points at a module that does not exist | Either add a thin maverick/marketplace_moderation.py shim (or a [project.scripts] entry) so the flat name resolves, or correct both the docstring and  | 0.95 |
| `packages/maverick-core/maverick/proof_guarantees.py`:184-204 | Crypto-gated diligence guarantees are recorded passed=True when cryptography is absent ("verified in CI") | Keep skipped guarantees out of the proven set by introducing a tri-state or by setting passed=False (or a distinct 'skipped' status) for crypto-absent | 0.66 |
| `packages/maverick-core/maverick/providers/azure_openai_provider.py`:70 | Azure OpenAI substitutes a fake key 'azure-no-auth' when AZURE_OPENAI_API_KEY is missing | Require AZURE_OPENAI_API_KEY explicitly (add it to the existing 'requires AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_DEPLOYMENT' guard), or support AzureAD  | 0.72 |
| `packages/maverick-core/maverick/providers/bedrock_provider.py`:31 | Bedrock substitutes a fake bearer 'bedrock-no-auth' when the API key is missing | Raise RuntimeError('Bedrock requires BEDROCK_API_KEY') when no key is provided (mirroring the existing AWS_REGION check two lines above), instead of s | 0.78 |
| `packages/maverick-core/maverick/providers/openai_provider.py`:10-16, 298-308 | Module docstring claims tool_call_id stubbing fix that the code explicitly does NOT implement | Either implement the stubbing the docstring promises (synthesize empty `tool` responses for any tool_call lacking a matching tool_result, and reject/l | 0.7 |
| `packages/maverick-core/maverick/reliability_cert.py`:12-22, 86-90 | Reliability-cert docstring claims a 'query plans / EXPLAIN index' check that is not implemented or registered | Either implement a `_check_query_plans` that runs EXPLAIN QUERY PLAN over the hot world-model queries and asserts index usage (then add it to DEFAULT_ | 0.88 |
| `packages/maverick-core/maverick/sandbox/network_policy.py`:11-15 | Docstring claims packet-level egress enforcement that does not exist anywhere in the codebase | Reword the docstring to state plainly that this is an advisory in-process policy decision with no packet-level enforcement, and that container backend | 0.8 |
| `packages/maverick-core/maverick/self_learning.py`:740-754 | Approved generated tool's fn runs in-process at runtime despite 'sandbox'/out-of-host framing | Either land the documented out-of-process tool RUNTIME so approved fns execute in the sandbox backend on every call, or make the in-process-execution  | 0.55 |
| `packages/maverick-core/maverick/tools/ast_edit.py`:1-16, 120-127 | "AST-aware editor" rename_symbol is a raw regex text substitution, not AST-aware | Either rename the op to make the limitation explicit (e.g. textual_rename) or implement a true AST-scoped rename: parse, resolve binding scopes, rewri | 0.78 |
| `packages/maverick-core/maverick/tools/capability_revocation.py`:1-8, 37-56 | Revocation BFS revokes principals who still hold the capability via an independent un-revoked path | Compute the set of principals still reachable from any non-revoked root that grants the capability, and subtract it from the transitively-lost set; on | 0.7 |
| `packages/maverick-core/maverick/tools/consent_ergonomics.py`:19-32 | Consent risk badge uses naive substring matching and mislabels benign scopes as HIGH | Match on tokenized scope segments (split on '.', '_', '-', ':' and compare whole segments) or anchored patterns, and special-case the wildcard ('*') a | 0.88 |
| `packages/maverick-core/maverick/tools/decision_explainer.py`:7-14 | Docstring claims a 'smallest change that would flip it' recourse computation that is never implemented | Either implement the recourse computation (for the additive model, the minimal single-factor delta is margin/weight per factor; report the smallest su | 0.85 |
| `packages/maverick-core/maverick/tools/geofence.py`:8, 47-64 | Geofence docstring says empty allow-list means 'any region not denied' but the code defaults to DENY | Make the docstring match the code: state that an empty allow-list with no explicit 'default' is DENY (fail-closed), and that allow-by-default requires | 0.7 |
| `packages/maverick-core/maverick/tools/home_assistant_tool.py`:137-145 | history op advertises an `hours` time-window parameter that is silently ignored | Either honor the parameter by building the start_time path segment (`/api/history/period/{iso8601_start}?filter_entity_id=...&end_time=...` computed f | 0.85 |
| `packages/maverick-core/maverick/tools/marketplace_ratings.py`:1-14, 75-86 | "verify_install" claims to verify a downloaded artifact but only compares two caller-supplied hashes | Have the tool accept an artifact path (workspace-confined like container_build), compute the digest itself with hashlib.sha256 over the file bytes, an | 0.82 |
| `packages/maverick-core/maverick/tools/snowflake_tool.py`:70-77 | Snowflake client always sends KEYPAIR_JWT token-type header, breaking the OAuth path its docstring promises | Derive the token-type header from config (e.g. a SNOWFLAKE_TOKEN_TYPE env var defaulting to KEYPAIR_JWT, allowing OAUTH), or detect/omit it for OAuth  | 0.82 |
| `packages/maverick-core/maverick/tools/supply_chain_pin.py`:26-38 | Pin auditor flags the standard pip exact-pin '==1.0.0' as a version range | Treat a leading '==' / '=' as an exact pin: strip a leading exact-equality operator before range detection, or detect ranges via packaging.specifiers. | 0.78 |
| `packages/maverick-core/maverick/training/__init__.py`:21-24 | Stale status docstring calls RLAIF a "placeholder" when it is a full 822-line implementation | Update the __init__ status block to reflect that RLAIF is implemented (pure pair-construction unit-tested; heavy GPU train loop operator-side), or dro | 0.93 |
| `packages/maverick-core/maverick/vector_store/qdrant_store.py`:40-45,134-165 | Qdrant _stored_id docstring claims read isolation but query() applies no tenant filter | Either filter query results by the tenant-namespaced id (qdrant payload/id filter; weaviate where-clause on a tenant property) or correct the docstrin | 0.7 |
| `packages/maverick-core/maverick/verifier.py`:293-296, 438-450 | Ensemble verifier docstring claims 'minimum confidence' but code computes the mean | Make the code match the documented contract: `confidence = min(v.confidence for v in side)` for accepting panels, or correct the docstring to say 'mea | 0.9 |
| `packages/maverick-core/maverick/world_model_backends/postgres.py`:289-294, 314-318, 335-340 | Migration comments claim columns are stored plaintext, but the code seals them at rest | Update the v15/v16/v17 migration docstrings to state these columns are sealed at rest via the shared field codec (matching the actual _seal/_unseal ca | 0.92 |
| `packages/maverick-evolve/maverick_evolve/agent_adapter.py`:98-126 | subprocess_run_one docstring claims a 'DONE.\n\n<summary>' answer but returns raw stdout | Either parse the documented `DONE.`/summary delimiter out of stdout (and fail the run if absent) or fix the docstring to state it returns raw stdout;  | 0.78 |

### Swallowed error / silent failure (15)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `apps/installer-cli/maverick_installer/wizard.py`:314-373 | All five OpenAI-compatible key validators swallow every non-auth error and report success | Return a tri-state (ok / rejected / unverifiable) and only cache definitively-ok results; render unverifiable distinctly so operators know the key was | 0.74 |
| `benchmarks/agent_solver.py`:82-87 | Benchmark answer-extraction fallback swallows all exceptions and silently scores 0 | Narrow the except to the specific lookup error, log/re-raise unexpected exceptions, and distinguish 'no answer found' (empty) from 'error reading goal | 0.6 |
| `benchmarks/container_terminal_solver.py`:169-176 | LLM call exception is silently swallowed with a bare return, abandoning the task with no diagnostic | Catch the specific recoverable exceptions, log type+message to stderr, and surface the abort as a distinct result detail (e.g. record an 'ERROR: <type | 0.8 |
| `benchmarks/security/detector_score.py`:39-49 | Heuristics import failure silently degrades the headline `defense_in_depth` backend to never-fire, reported as a measured result | Narrow the except to ImportError, print a WARNING when _HEUR is False, and either list the heuristics backend under UNAVAILABLE (consistent with the f | 0.7 |
| `benchmarks/security/end_to_end_asr.py`:72-84 | Bare `except Exception: return False` silently swallows every scanner crash in a benchmark that feeds the shipping proof_pack | Catch narrowly, count and surface errored cases separately from genuine misses (e.g. return a tri-state or accumulate an `errors` counter), and emit a | 0.78 |
| `benchmarks/tau2_solver.py`:87-124 | LLM/network errors are swallowed and surface as the agent "producing nothing", conflating infra failures with task failures | Catch only the provider/budget exception types, and distinguish error termination from empty-reply termination (e.g. record an explicit error/aborted  | 0.6 |
| `packages/maverick-core/maverick/finance/status.py`:61-68 | Audit-signing probe swallows all exceptions and reports control as merely "off" | Catch only the specific expected exceptions (e.g. ImportError for the optional crypto extra), log unexpected ones at WARNING with the exception, and s | 0.7 |
| `packages/maverick-core/maverick/finance/status.py`:80-97 | Encryption-at-rest and egress-lock probes also swallow all exceptions silently | Narrow the except to ImportError (optional dependency) and log/re-surface any other exception as an explicit error state in the ControlCheck detail ra | 0.7 |
| `packages/maverick-core/maverick/glance.py`:52-63 | Silent broad except in spend path reports $0.00 on any ledger error | Catch the specific expected exceptions (ImportError / KeyError / OSError), log at warning, and signal unavailability distinctly from zero (e.g. spend_ | 0.74 |
| `packages/maverick-core/maverick/grpc_api/server.py`:199-211 | Trust-plane gate fails OPEN on any exception from load_trust_state() | Narrow the except to the specific config/IO errors that are truly best-effort, and on any other exception either re-raise to fail the RPC closed or lo | 0.55 |
| `packages/maverick-core/maverick/routing.py`:57-64 | Broad except: pass silently discards a user's explicitly-configured per-role model, contradicting the 'users own model choice' rule | Narrow the except to the expected import/parse errors and log at warning level (e.g. log.warning('role-model resolution failed for %s; using cascade d | 0.6 |
| `packages/maverick-core/maverick/tools/calendar_tool.py`:205-223 | find_slot silently drops any event it can't parse, so a busy block becomes free time | Catch only the specific normalization errors (AttributeError/TypeError/ValueError) you expect, log.warning the dropped event, and either fail the find | 0.7 |
| `packages/maverick-core/maverick/training/ingest.py`:46-58 | Broad except Exception silently returns [] for world-model lookups, masking real DB failures | Catch only the expected absence (e.g. a specific WorldModel lookup error or check goal existence first), let unexpected exceptions propagate or at min | 0.8 |
| `packages/maverick-core/maverick/vector_store/qdrant_store.py`:178-183 | count() returns 0 on any backend error, masking outages as an empty store | Let transient/backend errors propagate (or log at warning and re-raise a typed StoreUnavailable), and only treat a definitively-absent collection as 0 | 0.66 |
| `packages/maverick-dashboard/maverick_dashboard/api.py`:2443-2457 | oversight 'Active now' activity silently blanks under Postgres (SQLite-only raw query swallowed by broad except) | Use a public WorldModel method (e.g. `recent_goal_events(goal_id, limit=1)`, already used elsewhere in this file) instead of `w.conn.execute` with a ` | 0.85 |

### Reliability gap (14)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `benchmarks/fetch_swe_bench_verified.py`:128-150 | Failed-checkout leaves a half-staged repo that later falsely reports "already staged" | On checkout failure and in the except handler, shutil.rmtree(target, ignore_errors=True) before returning False (mirror the clone-failure path), and/o | 0.83 |
| `go/model-proxy/handle.go`:37-43 | Upstream forward failures are never logged, unlike the Python original | Add structured logging on the error paths (a Go logger or slog) mirroring the Python warning, logging the scrubbed error, and ideally counters/metrics | 0.7 |
| `packages/maverick-core/maverick/automation_import/make.py`:152-171 | Make fetch silently imports only the first 100 scenarios (no pagination) | Add the same continuation loop the other importers use: follow Make's pagination (pg[offset] / pg[limit]) until a short page is returned, with the sam | 0.85 |
| `packages/maverick-core/maverick/compaction/streaming.py`:249-273 | folder() coroutine stores a fingerprint of only locally-folded turns, breaking the cursor/prefix invariant on resume | Seed folded_turns from the persisted prefix (or persist a rolling prefix hash), so the stored fingerprint always covers turns[:cursor]. Add a test tha | 0.72 |
| `packages/maverick-core/maverick/mcp_oauth.py`:122-138, 253-272 | OAuth token fetch/refresh runs the blocking HTTP call while holding the provider lock | Compute whether a fetch is needed under the lock, release it, perform the network call outside the lock, then re-acquire to store the result with a do | 0.6 |
| `packages/maverick-core/maverick/plugin_isolation.py`:135-187 | Advertised timeout_s is silently ignored in the subinterpreter isolation backend | Either run the subinterpreter call in a watchdog thread with a join(timeout_s) and surface an ERROR/abort on expiry (or si.destroy() the interpreter f | 0.82 |
| `packages/maverick-core/maverick/retry/classifier.py`:61-110 | Error classification relies on substring/regex matching against English exception text | Drive classification primarily off concrete exception types (isinstance against the resolved anthropic/openai/httpx classes already enumerated in __in | 0.6 |
| `packages/maverick-core/maverick/skill/embeddings.py`:122-129 | Embedding cache save is non-atomic and unlocked, the exact race the sibling stats module documents and fixes | Use the same maverick.file_lock.atomic_write_text for the write and wrap the load-modify-save in cross_process_lock(path) (and the module _lock), mirr | 0.82 |
| `packages/maverick-core/maverick/tools/containment_mode.py`:18-19, 83 | "Containment" policy tool fails open: unknown (possibly dangerous) actions default to ALLOW | At level=full (and arguably network) deny unknown actions by default (DENY with 'unknown action, denied under containment'); derive the action->catego | 0.6 |
| `packages/maverick-core/maverick/tools/database_tool.py`:123-136 | SQLAlchemy Engine created per call and never disposed — connection/pool leak | Cache/reuse a single Engine per (sanitized) URL with a bounded pool (e.g. an lru-keyed module-level dict or pool_pre_ping/pool_recycle config), or wra | 0.82 |
| `packages/maverick-core/maverick/tools/gdrive_tool.py`:166-185 | Google Drive multipart upload uses a hardcoded boundary with unescaped user content | Generate a random boundary (e.g. 'maverick_' + secrets.token_hex(16)) and assert it does not occur in metadata or content before building the body (re | 0.8 |
| `packages/maverick-core/maverick/tools/office_convert.py`:96-106 | office_convert reports 'wrote {dst}' on a predicted path it never verifies exists | After the sandbox_run, confirm the artifact: stat the derived dst (or glob the outdir for the stem) and return ERROR if no output file is present; pre | 0.78 |
| `packages/maverick-core/maverick/training/ingest.py`:231-236 | Trajectory ingest silently truncates to first 200 events via goal_events() default limit | Pass an explicit, large/unbounded limit or paginate with since_id until exhausted in fetch_steps_for_goal, and assert/log when an event count hits the | 0.78 |
| `packages/maverick-core/maverick/vector_store/weaviate_store.py`:69-80 | Remote non-cloud path passes a full URL as the `host` argument to connect_to_local | Parse MAVERICK_WEAVIATE_URL into scheme/host/port (or use connect_to_custom with explicit http_host/http_port), and add a test asserting the parsed ho | 0.55 |

### Security (5)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `packages/maverick-core/maverick/a2a_tasks.py`:653-658 | A2A streaming path leaks raw exception text (no scrub) into caller artifact and push webhook, unlike send() | Apply the same secrets.scrub() wrapper used in _run() (lines 598-603) to the streaming except clause: detail = scrub(f"{type(e).__name__}: {e}") with  | 0.85 |
| `packages/maverick-core/maverick/audit/forwarder.py`:32,100-111,114-129 | SIEM forwarder ships audit data and a bearer token over plaintext http:// / tcp:// | Default to TLS: warn (or refuse, behind a config knob) when scheme is http/tcp while a bearer token is configured; offer a tls:// (TCP+TLS) syslog tra | 0.55 |
| `packages/maverick-core/maverick/tools/differential_privacy.py`:23-32, 67-68 | Differential-privacy mechanism uses a non-cryptographic PRNG and float inverse-CDF Laplace (predictable, leaky) | Draw randomness from secrets.SystemRandom / os.urandom (CSPRNG) for unseeded use, and replace the inverse-CDF sampler with a snapping mechanism or dis | 0.72 |
| `packages/maverick-core/maverick/tools/oidc_tool.py`:97-111 | OIDC tool reports an identity (subject/email) from an id_token whose signature it never verifies | Verify the id_token against the IdP's JWKS (fetch via the existing guarded_urlopen, match kid/alg, validate iss/aud/exp/nonce) before reporting any su | 0.6 |
| `packages/maverick-dashboard/maverick_dashboard/oidc_login.py`:328-358 | OIDC authorization-code flow sends no `nonce` and never verifies one on the ID token | Generate a `nonce` at login, store it in the signed tx cookie, send it on the authorization request, and after `verify_oidc_token` assert `principal.c | 0.7 |

### Incompleteness marker (TODO/for-now) (3)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `packages/maverick-core/maverick/llm.py`:108-115 | OpenRouter billing rates are self-admitted unverified placeholders in the live pricing table | Verify the three OpenRouter rates against published pricing and remove the TODO/placeholder comments, or omit unverified models from MODEL_PRICES so t | 0.72 |
| `packages/maverick-core/maverick/sandbox/firecracker.py`:22-26,150-159,189-190 | Production sandbox backend ships with self-labeled 'SCAFFOLD' / 'For now' incompleteness markers | Gate the local firectl path behind an explicit experimental flag (or remove it from build_sandbox until complete), keep the working e2b path as the su | 0.72 |
| `packages/maverick-dashboard/maverick_dashboard/saml.py`:21-24 | SAML browser-SSO auth path ships disclosed as untested against any live IdP | Gate SAML behind an explicit experimental/beta flag in config and the wizard until a real Okta and Entra ACS round-trip (signed assertion accepted, ta | 0.7 |

### Hardcoded value (should be config) (2)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `apps/desktop/src-tauri/src/lib.rs`:28,32-39,77-95 | DASHBOARD_PORT constant is bypassed by a hardcoded "8765" string in spawn_dashboard, breaking the documented reconfigure path | Reference the constant everywhere: e.g. `let port = DASHBOARD_PORT.to_string(); .args(["dashboard", "--host", "127.0.0.1", "--port", &port])`. Better, | 0.9 |
| `benchmarks/preflight.py`:71-99, 140-143 | Hardcoded model IDs in preflight pings and BoN-ladder default violate the repo's no-hardcoded-models rule | Resolve the ping model via maverick.llm.ROLE_MODELS (e.g. a cheap 'cheap'/'haiku' role) or model_for_role, and derive the BoN-ladder default from the  | 0.78 |

### Theater (scaffolding, no impl) (2)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `benchmarks/_common/manifests.py`:8-194 | "The manifest is the contract" registry is consumed only by its own test, never enforced by the harness | Wire the harness (swe_bench.py / run_eval.py) to load the matching Manifest by name and actually enforce it: abort/flag a task when per-task spend exc | 0.82 |
| `packages/maverick-core/maverick/marketplace/moderation.py`:1-32,196-356 | Security "moderation gauntlet" is wired into no production publish/install/federation path | Wire moderate_skill/moderate_plugin into the actual publish and federation-import flows (or have tools.marketplace_moderation delegate to it), and sof | 0.78 |

### Dead code (2)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `packages/maverick-core/maverick/cache/redis_tool.py`:1-33 | Distributed cross-host tool cache backend is never wired into the tool cache | Wire from_config() into tool_cache.get_cached/store_cached as a second tier (check redis on local miss, write-through on store), gated by redis_tool.e | 0.85 |
| `packages/maverick-core/maverick/safety/voice_safety.py`:1-69 | Documented inbound transcript-injection screen has zero production callers (dead safety control) | Wire scan_transcript into the inbound voice/STT handlers (live_mic.py / voice_only.py / meeting_listener.py) so every transcript is screened before it | 0.85 |

### Duplication (1)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `packages/maverick-shield/maverick_shield/deobfuscate.py`:116-160 | Phase-aligned base64 de-obfuscation logic duplicated across two security modules | Extract a single shared helper (e.g. _deobfuscate.decode_b64_blobs(text, *, max_blobs, max_windows)) and have both builtin_rules and deobfuscate call  | 0.78 |

---

## Appendix B — Low-severity findings

*178 findings.*

### Reliability gap (51)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `apps/desktop/src-tauri/src/lib.rs`:99-101 | open_in_browser leaks the spawned child handle (no wait), risking a zombie on Unix | Capture the Child and either `.wait()` (these launchers return quickly) or detach it deliberately with a comment; on Unix consider double-fork/setsid  | 0.45 |
| `apps/installer-desktop/src-tauri/src/lib.rs`:127-141 | Child process is not reaped/killed if wait() returns an error | On the wait() error branch, emit an `install-failed` event (and optionally `child.start_kill()`) before returning, mirroring the non-success branch so | 0.6 |
| `apps/mobile-companion/App.tsx`:26-29 | Settings load has no error handling; a rejected SecureStore call hangs the app on the loading screen | Attach a .catch to set a safe default and surface an error state, e.g. loadSettings().then(setSettings).catch(() => setSettings({ baseUrl: DEFAULT_BAS | 0.6 |
| `apps/mobile-companion/src/poll.ts`:23-45 | Polling has no overlap guard or per-tick timeout; slow/stalled fetches can stack | Skip a tick while one is in flight (a useRef boolean), and attach an AbortController with a timeout so a stalled fetch is cancelled before the next in | 0.55 |
| `apps/mobile-companion/src/screens/SettingsScreen.tsx`:23-27 | save() has no error handling; keychain write failure is silently unhandled and onSaved fires regardless of feedback | Wrap the body in try/catch, set an error note on failure (e.g. setNote('Could not save settings: ' + msg)) and only call props.onSaved() after a succe | 0.72 |
| `apps/mobile-skills/kivy-shell/main.py`:37-42 | load_skill assumes importlib spec/loader are non-None | Guard the spec: if spec is None or spec.loader is None, raise the same descriptive ImportError/FileNotFoundError used elsewhere so failures stay legib | 0.5 |
| `apps/vscode-extension/src/extension.ts`:282-285 | Live-watch silently dies on recoverable HTTP error responses (no reconnect, body unconsumed) | Treat 5xx (and connection-level) failures uniformly: consume/drain res, and schedule setTimeout(connect, backoffMs) with the same exponential backoff  | 0.7 |
| `benchmarks/_common/contamination_guard.py`:144-147 | Hash-vs-raw-brief detection is a fragile len==16-and-hex heuristic that silently misclassifies short hex briefs | Use an explicit prefix or a separate file/column to mark precomputed hashes (e.g. 'sha256:<hex>') instead of inferring from length+charset, and store/ | 0.6 |
| `benchmarks/_common/contamination_guard.py`:66-67 | Training-cutoff vs publication-date check uses raw string comparison with no date validation | Parse both sides with datetime.date.fromisoformat() (or dateutil) inside a try/except, compare as dates, and emit a low-severity 'unparseable_date' fl | 0.62 |
| `benchmarks/moat_rigorous.py`:419-432 | Worker builds a config.toml via unescaped %-interpolation of model name and codebase path | Build the config with a TOML serializer (tomli_w / tomlkit) or at minimum json.dumps the string values so quotes/backslashes are escaped, rather than  | 0.6 |
| `benchmarks/recall_precision.py`:20 | Benchmark couples to a private underscore-prefixed kernel internal | Expose a thin public wrapper (e.g. maverick.skills.score_lexical or a relevant_skills(...) public entry that accepts min_score) and have the benchmark | 0.55 |
| `benchmarks/run_eval.py`:23-33 | Dynamic module loader has no error handling on spec/exec failures | Guard spec is None and wrap exec_module to raise a clear RuntimeError naming the missing adapter file, so a misregistered benchmark fails with an acti | 0.4 |
| `deploy/relay/relay.py`:89-91 | Malformed Content-Length header raises an uncaught ValueError, crashing the request thread instead of returning a clean 400 | Wrap the parse: `try: length = int(self.headers.get("Content-Length") or 0)` / `except (TypeError, ValueError): return self._send(411, b'{"error":"bad | 0.85 |
| `deploy/relay/relay.py`:102-103 | Caller-supplied 'budget' is forwarded to the dashboard with no type or range validation | Validate at the edge: coerce with `float(data['budget'])` inside a try/except returning 400 on failure, and clamp to a sane non-negative ceiling befor | 0.7 |
| `extensions/browser/popup.js`:135-141 | Popup messages content script via chrome.tabs.sendMessage without tabs/activeTab permission | Either add the activeTab permission (still minimal, granted only on user gesture) to make tabs.sendMessage robust across browsers, or document explici | 0.45 |
| `extensions/widget/maverick-widget.js`:51 | Shadow-DOM-less fallback silently loses the CSS isolation the comment promises | Either drop the fallback (Shadow DOM is baseline in all supported browsers) or namespace all selectors under a unique container class in the non-shado | 0.55 |
| `go/model-proxy/cmd/model-proxy/main.go`:40-57 | Empty provider key downgraded to a warning, so the proxy starts and fails-open on its core key-custody guarantee | Either exit non-zero on empty APIKey (treat it like the missing ClientToken on lines 36-39) or gate the start-with-no-key path behind an explicit opt- | 0.55 |
| `packages/maverick-core/maverick/automation_import/n8n.py`:186-204 | n8n fetch silently stops at 100 pages with no signal on truncation | After the loop, if cursor is still truthy (cap reached rather than exhausted), emit a warning / raise / return a note so the truncation is visible to  | 0.5 |
| `packages/maverick-core/maverick/cli/__init__.py`:102-152 | Operational error classification by brittle substring/typename matching can misclassify real failures | Branch on the provider SDK's typed exception classes (anthropic.AuthenticationError, NotFoundError, RateLimitError, APIConnectionError) and HTTP statu | 0.55 |
| `packages/maverick-core/maverick/compaction/hybrid.py`:239-248 | fit() trainer reaches into ContextualBandit private attribute _table | Aggregate via the bandit's public API (iterate contexts and call stats(context)) under its lock, or add a public snapshot() method to ContextualBandit | 0.6 |
| `packages/maverick-core/maverick/compaction/multimodal.py`:65-77 | JPEG dimension sniffer can misread non-SOF markers; saved only by a broad except | Skip the length read for standalone markers (0xD0-0xD9, 0x01) and only treat SOF0/1/2/3/5/6/7/9-15 as length-prefixed; add a couple of real JPEG fixtu | 0.55 |
| `packages/maverick-core/maverick/github_app.py`:378-401 | Auto-`git add -A` of an unsupervised agent's entire workdir into a draft PR | Limit auto-staging to tracked modifications (`git add -u`) or an explicit allowlist of changed paths, and/or scrub the staged diff for secret-shaped c | 0.4 |
| `packages/maverick-core/maverick/health.py`:136-139,166-169 | doctor's live Anthropic/OpenAI key probe sets no client timeout and can hang `maverick doctor` for minutes | Pass a short client timeout, e.g. anthropic.Anthropic(api_key=key, timeout=5.0) and OpenAI(api_key=key, timeout=5.0) (or wrap with a per-call .with_op | 0.78 |
| `packages/maverick-core/maverick/killswitch.py`:113-144 | Cluster-wide shared-halt check fails OPEN on any error while caching the previous result, so a persistent shared-store fault can silently mask a real clust | Distinguish transient from sustained failures: track consecutive shared-check errors and, past a small threshold, escalate (log at error/page the oper | 0.5 |
| `packages/maverick-core/maverick/mcp_client.py`:1042-1059 | HTTP MCP client ignores Mcp-Session-Id on the initialize response | Honor an empty/changed Mcp-Session-Id by updating or dropping self._session_id, and surface a debug log when the server omits it after a prior assignm | 0.3 |
| `packages/maverick-core/maverick/migrate.py`:191-219 | Hand-rolled TOML writer used by the only mutating path does not escape/round-trip all value types | Before enabling any entry in REWRITES, replace _write_toml with a real round-tripping emitter (e.g. tomlkit) that preserves comments/formatting, or re | 0.5 |
| `packages/maverick-core/maverick/notification_batcher.py`:179-196 | Daemon flusher thread leaks on reset_shared() and never stops | Give the batcher a threading.Event stop flag, have _loop wait on it instead of bare time.sleep, and signal+join (best-effort) the existing flusher in  | 0.7 |
| `packages/maverick-core/maverick/notifications.py`:66-90 | ntfy notification body is not sanitized/length-bounded; only the Title header is CRLF-stripped | Truncate the notification body to a sane bound (e.g. a few KB) before sending, consistent with the X-Title/header limits ntfy and the other backends e | 0.45 |
| `packages/maverick-core/maverick/provider_cost_cap.py`:276-298 | Per-period alert-dedup set `_alerted` is process-local module state, never pruned | Either soften the docstring to 'once per period per process', or move the alert-dedup into the shared ledger (e.g. a sentinel row) so it is genuinely  | 0.55 |
| `packages/maverick-core/maverick/provision.py`:355 | Tool synthesis passes the capability phrase (g.need) instead of a declared tool-name field (latent fragility) | Store the canonical tool identifier on the gap (e.g. CapabilityGap.tool_name) and pass that to _generate_tool. | 0.3 |
| `packages/maverick-core/maverick/replay/trace.py`:102-115 | replay() gives no per-handler error isolation — one failing handler aborts the whole replay | Wrap handler(ev) in try/except, log the failing seq/kind, and optionally surface errors via the return value or a strict=False flag, so one bad event/ | 0.55 |
| `packages/maverick-core/maverick/replay/video.py`:83-91 | ffconcat manifest breaks if frame directory path contains a single quote | Escape each path before embedding: replace "'" with the sequence quote-backslash-quote-quote inside the single-quoted file lines (or build the manifes | 0.7 |
| `packages/maverick-core/maverick/reviewer.py`:59-60,118-123,143-146 | Reviewer trusts the model's self-reported approves flag instead of enforcing the stated approval rule | Derive the verdict in _parse: approves = (confidence >= 0.75) and not any(c.severity == "blocker" for c in comments); keep the model's boolean only as | 0.72 |
| `packages/maverick-core/maverick/runner.py`:72-77 | inflight_goals() reads a private CPython semaphore attribute (_value) used by /healthz and /metrics gauges | Maintain an explicit `_inflight` counter incremented/decremented under a lock (or an itertools-style atomic) around the acquire/release in run_goal_in | 0.55 |
| `packages/maverick-core/maverick/sandbox/modal_backend.py`:95-105 | Modal exec reads sb.stdout/stderr/returncode with no guard that the sandbox actually produced them | Pin to the documented Modal Sandbox stdout/stderr stream API and, if the expected `.read` is absent, raise/return an explicit error ExecResult rather  | 0.55 |
| `packages/maverick-core/maverick/tenant/registry.py`:299-323 | tenant_spend_today reaches into UsageLedger._load() private API | Add a public method on UsageLedger (e.g. spend_for_day(day) or a today_dollars() summary) and call that; keep _today logic behind a public quotas help | 0.55 |
| `packages/maverick-core/maverick/tools/android.py`:150-159 | input_text only escapes spaces, not other adb-special characters | Escape the full set of adb `input text` metacharacters (percent-encode or backslash per adb's documented rules) rather than only spaces, and/or note t | 0.55 |
| `packages/maverick-core/maverick/tools/arxiv.py`:48-80 | Atom/XML response parsed with regex, with a self-admitted brittleness comment | Parse with xml.etree.ElementTree (stdlib, namespace-aware) — register the Atom namespace and iterate entry elements — so titles/summaries with markup, | 0.6 |
| `packages/maverick-core/maverick/tools/ask_user.py`:16-21 | ask_user dereferences args['question'] directly, raising KeyError if the model omits it | Validate the argument before use: `q = str(args.get("question", "")).strip(); if not q: return "ERROR: 'question' is required."` — matching the valida | 0.7 |
| `packages/maverick-core/maverick/tools/hackernews.py`:44-51 | hackernews HTTP client bypasses the repo's SSRF-safe wrapper used elsewhere | Route hackernews fetches through tools/_ssrf.safe_get (or document explicitly why this tool is exempt), keeping all outbound HTTP behind one hardened  | 0.55 |
| `packages/maverick-core/maverick/tools/honeytoken.py`:33-43 | Honeytoken exfiltration scanner only detects tokens delimited by whitespace | Scan with a compiled regex over the raw text instead of whitespace tokens, e.g. re.findall(r"MAVHT_(?:aws\|api\|pat\|generic)_[0-9a-f]{32}", text), so | 0.6 |
| `packages/maverick-core/maverick/tools/lambda_tool.py`:62-66 | list_functions format spec crashes on a None field instead of degrading | Coerce to string before the width spec, e.g. `f.get('FunctionName') or '?'` and `str(f.get('Runtime') or '-'):<14`, so a missing field renders as a pl | 0.7 |
| `packages/maverick-core/maverick/tools/latex_tool.py`:47-71 | PDF render leaks its temp working directory (and the LaTeX source/PDF) on every call | Wrap the work in `with tempfile.TemporaryDirectory(prefix='mvk-latex-') as d:` (or rmtree in a finally) so the scratch dir and its contents are remove | 0.8 |
| `packages/maverick-core/maverick/tools/youtube.py`:54-59 | Uses youtube_transcript_api.get_transcript static API removed in the library's 1.x line | Detect the API surface (try the 1.x `YouTubeTranscriptApi().fetch(video_id, languages=...)` and fall back to the legacy classmethod) and pin a known-c | 0.45 |
| `packages/maverick-core/maverick/tree_of_thought.py`:158-168 | Critic JSON-parse failure silently falls back to a length heuristic to pick the winning plan | On critic parse failure, prefer a structured retry (re-prompt the critic for strict JSON once) and, if still unparseable, fall back to the first candi | 0.55 |
| `packages/maverick-core/maverick/vector_store/pgvector_store.py`:162-173,185 | Embedding vectors serialized via repr(float(x)) can emit nan/inf and corrupt inserts/queries | Validate vectors are finite (math.isfinite) before serialization and raise a clear ValueError, or pass vectors via psycopg's pgvector adapter/register | 0.5 |
| `packages/maverick-dashboard/maverick_dashboard/static/maverick-analytics.js`:57-62 | Numeric goal counts interpolated into SVG aria-label/text without esc() (defense-in-depth, not exploitable) | For uniformity, wrap the count in esc() or Number() at interpolation sites so the escaping contract is visibly consistent across the function; no beha | 0.3 |
| `packages/maverick-evolve/maverick_evolve/agent_adapter.py`:73-87 | Hand-rolled overlay TOML writer does not escape section/key names | Use a real TOML serializer (tomli_w / tomlkit) for the overlay, or validate/escape keys against a `[A-Za-z0-9_-]+` whitelist and raise on anything els | 0.5 |
| `rust/mvk-scan-wasm/src/lib.rs`:34-39 | Length-mismatch error message uses unchecked multiplication while the guard uses saturating_mul | Reuse the already-computed saturating product for the message, e.g. compute `let expected = width.saturating_mul(height).saturating_mul(3);` once and  | 0.55 |
| `scripts/stress/mp_jobqueue_stress.py`:94 | Unconditional mp.set_start_method("fork") is platform-fragile and raises if a start method is already set | Use mp.get_context("fork") to obtain a fork context for the Process objects (or guard the call: only set it when not already set, and fall back to the | 0.55 |
| `web/widget/maverick-widget.js`:95-100 | Raw fetch error/status surfaced verbatim into the chat UI | Map known status codes to friendly text (e.g. 401/403 -> 'Sign in to your dashboard first', 5xx -> 'Service unavailable'), and only show 'Started.' wh | 0.5 |

### Misleading name / docstring / comment (48)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `apps/installer-msi/test_wxs.py`:64-69 | Hardcoded-path check uses a narrow heuristic that misses most absolute paths | Broaden to flag any drive-letter absolute path (`[A-Za-z]:\\`) and unix absolute prefixes outside the allowlist, or assert that all `Source=`/path att | 0.55 |
| `apps/mobile-companion/src/api.ts`:87-98 | Comment claims it 'mirrors' the VS Code extension, but behavior diverges | Reword the comment to 'Stricter than the VS Code extension's shouldSendDashboardToken: that prompts and may send over http on confirm; this fails clos | 0.6 |
| `apps/mobile-skills/test_mobile_skills.py`:50-58 | Docstring claims the test checks the 'fetch path' but the regex never matches a fetch() call | Either add a regex that captures fetch("...") string literals and assert those are relative too, or rewrite the comment to say it checks 'script src,  | 0.6 |
| `apps/zed-extension/src/lib.rs`:29-29 | Comment references stale CLI path maverick/cli.py (now a package, cli/__init__.py) | Update the comment (and the README/tasks references) to point at maverick/cli/__init__.py, or grep the repo and fix all `maverick/cli.py` mentions in  | 0.82 |
| `benchmarks/harness.py`:88-98 | run_one unconditionally stamps source='measured' even though the comment insists comparator rows must be source='manual' | Add an explicit source argument/flag to append_results and validate it, or have _ensure_results_table/append_results refuse a 'measured' row that wasn | 0.55 |
| `benchmarks/security/latency_bench.py`:59-62 | Percentile helper fabricates p50/p95/p99 from a single sample when n<=1 | When len(s) < a minimum sample floor, mark the row as insufficient-sample (or omit p95/p99) instead of broadcasting the lone sample across all quantil | 0.55 |
| `benchmarks/test_cost_accumulation.py`:112-120 | Test name claims an invariant the test explicitly does not enforce | Rename to reflect what it checks (e.g. test_negative_cost_accumulates_arithmetically) or add and assert a real guard that rejects/clamps negative cost | 0.7 |
| `benchmarks/test_wave12_operational.py`:121-123 | Misleading dead PATH assignment (a file, not a directory) immediately overwritten | Drop the bogus seed dict and just copy the environment then set the flag: `env = os.environ.copy(); env["MAVERICK_BENCH_DRY_RUN"] = "1"`. | 0.8 |
| `packages/maverick-channels/maverick_channels/__init__.py`:9-17 | Module docstring claims "18 wired adapters" but enumerates only 17 | Change "18 wired adapters" to "17 wired adapters" (or add the missing adapter to the list if one was intended), and consider deriving the count from a | 0.82 |
| `packages/maverick-core/maverick/adaptive_compute.py`:4-5 | Docstring cites an apparently fabricated arXiv paper as SOTA grounding | Replace the fabricated arXiv ID with either a real, verifiable citation or a plain description of the heuristic (e.g. 'concentrate inference compute o | 0.78 |
| `packages/maverick-core/maverick/coding_mode.py`:943-954 | defensive_validate docstring claims a 20% cheating-overlap threshold but the code enforces 50%/35% | Update the defensive_validate docstring bullet to match the implemented thresholds (>=50% longest verbatim run OR >=35% 3-gram Jaccard), ideally refer | 0.9 |
| `packages/maverick-core/maverick/coding_mode.py`:1066-1118 | detect_test_runner return-type docstring omits the hint-miss to 'unsupported' branch | Expand the docstring to note the hint-miss -> 'unsupported' behavior, or add an explicit Literal return type so the contract is machine-checked. | 0.55 |
| `packages/maverick-core/maverick/compliance.py`:142-145 | Audit-logging control hardcoded to 'active' without probing that logging actually works | Probe audit writability like the tamper-evident check probes signing, and downgrade to 'action_needed' if it can't. | 0.55 |
| `packages/maverick-core/maverick/credit.py`:88-94 | normalize_credit equal-split fallback masks all-harmful swarm as uniform contribution | Return all-zero weights when no contributor has positive credit (so a round with no demonstrated value contributes no learning signal), and document t | 0.5 |
| `packages/maverick-core/maverick/domain_eval.py`:36-39, 86-93, 139-144 | Citation-rubric markers so broad the legal_research golden case passes on almost any markdown output | Tighten _CITATION_MARKERS to anchored citation forms (e.g. 'source:', 'according to', 'reference:', '§', a bracketed-number regex like r'\[\d+\]') and | 0.55 |
| `packages/maverick-core/maverick/dreaming.py`:909-916 | Rehearsal success graded by English/emoji prefix string-matching | Make the failure-prefix set configurable and locale-independent (e.g. a structured result/status enum from the agent rather than scraping prose), and  | 0.5 |
| `packages/maverick-core/maverick/experience.py`:3-8 | Fabricated/future arXiv citation used to lend authority in a shipping module docstring | Replace fabricated/future arXiv IDs with real, verifiable citations or remove the specific ID and describe the technique generically (e.g. 'experience | 0.55 |
| `packages/maverick-core/maverick/marketplace/stats.py`:6-8 | Stats docstring lists a rating kind ("channels") the ledger never supports | Align the docstring example with ratings._VALID_KINDS (templates/skills/personas/mcp) or make the kind list a shared constant referenced by both modul | 0.7 |
| `packages/maverick-core/maverick/replay/video.py`:44-49 | _event_ts assumes float epoch timestamps; ISO-8601 audit ts silently collapse all frame durations to the minimum | Parse both representations: try float(ts), and on failure fall back to datetime.fromisoformat(ts).timestamp(); add a test covering an ISO-string ts so | 0.5 |
| `packages/maverick-core/maverick/retry/__init__.py`:3-6 | Backoff docstring states fixed 1s/2s/4s/8s delays but actual delays are jittered and env-tunable | Update the docstring to state the delays are base*2^attempt capped at MAX_DELAY (default 30s) with 50-100% jitter, and that MAVERICK_LLM_RETRY_ATTEMPT | 0.6 |
| `packages/maverick-core/maverick/retry/classifier.py`:12-13 | MALFORMED policy docstring claims 'retry once with same prompt' but no prompt resubmission exists here | Reword the docstring to describe only what the policy table encodes (retry budgets/backoff per class) and explicitly state that delay/attempt scheduli | 0.55 |
| `packages/maverick-core/maverick/routing.py`:2-13,66-85 | Cascade docstring describes a Haiku->Sonnet->Opus escalation that pick() never produces (escalation jumps straight to Opus) | Either implement the intermediate tier (return MODEL_SONNET for the confidence/tool-depth signals and reserve MODEL_OPUS for retries/thinking) or rewr | 0.62 |
| `packages/maverick-core/maverick/safety/secret_detector.py`:6, 30-32 | Docstring advertises "generic high-entropy secret" detection that does not exist | Either add a real Shannon-entropy fallback rule (e.g. flag >=20-char base64/hex runs above an entropy threshold) to back the claim, or correct the doc | 0.85 |
| `packages/maverick-core/maverick/safety/tool_acl.py`:263-267 | Stale comment claims it is "adding" a public remove() that was never added | Add a public ToolRegistry.remove(name) (or unregister) method and call it here, or update the comment to acknowledge the deliberate private-API coupli | 0.8 |
| `packages/maverick-core/maverick/safety/voice_safety.py`:17-18 | Docstring claims module-wide fail-open, but scan_transcript has no exception guard | Either wrap scan_transcript's body so it returns TranscriptVerdict(ok=True) on internal error (matching the documented fail-open contract) or narrow t | 0.6 |
| `packages/maverick-core/maverick/sandbox/firecracker.py`:244-264 | Firecracker Docker-fallback ignores the configured image and always uses python:3.12-slim | Mount/run the configured self.image (resolved via the same language map) in _docker_fallback instead of the hardcoded python:3.12-slim, or document ex | 0.7 |
| `packages/maverick-core/maverick/shield_ensemble.py`:1-15,83-84 | Ensemble docstring claims an injection+jailbreak+exfil+policy lineup but ships injection/exfil/pii with no policy member | Either add a real PolicyMember (delegating to an existing policy/tool-ACL check) and a distinct jailbreak member, or correct the docstring to state th | 0.72 |
| `packages/maverick-core/maverick/task_graph.py`:269-300 | Loop variable `path` reused for two unrelated meanings in `_run` | Rename the unpacked result to `crit_path, length = g.critical_path()` so the file path binding from line 269 is never clobbered. | 0.7 |
| `packages/maverick-core/maverick/tenant/concurrency.py`:58-67 | release() docstring claims 'Idempotent-safe' but a spurious extra call drops a live slot | Either make release truly idempotent against over-release (e.g. track per-call tokens/handles so an unmatched release is a no-op), or drop 'Idempotent | 0.6 |
| `packages/maverick-core/maverick/tools/capability_leak_fuzzer.py`:1-16,110-124 | 'capability_leak_fuzzer' performs no fuzzing | Rename to capability_leak_check / capability_grant_audit (matching its real behavior), or, if a real fuzzer is intended, add input-mutation over the g | 0.55 |
| `packages/maverick-core/maverick/tools/knowledge_graph.py`:111-116 | knowledge_graph 'dot' op emits invalid Graphviz (Python repr, single-quoted IDs) | Quote identifiers per the DOT spec: emit double-quoted strings with internal double-quotes and backslashes escaped, e.g. def _q(x): return '"' + x.rep | 0.82 |
| `packages/maverick-core/maverick/tools/latency_heatmap.py`:33-39, 80-81 | Heatmap shading collapses to all-max (█) whenever every cell value is equal, and legend advertises a low band that can never render | On hi<=lo render a neutral mid/low block (or a flat indicator) rather than the max block, and document that a single-value matrix has no contrast; thi | 0.55 |
| `packages/maverick-core/maverick/tools/memleak_quarantine.py`:1-17, 67-83, 137-151 | "Memory-leak quarantine" only flags components as QUARANTINE — it never quarantines anything | Rename to memleak_detector / leak_scan and describe it as "flags components whose RSS grows monotonically (positive slope + good fit)"; keep "quaranti | 0.55 |
| `packages/maverick-core/maverick/tools/memory.py`:237-245 | memory insert: schema says '1-based line to insert AFTER' but code inserts BEFORE a 0-based index | Pick one semantic and make schema description, the inline error string, and the slice math agree (e.g. document it as 0-based insert-before-index, whi | 0.6 |
| `packages/maverick-core/maverick/tools/mutation_test.py`:5-7, 38-39, 85 | Mutation-test docstring claims a "rewritten line" but the output emits the original, unmutated line | Either change the docstring to say "the original line and the operator swap to apply" (cheap, accurate), or actually unparse the mutated node with `as | 0.7 |
| `packages/maverick-core/maverick/tools/risk_tier_classifier.py`:58-66 | Risk-tier classifier lets a caller-supplied custom_weight silently downgrade a HIGH action | Clamp custom_weight to a non-negative range (or to a small bounded +/- delta) and never allow it to lower the tier below what the hard signals (irreve | 0.55 |
| `packages/maverick-core/maverick/tools/s3_attachments.py`:34-46 | "Content-addressed" key is actually filename-addressed (sha256 of the name, not the bytes) | Rename to name_addressed_key / key_for_name and describe it as a deterministic name-derived key, reserving "content-addressed" for a path that hashes  | 0.7 |
| `packages/maverick-core/maverick/tools/semantic_code_search.py`:1-16, 118-123, 196-205 | "semantic_code_search" / "search by intent" is a literal keyword-overlap matcher, not semantic search | Rename to lexical_code_search (or symbol_search) and reword the description to 'lexical keyword-overlap search over Python symbols', or actually back  | 0.55 |
| `packages/maverick-core/maverick/tools/sla_breach.py`:1-30, 85-92, 139-152 | "SLA-breach automation" with action=failover never executes any action — it only returns a recommendation string | Rename to sla_breach_check / sla_advisor and change the description from "SLA-breach automation" to "SLA-breach evaluator that recommends an escalatio | 0.6 |
| `packages/maverick-core/maverick/tools/slack_bot.py`:116-119 | Upload comment says 'PUT the bytes' but code POSTs | Change the comment to 'POST the bytes' to match the call (and Slack's documented v2 upload contract). | 0.9 |
| `packages/maverick-core/maverick/tools/sql_query.py`:1-9, 56-71, 187-200 | Docstring guarantees workspace path confinement that is bypassed when no sandbox is bound | Make the factory require a sandbox (raise if None) or have `_safe_path` reject absolute/`..` paths even when sandbox is None for security-sensitive to | 0.6 |
| `packages/maverick-core/maverick/vector_store/pgvector_store.py`:125-129 | _ensure_vector_column builds DDL with Python %-formatting instead of psycopg parameters | pgvector dimension cannot be bound as a normal parameter, so format it explicitly and safely: f"... vector({int(dim)})" with a comment that it is a va | 0.6 |
| `packages/maverick-core/maverick/world_model.py`:1523-1563 | search_goals only scans a bounded recent window under encryption, silently missing older matches | Return a truncation flag / total-scanned count to the caller, or back text search with a searchable encryption / blind-index scheme so matches beyond  | 0.5 |
| `packages/maverick-core/maverick/world_model_backends/postgres.py`:19-23 | Module docstring understates scope: claims only 'shape + hot-path methods' while full surface is implemented | Rewrite the 'Implementation scope' paragraph to reflect the now-complete public surface, or remove it. | 0.85 |
| `packages/maverick-evolve/maverick_evolve/eval_harness.py`:40-44 | Default fitness 'scorer' is case-insensitive substring containment over whole output | Make the live CLI path require a `check` predicate or an explicit semantic/verifier-backed scorer (the kernel already has `verifier`), and at minimum  | 0.62 |
| `packages/maverick-mcp/maverick_mcp/server.py`:922-925 vs 983-989 | Enterprise license preflight enforced on maverick_start but omitted on maverick_resume | Either call require_enterprise_or_die() in _tool_resume too (matching _tool_start), or drop it from _tool_start and rely solely on the process-entry c | 0.55 |
| `packages/maverick-shield/maverick_shield/cascade.py`:1-18 | Module docstring frames a regex/heuristic cheap-probe with Constitutional-Classifiers-v2 efficacy numbers it does not deliver | Reword the docstring to state plainly that this ships only the cheap heuristic probe plus a pluggable deep-scan hook (unset by default), and cite the  | 0.5 |
| `sdks/plugin-ts/src/index.ts`:231-237 | Untrusted count fields passed through unclamped despite "never trusts oversized input" claim | Clamp or recompute the counts: take the smaller of the reported number and the retained array length, or reject non-finite/negative numbers, e.g. elem | 0.6 |

### Swallowed error / silent failure (41)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `apps/desktop/src-tauri/src/lib.rs`:98-108 | open_in_browser silently discards every launcher spawn result, so a failed 'Open in Browser' gives the user no signal | Log the error to stderr (mirror the eprintln! pattern in spawn_dashboard) and ideally surface a one-line notice/toast in the webview so the user knows | 0.6 |
| `apps/installer-cli/maverick_installer/bridge.py`:119-125 | Sidecar top-level handler catches BaseException-shaped failures and exits, masking the real failure to the GUI | Include type(e).__name__ and a remediation hint in the error frame (mirror show_install_failure), and write a diagnostic line to stderr/log so the Tau | 0.55 |
| `apps/installer-cli/maverick_installer/wizard.py`:399-417 | Validation-cache load/save swallow all OSError/ValueError silently, so a poisoned cache can serve stale 'ok' verdicts forever | Keep the best-effort swallow but only ever cache definitively-ok (not 'skipped') results, and shorten/disable caching for unverifiable verdicts so a t | 0.5 |
| `apps/installer-desktop/src-tauri/src/lib.rs`:113-125 | Log-streaming reader loops silently truncate output on the first I/O error | Use `loop { match lines.next_line().await { Ok(Some(l)) => {..}, Ok(None) => break, Err(e) => { let _ = a.emit("install-log", format!("[log read error | 0.72 |
| `benchmarks/swe_bench.py`:319-323 | Broad except: pass around gold-patch cache reset with no logging | Narrow the except (ImportError is expected/benign; other exceptions are not) and emit a stderr warning when the reset itself fails, mirroring the warn | 0.55 |
| `go/model-proxy/server.go`:74-77 | Request body read errors are silently swallowed and forwarded as empty | On io.ReadAll error, return a 400 (or 502) to the client and log the read failure rather than forwarding a nil body; do not treat a read error as an e | 0.55 |
| `packages/maverick-channels/maverick_channels/bluesky.py`:288-312 | Proactive send() swallows HTTP failures while the sibling reply path checks status | Bind the response and log on failure exactly as _reply() does: r = await client.post(...); if r.status_code >= 400: log.warning('bluesky send failed ( | 0.85 |
| `packages/maverick-channels/maverick_channels/mastodon.py`:223-240 | send() drops the HTTP response, silently losing failed direct messages | Capture and check the response like _post_reply(): resp = await client.post(...); if resp.status_code >= 400: log.warning('mastodon send failed (%d):  | 0.85 |
| `packages/maverick-core/maverick/agent.py`:813-855 | _build_system swallows ALL exceptions silently (no log) on five prompt-augmentation paths | Catch narrowly (ImportError for the optional-feature import) and log.debug/warning the unexpected case, mirroring lines 1708-1716 and the skills block | 0.6 |
| `packages/maverick-core/maverick/agent.py`:2470-2519 | Benchmark cheating-detector (defensive_validate) fails open to patch acceptance on any exception | On exception, log + post to the blackboard and treat it as a non-fatal warning at minimum, or fail closed (request revision) in benchmark/opaque mode  | 0.55 |
| `packages/maverick-core/maverick/ai_act_package.py`:32-41 | Compliance-doc generator swallows every exception via blanket _safe wrapper | Narrow the catch (or at least log.warning/exc_info on failure) and surface a distinct 'error gathering evidence' marker separate from the legitimate ' | 0.5 |
| `packages/maverick-core/maverick/audit/worm.py`:163-182 | S3 WORM verify() swallows every exception as a silent verification result | Catch botocore ClientError specifically; distinguish NoSuchKey/checksum mismatch (real failure -> False) from transient/credential errors (log.warning | 0.5 |
| `packages/maverick-core/maverick/automation_import/__init__.py`:50-54 | Feature-flag check swallows every config exception and silently disables import | Catch only the specific expected errors (e.g. FileNotFoundError / config-parse error) and let unexpected exceptions propagate or at least log at warni | 0.55 |
| `packages/maverick-core/maverick/benchmarks/reproducible_v2.py`:179-185 | Seed-kwarg fallback masks a solver's own internal TypeError and silently re-invokes it | Detect the seed-kwarg arity once via inspect.signature(solver) (or use functools.partial/try-once-outside-the-loop), and only fall back to solver(task | 0.82 |
| `packages/maverick-core/maverick/cli/__init__.py`:3156-3175 | Progress poller swallows every exception each iteration, so a persistent read failure spins silently with no output and no error | Log the first exception at debug level (or once, then stop the poller) instead of an unconditional silent pass, so an operator running with MAVERICK_D | 0.5 |
| `packages/maverick-core/maverick/coding_mode.py`:1084-1133 | package.json read/parse errors swallowed by blanket except, silently defaulting to jest with no log | Narrow to (OSError, json.JSONDecodeError), log the parse failure at debug with the path, then fall back to jest, keeping robustness while leaving a br | 0.5 |
| `packages/maverick-core/maverick/cost/by_tag.py`:107-123 | _goal_tag() swallows all exceptions from world.get_goal(), masking real DB errors as untagged spend | Narrow the catch to the actual not-found signal (KeyError/None return) and let unexpected backend errors propagate, or log them, so a failed lookup du | 0.5 |
| `packages/maverick-core/maverick/cost/router.py`:175-201 | role_policy() catches bare Exception when reading routing config, hiding malformed config | Catch the specific expected error (FileNotFoundError / config-not-present) and let unexpected exceptions propagate or at minimum log.warning with the  | 0.6 |
| `packages/maverick-core/maverick/github_app.py`:236-277 | PR creation via gh silently returns None on failure, losing the agent's pushed work | Return a typed failure (or populate PRResult.error via scrub()) distinguishing push failure, gh-create failure, and 'no changes', so the webhook handl | 0.55 |
| `packages/maverick-core/maverick/glance.py`:33-36 | Broad except masks world-model failures as an empty goal list | Narrow to the expected DB/IO exceptions, log the failure, and let the caller decide; consider a sentinel/error field in the payload so the watch can r | 0.6 |
| `packages/maverick-core/maverick/marketplace/moderation.py`:165-168 | Secret-detector import failure silently degrades a security gate to no finding | Narrow the except to ImportError, and on failure return a Severity.FLAG/REJECT "secret scanner unavailable" finding (fail-closed) instead of an empty  | 0.55 |
| `packages/maverick-core/maverick/notifications.py`:163-240 | notify() silently swallows backend send results in the async path; returns optimistic count | Either document that the async return is 'backends dispatched' (best-effort, fire-and-forget) and rename accordingly, or collect the futures and recon | 0.55 |
| `packages/maverick-core/maverick/persona.py`:38-43 | Config load wrapped in bare except returning empty persona | Log the exception at debug/warning before returning the empty persona, and ideally catch the specific config-load error rather than bare Exception. | 0.45 |
| `packages/maverick-core/maverick/prm.py`:163-192 | RemotePRM silently swallows all network/HTTP/JSON errors with zero logging, masking a down or misconfigured scoring endpoint | Add a _warn_once helper to RemotePRM (mirroring LearnedPRM) and log the status code / exception on the first fallback, and ideally a periodic re-log,  | 0.7 |
| `packages/maverick-core/maverick/providers/openai_provider.py`:352-365 | Unparseable tool-call arguments silently coerced to {} (logged, but the tool still runs) | Return the tool call with a sentinel/error marker so the agent loop can treat it as a failed tool invocation (emit an error tool_result) instead of ex | 0.5 |
| `packages/maverick-core/maverick/sandbox/firecracker.py`:299-307 | e2b exec result defaults exit_code to 1 and treats any non-2xx body as empty without surfacing the API body | On status>=300, capture run.text (truncated) into stderr so the e2b error message is preserved, and distinguish a genuine command exit code from a tra | 0.5 |
| `packages/maverick-core/maverick/tenant/kms.py`:344-348 | rotate_kek_idempotent swallows all exceptions in the 'already rotated?' probe | Catch only the decrypt/AEAD-mismatch exception types that legitimately mean 'this blob isn't under new_kms' (e.g. EncryptionUnavailable raised for bad | 0.5 |
| `packages/maverick-core/maverick/tools/calendar_tool.py`:60-69 | Calendar config loader swallows all errors and returns default, masking misconfiguration | Narrow the except to the expected config-absent/parse errors and log.warning the underlying exception so a broken config.toml surfaces instead of sile | 0.5 |
| `packages/maverick-core/maverick/tools/email_tool.py`:186-201 | Bare best-effort except Exception: pass around MIME body decode | Narrow to the expected failure (e.g. AttributeError/UnicodeError on None payloads) or at least log.debug the swallowed exception so silent empty-body  | 0.5 |
| `packages/maverick-core/maverick/tools/knowledge.py`:25-26 | knowledge_search swallows KB error detail, returning only the exception class name | Keep the broad catch for loop-safety but emit a structured log/metric with the full exception (e.g. logger.warning("knowledge_search failed", exc_info | 0.6 |
| `packages/maverick-core/maverick/tools/oauth_helper.py`:101-105 | chmod 0600 on the plaintext OAuth token out-file is best-effort and silently swallowed | Create the file with restrictive perms atomically (os.open with mode=0o600 / O_CREAT\|O_EXCL, or set umask before write), and if chmod fails, delete t | 0.55 |
| `packages/maverick-core/maverick/tools/recall.py`:115-117 | Broad except in embedding path swallows all errors and silently downgrades to weaker scorer | Narrow the catch to the expected import/model-load failures, and log the fallback at WARNING (once) so silent degradation of the 'cross-goal memory re | 0.5 |
| `packages/maverick-core/maverick/tools/spend_report.py`:58-67 | Cost accessor silently returns $0.00 on any error in a financial-analytics tool | Narrow the excepts to (TypeError, ValueError, KeyError, AttributeError), and when a row has a cost field that fails to parse (vs. genuinely absent), l | 0.5 |
| `packages/maverick-core/maverick/tools/voice.py`:263-269 | Voice safety redaction fails open: a crash in redact_for_speech lets secrets/PII be spoken aloud | Distinguish import-absent (acceptable fail-open) from a redactor runtime exception (fail-closed): if redact_for_speech is present but raises, refuse t | 0.55 |
| `packages/maverick-core/maverick/trace_pin.py`:81-83 | trace_commit silently swallows all exceptions with no log | Mirror pin_trace: log.debug('trace_commit read failed for goal %s', goal_id, exc_info=True) before returning None so genuine store errors are observab | 0.55 |
| `packages/maverick-core/maverick/training/ingest.py`:39-43 | load_donations silently skips files that fail to parse, dropping records with no audit trail | log.warning the skipped path (and optionally a skipped-count in the final summary) so dropped donations are observable, mirroring the explicit warning | 0.6 |
| `packages/maverick-core/maverick/ux_retrospective.py`:35-37, 53-60, 61-71 | Three broad except Exception blocks in collect() silently zero out UX sections | Narrow the excepts to the specific expected exceptions (e.g. AttributeError for a world lacking the method) and log.warning on unexpected failures, or | 0.62 |
| `packages/maverick-core/maverick/world_model.py`:745-753 | Best-effort chmod failures on the data dir/DB file are swallowed silently | Log at WARNING when a chmod fails on a non-:memory: store (especially the parent dir), so an operator can detect a host where at-rest file permissions | 0.5 |
| `packages/maverick-dashboard/maverick_dashboard/api.py`:1419-1420 | System-of-record deliverable hand-off failure logged without a stack trace | Log with `exc_info=True` (matching the security-register and halt best-effort logs in this file) so the integration failure is diagnosable without cha | 0.72 |
| `packages/maverick-dashboard/maverick_dashboard/control_plane.py`:313-317 | Trust-overview view fails OPEN to active='active' when an agent's lifecycle check raises | On exception set active=False with reason='unknown' (or surface an explicit error state) so an uncomputable agent never renders as healthy; log the ex | 0.55 |
| `scripts/stress/mp_jobqueue_stress.py`:26-40 | Worker process discards its claimed-id record on any mid-run exception, masking the real error as "lost jobs" | Wrap the loop body so the claimed list is written in a finally block (or stream each id to the file as it is claimed and fsync), and surface the child | 0.6 |

### Security (11)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `apps/visionos-plan-tree/MaverickPlanTree/PlanTreeModel.swift`:33-49 | Bearer token sent without enforcing HTTPS on the configurable dashboard URL | Require url.scheme == "https" (or host == 127.0.0.1/localhost) before sending the Authorization header; otherwise surface an error like 'refusing to s | 0.55 |
| `extensions/widget/maverick-widget.js`:42-44, 151-153 | Full-control bearer token read from a client-side script attribute and sent to data-endpoint | Ship a read-only token scope on the dashboard so data-token (when used) cannot drive mutating endpoints, and/or validate that data-endpoint is same-or | 0.5 |
| `packages/maverick-channels/maverick_channels/rich_render.py`:37-40, 120-134 | Generated HTML artifacts load KaTeX/Mermaid from a CDN with no Subresource Integrity pinning | Add Subresource Integrity (integrity="sha384-..." + crossorigin="anonymous") with hashes for exact pinned versions, or vendor the JS/CSS locally under | 0.7 |
| `packages/maverick-core/maverick/grpc_plugin_host.py`:79-102 | Shield scan of plugin tool manifests fails OPEN on any shield error | Treat a shield scan exception on plugin manifest text as a rejection (return False), matching fleet_memory._sanitize. | 0.4 |
| `packages/maverick-core/maverick/mcp_registry.py`:226-244 | Registry install writes MCP auth tokens/headers to config.toml without setting 0600 perms | On the file-creation branch, create with restrictive perms (e.g. os.open with mode 0o600 / os.chmod(p, 0o600) after write), matching the 0600 discipli | 0.5 |
| `packages/maverick-core/maverick/tools/gitlab.py`:67-76 | GitLab connector bypasses the SSRF-safe client used by sibling fetch tools | Route GitLab requests through tools._ssrf.safe_client(base) (already imported by the generic REST factory) so the self-hosted host is validated and IP | 0.55 |
| `packages/maverick-core/maverick/tools/office_convert.py`:64-68 | _safe_path performs no traversal confinement when sandbox is None despite docstring claiming paths are confined | Apply consistent confinement in both branches (resolve against an explicit allowed root and require relative_to it), or have the no-sandbox branch rej | 0.6 |
| `packages/maverick-core/maverick/tools/pandas_query.py`:31-45 | Path confinement silently disabled when sandbox is None | Make the no-sandbox case fail closed: raise (or refuse absolute/`..` paths) instead of returning an unconfined path, so omitting the sandbox cannot si | 0.62 |
| `packages/maverick-core/maverick/tools/shopify_tool.py`:73-86 | Shopify connector uses raw httpx.Client without the SSRF-safe transport | Use _ssrf.safe_client for the fixed myshopify.com host for parity with the generic connector factory; the existing host validation already makes this  | 0.4 |
| `packages/maverick-core/maverick/world_model.py`:642-672 | At-rest decrypt passes unsealed values through by default instead of failing closed | Consider defaulting to strict (withhold) once a deployment is marked enterprise/compliance-floored, or emit a metric/alert (not just a log line) on ev | 0.55 |
| `rust/maverick-verify-audit/src/lib.rs`:238-245 | Rust verifier trusts any lone <key_id>.pub, dropping the Python source's forged-pubkey defense | Replicate the Python trust gate: in load_key_from_dir, after locating <key_id>.pub require that either <key_id>.key or <key_id>.injected also exists i | 0.88 |

### Incompleteness marker (TODO/for-now) (9)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `packages/maverick-channels/maverick_channels/voice.py`:23-31, 219-263 | Retell/Bland outbound contracts shipped untested, presented inline with the live Vapi path | Gate the unverified providers behind an explicit opt-in flag or mark them experimental in the wizard, and add contract tests (recorded/mocked response | 0.55 |
| `packages/maverick-core/maverick/cache/__init__.py`:21-36 | cache.stats()/purge() omit the llm, learning, and tool caches it claims to centralize | Add llm/tool/learning(/redis) to _VALID_SCOPES and route their clear()/purge()/prune() through purge(), and have the CLI call this surface instead of  | 0.65 |
| `packages/maverick-core/maverick/learning_rollout.py`:104-140 | "Live" governed rollout records an audit row instead of deploying; only rollback is real | Either wire the live deploy seam to the real fleet-promotion mechanism (dreaming.promote_shared_insights / the actual staged-activation API) so deploy | 0.6 |
| `packages/maverick-core/maverick/prm.py`:1-26 | Module docstring self-labels as 'scaffold ... queued for v0.3' while shipping in a production code path | Reword the header to state what is production-ready today (Null/Heuristic/Remote/Learned/Linear backends, default Null) versus what is a future roadma | 0.5 |
| `packages/maverick-core/maverick/reflexion.py`:84-87, 267-273 | recall() never loads model_id despite per-model harness contract | Add 'model_id' to the key tuple in recall()'s Reflexion(**{...}) reconstruction (line 268-272) so it matches list_recent(); cover both loaders with a  | 0.72 |
| `packages/maverick-core/maverick/speculative_exec.py`:76-83 | Verify-and-rollback half not shipped; accepted() is a dead seam with no consumer | Either wire accepted() into a real post-turn verification path (re-run on the frontier model on divergence and surface an accept-rate metric), or gate | 0.55 |
| `packages/maverick-core/maverick/tools/shell.py`:97-103 | Benchmark anti-cheat git/secret blocklist is self-admittedly bypassable and the real fix is left unimplemented | Implement the documented robust complement at the sandbox layer (run opaque-mode commands with no network namespace and with .git relocated/made unrea | 0.5 |
| `packages/maverick-dashboard/maverick_dashboard/deliverables.py`:12-15 | Persona-inbox 'awaiting sign-off' is a proxy heuristic; real approval linkage not implemented | Land the governed-handoff record (persist the gate decision point and its pending/closed state against the run id) and compute 'awaiting' from that re | 0.6 |
| `web/widget/maverick-widget.js`:1-2 | Shipping code for an unreleased 2028-H1 roadmap feature in a production path | Drop the speculative roadmap framing from the docstring (or move it behind a feature flag / unbundled directory) so the file's stated maturity matches | 0.55 |

### Hardcoded value (should be config) (6)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `packages/maverick-core/maverick/cost/router.py`:37-74 | OpenRouter tier rates flow from unverified 'placeholder' prices in llm.MODEL_PRICES into both routing selection and billing | Either verify and pin the three OpenRouter rates (removing the TODO in llm.py) or mark these arms experimental and exclude them from cost scoring unti | 0.55 |
| `packages/maverick-core/maverick/skill/embeddings.py`:22-23, 73 | Embedding model id hardcoded with no config knob or override | Read the model name from config (e.g. get_skill_embeddings()['model'] with this value as the default), so the embedding model is operator-configurable | 0.55 |
| `packages/maverick-core/maverick/tax_prep.py`:78-99 | Tax constants hardcoded in a production module with self-admitted 'verify each year' caveats | Source the federal/state constant tables through the same signed maverick.tax_constants channel used for graduated brackets (with the in-code tables a | 0.5 |
| `packages/maverick-core/maverick/tools/voice.py`:90, 112, 196, 229 | Hosted STT/TTS model ids are hardcoded with no operator config knob (inconsistent with local backend) | Add env knobs mirroring the local case: MAVERICK_WHISPER_OPENAI_MODEL, MAVERICK_WHISPER_GROQ_MODEL, MAVERICK_TTS_OPENAI_MODEL, MAVERICK_TTS_ELEVENLABS | 0.6 |
| `packages/maverick-core/maverick/verifier.py`:241-255 | Hardcoded cross-family model ids in ensemble panel constants | Move the default ensemble panel and per-provider default model map into config (e.g. a [routing] ensemble_panel / per-provider defaults table, falling | 0.5 |
| `packages/maverick-core/maverick/world_model_backends/postgres.py`:3086-3097 | Cross-replica rate-limit prune window is a hardcoded 120.0 magic number coupled to a 60s reader window | Define the rate-limit window once (config or a shared constant) and derive both the reader cutoff and the prune horizon from it (e.g. prune at 2 * RAT | 0.6 |

### Dead code (4)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `benchmarks/swe_bench.py`:60-61 | verifier_confidence and disagreement_entropy CSV columns are declared but never populated -- always 0.0 | Either wire these from the orchestrator's verifier/best-of-N disagreement signals (which exist elsewhere in the kernel) into _maverick_build_row, or d | 0.7 |
| `packages/maverick-core/maverick/cache/learning.py`:30-34 | Cross-run learning cache is fully implemented but never imported by any caller | Wire shared()/get()/put() into the verifier or orchestrator behind enabled(), with at least one end-to-end test proving a verified sub-result is reuse | 0.7 |
| `packages/maverick-core/maverick/compaction/hybrid.py`:92-124, 113-123 | age_span feature is dead in production: agent messages carry no 'ts', so it always buckets to 0 | Either stamp messages with a timestamp where compaction features are extracted, or drop age_span from FEATURE_NAMES/buckets until a real time signal i | 0.6 |
| `packages/maverick-core/maverick/grpc_api/server.py`:309-311 | Unreachable `raise` after `context.abort()` in RunGoal exception handler | Drop the trailing `raise` to match the StartGoal handler, or if the intent is to satisfy a linter that the function never falls through, leave a comme | 0.7 |

### Duplication (3)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `apps/installer-cli/maverick_installer/models.py`:128-139 | Hardcoded per-role model ids duplicated from kernel ROLE_MODELS, already drifting (missing 'vision' role) | Derive the wizard's defaults from maverick.llm.ROLE_MODELS (import it, fall back to a local copy only if maverick-core is unimportable) so there is a  | 0.6 |
| `packages/maverick-dashboard/maverick_dashboard/api.py`:3008-3013 | At-rest field-sealing logic duplicated from the world model into the dashboard write path | Encapsulate the title update in a public WorldModel method that performs truncation, sealing, and the timestamp internally for each backend, and stop  | 0.7 |
| `packages/maverick-shield/maverick_shield/deobfuscate.py`:60-73 | Homoglyph-folding table maintained in two places with divergent coverage | Define one canonical homoglyph map (and the invisible/tag regexes) in a shared module and import it into both builtin_rules and deobfuscate so confusa | 0.7 |

### Fake / hollow feature (2)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `packages/maverick-core/maverick/sandbox/firecracker.py`:189-242 | Firecracker microVM 'isolation' runs commands against an empty rootfs — the agent's workspace is never copied into the VM | Either (a) implement the workspace transfer (vsock/virtio-fs mount or pre-exec `firectl cp`/drive injection of self.workdir) before claiming microVM e | 0.86 |
| `packages/maverick-core/maverick/tools/dp_stats.py`:16-39, 42-49, 86-88 | Differential-privacy noise is seedable and uses a non-crypto PRNG, defeating the privacy guarantee | Draw noise from a cryptographically secure source (secrets.SystemRandom / os.urandom) and remove the production `seed` parameter (or gate it behind an | 0.82 |

### Other (2)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `rust/mvk-scan/src/lib.rs`:182-194 | Test defines an impl block after the test that uses it (legal but unidiomatic) | Inline the one-line check or move the helper above the test; purely cosmetic. | 0.5 |
| `rust/mvk-scan/src/secret.rs`:30-100 | openai_api_key pattern lacks trailing anchor (faithful to Python, but an over-broad/over-redacting span by design) | No change needed; if anything, add a one-line Rust comment mirroring secret_detector.py's explanation so the asymmetry is self-documenting at the Rust | 0.55 |

### Theater (scaffolding, no impl) (1)

| File:lines | Issue | Fix | Conf |
|---|---|---|---|
| `benchmarks/test_wave12_patch_pipeline.py`:117-124 | Toothless assertion accepts both sanitizer outcomes, so it can never fail | Assert the exact expected output: `assert out == "'" + diff` (drop the `or out == diff` escape hatch), since the leading-dash case deterministically g | 0.75 |

---

## Appendix C — Findings by file

200 files have at least one active finding.

| File | H | M | L | Top issue |
|---|--:|--:|--:|---|
| `packages/maverick-core/maverick/compaction/hybrid.py` | 1 | 1 | 2 | "Compaction v6 hybrid" learned strategy picker is dead code — never wired into any production path, yet docs s |
| `packages/maverick-core/maverick/world_model_backends/postgres.py` | 1 | 1 | 2 | Memory Guard trust-tiering (OWASP ASI06) is silently defeated on the Postgres backend |
| `packages/maverick-dashboard/maverick_dashboard/api.py` | 1 | 1 | 2 | retitle_goal / reparent_goal reach into SQLite-only WorldModel internals and 500 under the Postgres backend |
| `go/model-proxy/handle.go` | 1 | 1 | 0 | Go port returns raw error strings to client, dropping the Python original's mandatory secret-scrubbing |
| `packages/maverick-core/maverick/vector_store/weaviate_store.py` | 1 | 1 | 0 | Weaviate adapter claims server-side vectorization but creates a vectorizer-less collection (near_text cannot w |
| `packages/maverick-core/maverick/donation.py` | 1 | 0 | 0 | Trajectory donation claims a PII-redaction step that does not exist; only secret-shaped strings are scrubbed |
| `packages/maverick-core/maverick/grpc_dispatcher.py` | 1 | 0 | 0 | gRPC dispatcher sends bearer token over a hardcoded insecure (plaintext) channel, ignoring the project's own c |
| `packages/maverick-core/maverick/worker_review.py` | 1 | 0 | 0 | Unconditional, hardcoded governance/compliance claim surfaced to buyers regardless of actual shield/audit stat |
| `packages/maverick-core/maverick/sandbox/firecracker.py` | 0 | 1 | 3 | Production sandbox backend ships with self-labeled 'SCAFFOLD' / 'For now' incompleteness markers |
| `apps/desktop/src-tauri/src/lib.rs` | 0 | 1 | 2 | DASHBOARD_PORT constant is bypassed by a hardcoded "8765" string in spawn_dashboard, breaking the documented r |
| `apps/installer-cli/maverick_installer/wizard.py` | 0 | 2 | 1 | Anthropic key 'validation' returns ok=True on nearly every failure, including import failure and any non-auth  |
| `packages/maverick-core/maverick/cli/__init__.py` | 0 | 1 | 2 | `cost --model` filter is non-functional; matches a `model=X` outcome format the system never writes |
| `packages/maverick-core/maverick/coding_mode.py` | 0 | 0 | 3 | defensive_validate docstring claims a 20% cheating-overlap threshold but the code enforces 50%/35% |
| `packages/maverick-core/maverick/marketplace/moderation.py` | 0 | 2 | 1 | Documented CLI entry point points at a module that does not exist |
| `packages/maverick-core/maverick/training/ingest.py` | 0 | 2 | 1 | Broad except Exception silently returns [] for world-model lookups, masking real DB failures |
| `packages/maverick-core/maverick/world_model.py` | 0 | 0 | 3 | At-rest decrypt passes unsealed values through by default instead of failing closed |
| `apps/installer-cli/maverick_installer/bridge.py` | 0 | 1 | 1 | Tauri sidecar claims to mirror CLI consumer mode 'exactly' but silently drops API-key validation |
| `apps/installer-desktop/src-tauri/src/lib.rs` | 0 | 0 | 2 | Log-streaming reader loops silently truncate output on the first I/O error |
| `apps/installer-msi/test_wxs.py` | 0 | 1 | 1 | Launcher regression guard regex is malformed and never matches the form it forbids |
| `apps/mobile-skills/test_mobile_skills.py` | 0 | 1 | 1 | Checksum test asserts the TODO placeholder exists, so it breaks when the real checksum is filled in |
| `benchmarks/_common/contamination_guard.py` | 0 | 0 | 2 | Hash-vs-raw-brief detection is a fragile len==16-and-hex heuristic that silently misclassifies short hex brief |
| `benchmarks/swe_bench.py` | 0 | 0 | 2 | verifier_confidence and disagreement_entropy CSV columns are declared but never populated -- always 0.0 |
| `deploy/relay/relay.py` | 0 | 0 | 2 | Malformed Content-Length header raises an uncaught ValueError, crashing the request thread instead of returnin |
| `extensions/widget/maverick-widget.js` | 0 | 0 | 2 | Full-control bearer token read from a client-side script attribute and sent to data-endpoint |
| `packages/maverick-core/maverick/agent.py` | 0 | 0 | 2 | _build_system swallows ALL exceptions silently (no log) on five prompt-augmentation paths |
| `packages/maverick-core/maverick/cost/router.py` | 0 | 0 | 2 | role_policy() catches bare Exception when reading routing config, hiding malformed config |
| `packages/maverick-core/maverick/finance/status.py` | 0 | 2 | 0 | Audit-signing probe swallows all exceptions and reports control as merely "off" |
| `packages/maverick-core/maverick/github_app.py` | 0 | 0 | 2 | PR creation via gh silently returns None on failure, losing the agent's pushed work |
| `packages/maverick-core/maverick/glance.py` | 0 | 1 | 1 | Silent broad except in spend path reports $0.00 on any ledger error |
| `packages/maverick-core/maverick/grpc_api/server.py` | 0 | 1 | 1 | Trust-plane gate fails OPEN on any exception from load_trust_state() |
| `packages/maverick-core/maverick/notifications.py` | 0 | 0 | 2 | notify() silently swallows backend send results in the async path; returns optimistic count |
| `packages/maverick-core/maverick/prm.py` | 0 | 0 | 2 | RemotePRM silently swallows all network/HTTP/JSON errors with zero logging, masking a down or misconfigured sc |
| `packages/maverick-core/maverick/providers/openai_provider.py` | 0 | 1 | 1 | Module docstring claims tool_call_id stubbing fix that the code explicitly does NOT implement |
| `packages/maverick-core/maverick/replay/video.py` | 0 | 0 | 2 | ffconcat manifest breaks if frame directory path contains a single quote |
| `packages/maverick-core/maverick/retry/classifier.py` | 0 | 1 | 1 | Error classification relies on substring/regex matching against English exception text |
| `packages/maverick-core/maverick/routing.py` | 0 | 1 | 1 | Broad except: pass silently discards a user's explicitly-configured per-role model, contradicting the 'users o |
| `packages/maverick-core/maverick/safety/voice_safety.py` | 0 | 1 | 1 | Documented inbound transcript-injection screen has zero production callers (dead safety control) |
| `packages/maverick-core/maverick/skill/embeddings.py` | 0 | 1 | 1 | Embedding cache save is non-atomic and unlocked, the exact race the sibling stats module documents and fixes |
| `packages/maverick-core/maverick/tools/calendar_tool.py` | 0 | 1 | 1 | find_slot silently drops any event it can't parse, so a busy block becomes free time |
| `packages/maverick-core/maverick/tools/office_convert.py` | 0 | 1 | 1 | office_convert reports 'wrote {dst}' on a predicted path it never verifies exists |
| `packages/maverick-core/maverick/tools/voice.py` | 0 | 0 | 2 | Hosted STT/TTS model ids are hardcoded with no operator config knob (inconsistent with local backend) |
| `packages/maverick-core/maverick/vector_store/pgvector_store.py` | 0 | 0 | 2 | _ensure_vector_column builds DDL with Python %-formatting instead of psycopg parameters |
| `packages/maverick-core/maverick/vector_store/qdrant_store.py` | 0 | 2 | 0 | Qdrant _stored_id docstring claims read isolation but query() applies no tenant filter |
| `packages/maverick-core/maverick/verifier.py` | 0 | 1 | 1 | Ensemble verifier docstring claims 'minimum confidence' but code computes the mean |
| `packages/maverick-evolve/maverick_evolve/agent_adapter.py` | 0 | 1 | 1 | subprocess_run_one docstring claims a 'DONE.\n\n<summary>' answer but returns raw stdout |
| `packages/maverick-shield/maverick_shield/deobfuscate.py` | 0 | 1 | 1 | Phase-aligned base64 de-obfuscation logic duplicated across two security modules |
| `scripts/stress/mp_jobqueue_stress.py` | 0 | 0 | 2 | Worker process discards its claimed-id record on any mid-run exception, masking the real error as "lost jobs" |
| `web/widget/maverick-widget.js` | 0 | 0 | 2 | Shipping code for an unreleased 2028-H1 roadmap feature in a production path |
| `apps/installer-cli/maverick_installer/models.py` | 0 | 0 | 1 | Hardcoded per-role model ids duplicated from kernel ROLE_MODELS, already drifting (missing 'vision' role) |
| `apps/mobile-companion/App.tsx` | 0 | 0 | 1 | Settings load has no error handling; a rejected SecureStore call hangs the app on the loading screen |
| `apps/mobile-companion/src/api.ts` | 0 | 0 | 1 | Comment claims it 'mirrors' the VS Code extension, but behavior diverges |
| `apps/mobile-companion/src/poll.ts` | 0 | 0 | 1 | Polling has no overlap guard or per-tick timeout; slow/stalled fetches can stack |
| `apps/mobile-companion/src/screens/SettingsScreen.tsx` | 0 | 0 | 1 | save() has no error handling; keychain write failure is silently unhandled and onSaved fires regardless of fee |
| `apps/mobile-skills/kivy-shell/main.py` | 0 | 0 | 1 | load_skill assumes importlib spec/loader are non-None |
| `apps/visionos-plan-tree/MaverickPlanTree/PlanTreeModel.swift` | 0 | 0 | 1 | Bearer token sent without enforcing HTTPS on the configurable dashboard URL |
| `apps/vscode-extension/src/extension.ts` | 0 | 0 | 1 | Live-watch silently dies on recoverable HTTP error responses (no reconnect, body unconsumed) |
| `apps/zed-extension/src/lib.rs` | 0 | 0 | 1 | Comment references stale CLI path maverick/cli.py (now a package, cli/__init__.py) |
| `benchmarks/_common/cost_tracker.py` | 0 | 1 | 0 | pareto_frontier() does no Pareto filtering — returns every pipeline including dominated ones |
| `benchmarks/_common/manifests.py` | 0 | 1 | 0 | "The manifest is the contract" registry is consumed only by its own test, never enforced by the harness |
| `benchmarks/agent_solver.py` | 0 | 1 | 0 | Benchmark answer-extraction fallback swallows all exceptions and silently scores 0 |
| `benchmarks/container_terminal_solver.py` | 0 | 1 | 0 | LLM call exception is silently swallowed with a bare return, abandoning the task with no diagnostic |
| `benchmarks/fetch_swe_bench_verified.py` | 0 | 1 | 0 | Failed-checkout leaves a half-staged repo that later falsely reports "already staged" |
| `benchmarks/harness.py` | 0 | 0 | 1 | run_one unconditionally stamps source='measured' even though the comment insists comparator rows must be sourc |
| `benchmarks/moat_rigorous.py` | 0 | 0 | 1 | Worker builds a config.toml via unescaped %-interpolation of model name and codebase path |
| `benchmarks/preflight.py` | 0 | 1 | 0 | Hardcoded model IDs in preflight pings and BoN-ladder default violate the repo's no-hardcoded-models rule |
| `benchmarks/recall_precision.py` | 0 | 0 | 1 | Benchmark couples to a private underscore-prefixed kernel internal |
| `benchmarks/run_eval.py` | 0 | 0 | 1 | Dynamic module loader has no error handling on spec/exec failures |
| `benchmarks/security/detector_score.py` | 0 | 1 | 0 | Heuristics import failure silently degrades the headline `defense_in_depth` backend to never-fire, reported as |
| `benchmarks/security/end_to_end_asr.py` | 0 | 1 | 0 | Bare `except Exception: return False` silently swallows every scanner crash in a benchmark that feeds the ship |
| `benchmarks/security/latency_bench.py` | 0 | 0 | 1 | Percentile helper fabricates p50/p95/p99 from a single sample when n<=1 |
| `benchmarks/tau2_solver.py` | 0 | 1 | 0 | LLM/network errors are swallowed and surface as the agent "producing nothing", conflating infra failures with  |
| `benchmarks/test_cost_accumulation.py` | 0 | 0 | 1 | Test name claims an invariant the test explicitly does not enforce |
| `benchmarks/test_wave12_operational.py` | 0 | 0 | 1 | Misleading dead PATH assignment (a file, not a directory) immediately overwritten |
| `benchmarks/test_wave12_patch_pipeline.py` | 0 | 0 | 1 | Toothless assertion accepts both sanitizer outcomes, so it can never fail |
| `extensions/browser/popup.js` | 0 | 0 | 1 | Popup messages content script via chrome.tabs.sendMessage without tabs/activeTab permission |
| `go/model-proxy/cmd/model-proxy/main.go` | 0 | 0 | 1 | Empty provider key downgraded to a warning, so the proxy starts and fails-open on its core key-custody guarant |
| `go/model-proxy/server.go` | 0 | 0 | 1 | Request body read errors are silently swallowed and forwarded as empty |
| `packages/maverick-channels/maverick_channels/__init__.py` | 0 | 0 | 1 | Module docstring claims "18 wired adapters" but enumerates only 17 |
| `packages/maverick-channels/maverick_channels/bluesky.py` | 0 | 0 | 1 | Proactive send() swallows HTTP failures while the sibling reply path checks status |
| `packages/maverick-channels/maverick_channels/mastodon.py` | 0 | 0 | 1 | send() drops the HTTP response, silently losing failed direct messages |
| `packages/maverick-channels/maverick_channels/rich_render.py` | 0 | 0 | 1 | Generated HTML artifacts load KaTeX/Mermaid from a CDN with no Subresource Integrity pinning |
| `packages/maverick-channels/maverick_channels/voice.py` | 0 | 0 | 1 | Retell/Bland outbound contracts shipped untested, presented inline with the live Vapi path |
| `packages/maverick-core/maverick/a2a_tasks.py` | 0 | 1 | 0 | A2A streaming path leaks raw exception text (no scrub) into caller artifact and push webhook, unlike send() |
| `packages/maverick-core/maverick/adaptive_compute.py` | 0 | 0 | 1 | Docstring cites an apparently fabricated arXiv paper as SOTA grounding |
| `packages/maverick-core/maverick/ai_act_package.py` | 0 | 0 | 1 | Compliance-doc generator swallows every exception via blanket _safe wrapper |
| `packages/maverick-core/maverick/audit/forwarder.py` | 0 | 1 | 0 | SIEM forwarder ships audit data and a bearer token over plaintext http:// / tcp:// |
| `packages/maverick-core/maverick/audit/worm.py` | 0 | 0 | 1 | S3 WORM verify() swallows every exception as a silent verification result |
| `packages/maverick-core/maverick/automation_import/__init__.py` | 0 | 0 | 1 | Feature-flag check swallows every config exception and silently disables import |
| `packages/maverick-core/maverick/automation_import/make.py` | 0 | 1 | 0 | Make fetch silently imports only the first 100 scenarios (no pagination) |
| `packages/maverick-core/maverick/automation_import/n8n.py` | 0 | 0 | 1 | n8n fetch silently stops at 100 pages with no signal on truncation |
| `packages/maverick-core/maverick/benchmarks/reproducible_v2.py` | 0 | 0 | 1 | Seed-kwarg fallback masks a solver's own internal TypeError and silently re-invokes it |
| `packages/maverick-core/maverick/cache/__init__.py` | 0 | 0 | 1 | cache.stats()/purge() omit the llm, learning, and tool caches it claims to centralize |
| `packages/maverick-core/maverick/cache/learning.py` | 0 | 0 | 1 | Cross-run learning cache is fully implemented but never imported by any caller |
| `packages/maverick-core/maverick/cache/llm.py` | 0 | 1 | 0 | Module docstring documents a cached_complete() integration API that does not exist |
| `packages/maverick-core/maverick/cache/redis_tool.py` | 0 | 1 | 0 | Distributed cross-host tool cache backend is never wired into the tool cache |
| `packages/maverick-core/maverick/compaction/multimodal.py` | 0 | 0 | 1 | JPEG dimension sniffer can misread non-SOF markers; saved only by a broad except |
| `packages/maverick-core/maverick/compaction/streaming.py` | 0 | 1 | 0 | folder() coroutine stores a fingerprint of only locally-folded turns, breaking the cursor/prefix invariant on  |
| `packages/maverick-core/maverick/compliance.py` | 0 | 0 | 1 | Audit-logging control hardcoded to 'active' without probing that logging actually works |
| `packages/maverick-core/maverick/cost/by_tag.py` | 0 | 0 | 1 | _goal_tag() swallows all exceptions from world.get_goal(), masking real DB errors as untagged spend |
| `packages/maverick-core/maverick/credit.py` | 0 | 0 | 1 | normalize_credit equal-split fallback masks all-harmful swarm as uniform contribution |
| `packages/maverick-core/maverick/domain_eval.py` | 0 | 0 | 1 | Citation-rubric markers so broad the legal_research golden case passes on almost any markdown output |
| `packages/maverick-core/maverick/dreaming.py` | 0 | 0 | 1 | Rehearsal success graded by English/emoji prefix string-matching |
| `packages/maverick-core/maverick/experience.py` | 0 | 0 | 1 | Fabricated/future arXiv citation used to lend authority in a shipping module docstring |
| `packages/maverick-core/maverick/grpc_plugin_host.py` | 0 | 0 | 1 | Shield scan of plugin tool manifests fails OPEN on any shield error |
| `packages/maverick-core/maverick/health.py` | 0 | 0 | 1 | doctor's live Anthropic/OpenAI key probe sets no client timeout and can hang `maverick doctor` for minutes |
| `packages/maverick-core/maverick/killswitch.py` | 0 | 0 | 1 | Cluster-wide shared-halt check fails OPEN on any error while caching the previous result, so a persistent shar |
| `packages/maverick-core/maverick/learning_rollout.py` | 0 | 0 | 1 | "Live" governed rollout records an audit row instead of deploying; only rollback is real |
| `packages/maverick-core/maverick/llm.py` | 0 | 1 | 0 | OpenRouter billing rates are self-admitted unverified placeholders in the live pricing table |
| `packages/maverick-core/maverick/marketplace/stats.py` | 0 | 0 | 1 | Stats docstring lists a rating kind ("channels") the ledger never supports |
| `packages/maverick-core/maverick/mcp_client.py` | 0 | 0 | 1 | HTTP MCP client ignores Mcp-Session-Id on the initialize response |
| `packages/maverick-core/maverick/mcp_oauth.py` | 0 | 1 | 0 | OAuth token fetch/refresh runs the blocking HTTP call while holding the provider lock |
| `packages/maverick-core/maverick/mcp_registry.py` | 0 | 0 | 1 | Registry install writes MCP auth tokens/headers to config.toml without setting 0600 perms |
| `packages/maverick-core/maverick/migrate.py` | 0 | 0 | 1 | Hand-rolled TOML writer used by the only mutating path does not escape/round-trip all value types |
| `packages/maverick-core/maverick/notification_batcher.py` | 0 | 0 | 1 | Daemon flusher thread leaks on reset_shared() and never stops |
| `packages/maverick-core/maverick/persona.py` | 0 | 0 | 1 | Config load wrapped in bare except returning empty persona |
| `packages/maverick-core/maverick/plugin_isolation.py` | 0 | 1 | 0 | Advertised timeout_s is silently ignored in the subinterpreter isolation backend |
| `packages/maverick-core/maverick/proof_guarantees.py` | 0 | 1 | 0 | Crypto-gated diligence guarantees are recorded passed=True when cryptography is absent ("verified in CI") |
| `packages/maverick-core/maverick/provider_cost_cap.py` | 0 | 0 | 1 | Per-period alert-dedup set `_alerted` is process-local module state, never pruned |
| `packages/maverick-core/maverick/providers/azure_openai_provider.py` | 0 | 1 | 0 | Azure OpenAI substitutes a fake key 'azure-no-auth' when AZURE_OPENAI_API_KEY is missing |
| `packages/maverick-core/maverick/providers/bedrock_provider.py` | 0 | 1 | 0 | Bedrock substitutes a fake bearer 'bedrock-no-auth' when the API key is missing |
| `packages/maverick-core/maverick/provision.py` | 0 | 0 | 1 | Tool synthesis passes the capability phrase (g.need) instead of a declared tool-name field (latent fragility) |
| `packages/maverick-core/maverick/reflexion.py` | 0 | 0 | 1 | recall() never loads model_id despite per-model harness contract |
| `packages/maverick-core/maverick/reliability_cert.py` | 0 | 1 | 0 | Reliability-cert docstring claims a 'query plans / EXPLAIN index' check that is not implemented or registered |
| `packages/maverick-core/maverick/replay/trace.py` | 0 | 0 | 1 | replay() gives no per-handler error isolation — one failing handler aborts the whole replay |
| `packages/maverick-core/maverick/retry/__init__.py` | 0 | 0 | 1 | Backoff docstring states fixed 1s/2s/4s/8s delays but actual delays are jittered and env-tunable |
| `packages/maverick-core/maverick/reviewer.py` | 0 | 0 | 1 | Reviewer trusts the model's self-reported approves flag instead of enforcing the stated approval rule |
| `packages/maverick-core/maverick/runner.py` | 0 | 0 | 1 | inflight_goals() reads a private CPython semaphore attribute (_value) used by /healthz and /metrics gauges |
| `packages/maverick-core/maverick/safety/secret_detector.py` | 0 | 0 | 1 | Docstring advertises "generic high-entropy secret" detection that does not exist |
| `packages/maverick-core/maverick/safety/tool_acl.py` | 0 | 0 | 1 | Stale comment claims it is "adding" a public remove() that was never added |
| `packages/maverick-core/maverick/sandbox/modal_backend.py` | 0 | 0 | 1 | Modal exec reads sb.stdout/stderr/returncode with no guard that the sandbox actually produced them |
| `packages/maverick-core/maverick/sandbox/network_policy.py` | 0 | 1 | 0 | Docstring claims packet-level egress enforcement that does not exist anywhere in the codebase |
| `packages/maverick-core/maverick/self_learning.py` | 0 | 1 | 0 | Approved generated tool's fn runs in-process at runtime despite 'sandbox'/out-of-host framing |
| `packages/maverick-core/maverick/shield_ensemble.py` | 0 | 0 | 1 | Ensemble docstring claims an injection+jailbreak+exfil+policy lineup but ships injection/exfil/pii with no pol |
| `packages/maverick-core/maverick/speculative_exec.py` | 0 | 0 | 1 | Verify-and-rollback half not shipped; accepted() is a dead seam with no consumer |
| `packages/maverick-core/maverick/task_graph.py` | 0 | 0 | 1 | Loop variable `path` reused for two unrelated meanings in `_run` |
| `packages/maverick-core/maverick/tax_prep.py` | 0 | 0 | 1 | Tax constants hardcoded in a production module with self-admitted 'verify each year' caveats |
| `packages/maverick-core/maverick/tenant/concurrency.py` | 0 | 0 | 1 | release() docstring claims 'Idempotent-safe' but a spurious extra call drops a live slot |
| `packages/maverick-core/maverick/tenant/kms.py` | 0 | 0 | 1 | rotate_kek_idempotent swallows all exceptions in the 'already rotated?' probe |
| `packages/maverick-core/maverick/tenant/registry.py` | 0 | 0 | 1 | tenant_spend_today reaches into UsageLedger._load() private API |
| `packages/maverick-core/maverick/tools/android.py` | 0 | 0 | 1 | input_text only escapes spaces, not other adb-special characters |
| `packages/maverick-core/maverick/tools/arxiv.py` | 0 | 0 | 1 | Atom/XML response parsed with regex, with a self-admitted brittleness comment |
| `packages/maverick-core/maverick/tools/ask_user.py` | 0 | 0 | 1 | ask_user dereferences args['question'] directly, raising KeyError if the model omits it |
| `packages/maverick-core/maverick/tools/ast_edit.py` | 0 | 1 | 0 | "AST-aware editor" rename_symbol is a raw regex text substitution, not AST-aware |
| `packages/maverick-core/maverick/tools/capability_leak_fuzzer.py` | 0 | 0 | 1 | 'capability_leak_fuzzer' performs no fuzzing |
| `packages/maverick-core/maverick/tools/capability_revocation.py` | 0 | 1 | 0 | Revocation BFS revokes principals who still hold the capability via an independent un-revoked path |
| `packages/maverick-core/maverick/tools/consent_ergonomics.py` | 0 | 1 | 0 | Consent risk badge uses naive substring matching and mislabels benign scopes as HIGH |
| `packages/maverick-core/maverick/tools/containment_mode.py` | 0 | 1 | 0 | "Containment" policy tool fails open: unknown (possibly dangerous) actions default to ALLOW |
| `packages/maverick-core/maverick/tools/database_tool.py` | 0 | 1 | 0 | SQLAlchemy Engine created per call and never disposed — connection/pool leak |
| `packages/maverick-core/maverick/tools/decision_explainer.py` | 0 | 1 | 0 | Docstring claims a 'smallest change that would flip it' recourse computation that is never implemented |
| `packages/maverick-core/maverick/tools/differential_privacy.py` | 0 | 1 | 0 | Differential-privacy mechanism uses a non-cryptographic PRNG and float inverse-CDF Laplace (predictable, leaky |
| `packages/maverick-core/maverick/tools/dp_stats.py` | 0 | 0 | 1 | Differential-privacy noise is seedable and uses a non-crypto PRNG, defeating the privacy guarantee |
| `packages/maverick-core/maverick/tools/email_tool.py` | 0 | 0 | 1 | Bare best-effort except Exception: pass around MIME body decode |
| `packages/maverick-core/maverick/tools/gdrive_tool.py` | 0 | 1 | 0 | Google Drive multipart upload uses a hardcoded boundary with unescaped user content |
| `packages/maverick-core/maverick/tools/geofence.py` | 0 | 1 | 0 | Geofence docstring says empty allow-list means 'any region not denied' but the code defaults to DENY |
| `packages/maverick-core/maverick/tools/gitlab.py` | 0 | 0 | 1 | GitLab connector bypasses the SSRF-safe client used by sibling fetch tools |
| `packages/maverick-core/maverick/tools/hackernews.py` | 0 | 0 | 1 | hackernews HTTP client bypasses the repo's SSRF-safe wrapper used elsewhere |
| `packages/maverick-core/maverick/tools/home_assistant_tool.py` | 0 | 1 | 0 | history op advertises an `hours` time-window parameter that is silently ignored |
| `packages/maverick-core/maverick/tools/honeytoken.py` | 0 | 0 | 1 | Honeytoken exfiltration scanner only detects tokens delimited by whitespace |
| `packages/maverick-core/maverick/tools/knowledge.py` | 0 | 0 | 1 | knowledge_search swallows KB error detail, returning only the exception class name |
| `packages/maverick-core/maverick/tools/knowledge_graph.py` | 0 | 0 | 1 | knowledge_graph 'dot' op emits invalid Graphviz (Python repr, single-quoted IDs) |
| `packages/maverick-core/maverick/tools/lambda_tool.py` | 0 | 0 | 1 | list_functions format spec crashes on a None field instead of degrading |
| `packages/maverick-core/maverick/tools/latency_heatmap.py` | 0 | 0 | 1 | Heatmap shading collapses to all-max (█) whenever every cell value is equal, and legend advertises a low band  |
| `packages/maverick-core/maverick/tools/latex_tool.py` | 0 | 0 | 1 | PDF render leaks its temp working directory (and the LaTeX source/PDF) on every call |
| `packages/maverick-core/maverick/tools/marketplace_ratings.py` | 0 | 1 | 0 | "verify_install" claims to verify a downloaded artifact but only compares two caller-supplied hashes |
| `packages/maverick-core/maverick/tools/memleak_quarantine.py` | 0 | 0 | 1 | "Memory-leak quarantine" only flags components as QUARANTINE — it never quarantines anything |
| `packages/maverick-core/maverick/tools/memory.py` | 0 | 0 | 1 | memory insert: schema says '1-based line to insert AFTER' but code inserts BEFORE a 0-based index |
| `packages/maverick-core/maverick/tools/mutation_test.py` | 0 | 0 | 1 | Mutation-test docstring claims a "rewritten line" but the output emits the original, unmutated line |
| `packages/maverick-core/maverick/tools/oauth_helper.py` | 0 | 0 | 1 | chmod 0600 on the plaintext OAuth token out-file is best-effort and silently swallowed |
| `packages/maverick-core/maverick/tools/oidc_tool.py` | 0 | 1 | 0 | OIDC tool reports an identity (subject/email) from an id_token whose signature it never verifies |
| `packages/maverick-core/maverick/tools/pandas_query.py` | 0 | 0 | 1 | Path confinement silently disabled when sandbox is None |
| `packages/maverick-core/maverick/tools/recall.py` | 0 | 0 | 1 | Broad except in embedding path swallows all errors and silently downgrades to weaker scorer |
| `packages/maverick-core/maverick/tools/risk_tier_classifier.py` | 0 | 0 | 1 | Risk-tier classifier lets a caller-supplied custom_weight silently downgrade a HIGH action |
| `packages/maverick-core/maverick/tools/s3_attachments.py` | 0 | 0 | 1 | "Content-addressed" key is actually filename-addressed (sha256 of the name, not the bytes) |
| `packages/maverick-core/maverick/tools/semantic_code_search.py` | 0 | 0 | 1 | "semantic_code_search" / "search by intent" is a literal keyword-overlap matcher, not semantic search |
| `packages/maverick-core/maverick/tools/shell.py` | 0 | 0 | 1 | Benchmark anti-cheat git/secret blocklist is self-admittedly bypassable and the real fix is left unimplemented |
| `packages/maverick-core/maverick/tools/shopify_tool.py` | 0 | 0 | 1 | Shopify connector uses raw httpx.Client without the SSRF-safe transport |
| `packages/maverick-core/maverick/tools/sla_breach.py` | 0 | 0 | 1 | "SLA-breach automation" with action=failover never executes any action — it only returns a recommendation stri |
| `packages/maverick-core/maverick/tools/slack_bot.py` | 0 | 0 | 1 | Upload comment says 'PUT the bytes' but code POSTs |
| `packages/maverick-core/maverick/tools/snowflake_tool.py` | 0 | 1 | 0 | Snowflake client always sends KEYPAIR_JWT token-type header, breaking the OAuth path its docstring promises |
| `packages/maverick-core/maverick/tools/spend_report.py` | 0 | 0 | 1 | Cost accessor silently returns $0.00 on any error in a financial-analytics tool |
| `packages/maverick-core/maverick/tools/sql_query.py` | 0 | 0 | 1 | Docstring guarantees workspace path confinement that is bypassed when no sandbox is bound |
| `packages/maverick-core/maverick/tools/supply_chain_pin.py` | 0 | 1 | 0 | Pin auditor flags the standard pip exact-pin '==1.0.0' as a version range |
| `packages/maverick-core/maverick/tools/youtube.py` | 0 | 0 | 1 | Uses youtube_transcript_api.get_transcript static API removed in the library's 1.x line |
| `packages/maverick-core/maverick/trace_pin.py` | 0 | 0 | 1 | trace_commit silently swallows all exceptions with no log |
| `packages/maverick-core/maverick/training/__init__.py` | 0 | 1 | 0 | Stale status docstring calls RLAIF a "placeholder" when it is a full 822-line implementation |
| `packages/maverick-core/maverick/tree_of_thought.py` | 0 | 0 | 1 | Critic JSON-parse failure silently falls back to a length heuristic to pick the winning plan |
| `packages/maverick-core/maverick/ux_retrospective.py` | 0 | 0 | 1 | Three broad except Exception blocks in collect() silently zero out UX sections |
| `packages/maverick-dashboard/maverick_dashboard/control_plane.py` | 0 | 0 | 1 | Trust-overview view fails OPEN to active='active' when an agent's lifecycle check raises |
| `packages/maverick-dashboard/maverick_dashboard/deliverables.py` | 0 | 0 | 1 | Persona-inbox 'awaiting sign-off' is a proxy heuristic; real approval linkage not implemented |
| `packages/maverick-dashboard/maverick_dashboard/oidc_login.py` | 0 | 1 | 0 | OIDC authorization-code flow sends no `nonce` and never verifies one on the ID token |
| `packages/maverick-dashboard/maverick_dashboard/saml.py` | 0 | 1 | 0 | SAML browser-SSO auth path ships disclosed as untested against any live IdP |
| `packages/maverick-dashboard/maverick_dashboard/static/maverick-analytics.js` | 0 | 0 | 1 | Numeric goal counts interpolated into SVG aria-label/text without esc() (defense-in-depth, not exploitable) |
| `packages/maverick-evolve/maverick_evolve/eval_harness.py` | 0 | 0 | 1 | Default fitness 'scorer' is case-insensitive substring containment over whole output |
| `packages/maverick-mcp/maverick_mcp/server.py` | 0 | 0 | 1 | Enterprise license preflight enforced on maverick_start but omitted on maverick_resume |
| `packages/maverick-shield/maverick_shield/cascade.py` | 0 | 0 | 1 | Module docstring frames a regex/heuristic cheap-probe with Constitutional-Classifiers-v2 efficacy numbers it d |
| `rust/maverick-verify-audit/src/lib.rs` | 0 | 0 | 1 | Rust verifier trusts any lone <key_id>.pub, dropping the Python source's forged-pubkey defense |
| `rust/mvk-scan-wasm/src/lib.rs` | 0 | 0 | 1 | Length-mismatch error message uses unchecked multiplication while the guard uses saturating_mul |
| `rust/mvk-scan/src/lib.rs` | 0 | 0 | 1 | Test defines an impl block after the test that uses it (legal but unidiomatic) |
| `rust/mvk-scan/src/secret.rs` | 0 | 0 | 1 | openai_api_key pattern lacks trailing anchor (faithful to Python, but an over-broad/over-redacting span by des |
| `sdks/plugin-ts/src/index.ts` | 0 | 0 | 1 | Untrusted count fields passed through unclamped despite "never trusts oversized input" claim |
