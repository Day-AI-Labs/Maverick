# Lightwork — Live Demo Script (the receipts)

> **Purpose:** a 6–8 minute live demo for a seed investor (or a design-partner
> security review) that *shows* the governance and learning instead of claiming
> them. **Every command here is real, runs offline, needs no API key, and is
> deterministic** — so it can't fail live and nothing is fabricated. Outputs
> below are the *actual* current outputs, captured 2026-06-16.
>
> **The one-sentence frame, said up front:** "I'm not going to tell you it's
> governed — I'm going to run it and you'll watch it refuse the dangerous
> action and leave a receipt you can verify."

---

## Pre-flight (do this before they're in the room)

```bash
pip install maverick-core            # or: from the monorepo, the editable install
maverick version                     # confirm it runs
```

- Terminal at a **large, readable font.** Dark theme.
- Pre-create one bundle as a fallback in case the room has no shell:
  `python -m maverick.golden_path -o /tmp/gp` and
  `python -m maverick.proof_pack -o /tmp/pp` — keep `/tmp/gp/story.md`,
  `/tmp/pp/PROOF.md`, and `/tmp/pp/proof_manifest.json` open in an editor tab.
- Have `pitch/SEED-DECK.md` slide 5 ("Product") on screen to cut back to.

**Why these four acts:** governance (it refuses), proof (it signs), learning
(it improves), library (it scales) — the four things a regulated buyer's review
actually gates on, in the order they ask about them.

---

## Act 1 — Governance: watch it refuse (≈2 min) — *the money shot*

**Say:** "One seeded run of a finance specialist under governance. No model is
called — every verdict is the real enforcement code, and every step leaves a
signed audit row."

**Run:**
```bash
python -m maverick.golden_path -o /tmp/gp
```

**They see (real output):**

| # | the agent asks to… | verdict | receipt |
|---|---|---|---|
| 1 | inherit the controller's full reach | **SEALED** | runs at max_risk='medium' (parent 'high'); can read AP, **cannot** open a shell, **cannot** release payments |
| 2 | wire_transfer **$60,000** | **DENY** | governance rule `deny_above` fired |
| 3 | release_payment **$6,000** | **REQUIRE_HUMAN** | governance rule `require_human_above` fired |
| 4 | release_payment $4,000 | **ALLOW** | rule `default` |
| 5 | burn past the $0.10 ceiling | **CAPPED** | hard budget ceiling held |
| 6 | verify the chain, then alter one amount | **TAMPER-EVIDENT** | authentic chain verifies clean; changing $60,000→$60 is caught (`bad_hash`) |

**Land the point (one breath each):**
- "It **booted sealed** — it physically can't open a shell or move money, even
  though its parent could. Least privilege by construction, not by prompt."
- "The **$60k wire was denied** and the **$6k release required a human** — a
  dollar-tier authority gate, not a model's opinion."
- "A runaway loop **hit the hard budget ceiling and stopped.**"
- "And it's all a **signed hash-chain** — watch: silently changing one amount
  is **caught.** That's the tamper-evidence a regulator asks for."

**Prove it's not theater:**
```bash
maverick audit verify --file /tmp/gp/audit.ndjson
```
"That's a real signed audit file. You can verify it offline, without us."

---

## Act 2 — Proof: it signs its own guarantees (≈1.5 min)

**Say:** "Most vendors hand you a PDF of claims. Lightwork emits a **signed
evidence bundle** — and it's honest about what it *hasn't* measured."

**Run:**
```bash
python -m maverick.proof_pack -o /tmp/pp
cat /tmp/pp/PROOF.md
```
> *(The run prints reliability "transient failure / retry" lines first — that's
> the chaos game-day deliberately injecting faults and showing the backoff
> absorb them. If the room is jumpy, just `cat /tmp/pp/PROOF.md` from the
> pre-built bundle instead.)*

**They see (real):** `ALL HARD GUARANTEES HOLD.`

| section | status | evidence |
|---|---|---|
| `governance` *(hard)* | **PASS** | 7 guarantees proven |
| `reliability` *(hard)* | **PASS** | chaos game-day exit 0; 1,500 calls 88.8% success; 16 writers × 25 rows, 0 errors |
| `perf_sla` *(hard)* | **PASS** | dispatch p95 0.58ms; world write p95 0.47ms; read p95 8.3ms — all under budget |
| `shield_asr` | PASS | built-in shield, attack-success 1.00→0.29 (detection layer) |
| `learning_curve` | **INSUFFICIENT DATA** | no run history yet — never invents a curve |
| `benchmarks` | **NOT RUN (needs key)** | competitive scores never fabricated; prints the exact reproduce command |

**Land the point:** "The three **hard** guarantees ran against the real code on
this machine, no mocks, and they gate the verdict. And notice the honesty:
`learning_curve` says *insufficient data* and `benchmarks` says *not run*
because I don't have a provider key on this laptop — **it refuses to fabricate a
number.** That's the posture that survives your technical diligence." Then show
the signature line of `proof_manifest.json`: "Ed25519 over the canonical
payload — verifiable offline."

---

## Act 3 — Learning: prove it improves (≈1.5 min)

**Say:** "A workforce isn't static. Here's a quarter of finance work — wins, and
one pattern that keeps failing — and the platform learning from it. Still no API
key; fully deterministic."

**Run:**
```bash
maverick demo
```

**They see (real):**
```
1) DREAM — consolidate the quarter's experience:
   replayed 3 success(es) + 2 failure(s); wrote 1 insight, distilled 1 skill…
2) HINDSIGHT — did learning help on the failures?
   coverage 0 → 2 (+2); 2 gained, 0 regressed.
3) PROOF — the value report:
   Deliverables completed : 3   Cost avoided : $360.00
```

**Land the point:** "It **consolidated** the quarter (we call it *dreaming*),
distilled a reusable skill, then **replayed the past failures and showed
coverage went 0→2** — measured improvement, not vibes. And critically: every one
of those learning steps is **governed, audited, and reversible** — there's a
`maverick rewind` for goals and a snapshot/rollback for the learning itself. A
self-improving system a regulator will actually allow, because it can be undone
and proven."

---

## Act 4 — Library & scale: it's deep, not a demo (≈1 min)

**Say:** "Last thing — this isn't a thin wrapper that works for one scripted
case."

**Run:**
```bash
maverick domains-lint
```
**They see (real):** `1118 pack(s): 0 error(s), 0 warning(s)`

**Land the point:** "**1,118 least-privilege specialist packs across 26 suites,
zero lint errors.** Plus ~310,000 lines of infrastructure that runs self-hosted
or air-gapped. This is the part a competitor doesn't reproduce
in a quarter — and that an incumbent's hosted product can't air-gap into your
bank."

---

## The close (30 sec)

"So in six minutes you watched it **refuse a $60k wire and require a human on a
$6k one**, **sign its own guarantees while refusing to fabricate the ones it
can't measure**, **prove it learned from failures — reversibly**, and do it
across a **1,118-pack governed library** you can self-host or air-gap. That's
the layer a regulated enterprise needs *around* the agent — and it's the layer
nobody else ships. `[FILL: We're raising $X to put it in front of 3 design
partners and turn on the first ARR.]`"

---

## Quick reference — every command in order

```bash
maverick version                                  # pre-flight
python -m maverick.golden_path -o /tmp/gp         # Act 1: it refuses
maverick audit verify --file /tmp/gp/audit.ndjson #         verify offline
python -m maverick.proof_pack -o /tmp/pp          # Act 2: it signs
cat /tmp/pp/PROOF.md                              #         the clean view
maverick demo                                     # Act 3: it improves
maverick domains-lint                             # Act 4: 1,118 packs, 0 errors
```

## If something goes sideways
- **No shell in the room:** screen-share the pre-built `/tmp/gp/story.md`,
  `/tmp/pp/PROOF.md`, and the deck's slide-5 screenshots. The story is identical.
- **"Is this cherry-picked?":** the seeds are in the repo; offer to change a
  threshold live (e.g. make the $4k release a $40k one) and rerun — the
  `require_human` / `deny` tiers move with it. That's the strongest possible
  proof it's enforcement, not a script.
- **"Does it need your cloud?":** no — everything you just saw ran locally with
  no network and no API key. That *is* the air-gap story.
