# Self-learning training runbook

Everything needed to train and *prove* the self-learning loop, end to end. The
loop has three rungs — all wired and tested; this page is how you actually run
them.

| Rung | What it does | Hardware |
|---|---|---|
| **L1** dream consolidation | LLM rewrites recurring failures into transferable lessons | CPU (uses your configured LLM) |
| **L2** learned step PRM | a learned per-step signal scores every agent step | **CPU** (no GPU) |
| **L3** DPO fine-tune | nudges the proposer toward verifier-preferred attempts | **GPU** |
| proof harness | reproducible A/B that the learning actually helped | CPU |

## 0. Prerequisite: produce training data (the real gate)

Neither your laptop nor the cloud can manufacture this — it comes from **real
runs**. Turn on donation, then use Maverick normally:

```toml
# ~/.maverick/config.toml
[telemetry]
donate_trajectories = true     # off by default; writes scrubbed records to ~/.maverick/outbox/
```

```bash
maverick start "…a real goal…"     # run a bunch; high-confidence runs (verifier ≥ 0.75) get donated
maverick donate status             # see what's queued in the outbox
```

The two training inputs are generated from this data (you don't hand-write them):

- `trajectories.jsonl` ← `python -m maverick.training.ingest` (from the outbox + world DB)
- `proposer_texts.jsonl` ← `python -m maverick.training.export_texts` (raw transcripts from the world DB, keyed to the same ids)

The one-command runner does both for you. **No outbox data ⇒ nothing to train on.**

---

## Option A — everything in the cloud, one command (no laptop)

On a GPU pod (RunPod / Lambda / Vast / any GPU VM):

1. Get your data onto the pod — **either** copy your `~/.maverick/` (so the
   outbox + `world.db` are present and inputs auto-generate), **or** pre-run the
   two `ingest`/`export_texts` commands at home and upload the two `.jsonl` files.
2. Paste one line:

```bash
curl -fsSL https://raw.githubusercontent.com/Day-AI-Labs/Lightwork/main/scripts/train_runpod.sh -o train.sh \
  && BASE_MODEL=Qwen/Qwen2.5-1.5B-Instruct bash train.sh
```

It installs (`maverick-agent[training]` → torch + transformers), generates any
missing inputs, trains the L2 PRM (CPU), runs real DPO (GPU,
`--require-real-text`), and prints where the outputs are.

3. **Copy the outputs off the pod before stopping it** (pods are ephemeral):
   `maverick-train-out/prm_linear.json` and `maverick-train-out/proposer_dpo/`
   → S3 / Hugging Face.

Useful env vars: `BASE_MODEL`, `OUTBOX`, `OUT_DIR`, `SKIP_DPO=1` (CPU PRM only),
`DRY_RUN=1` (preview the commands), `BETA/EPOCHS/LR/MIN_MARGIN/MAX_PAIRS`.
`bash train.sh --help` prints them all.

> Privacy: `export_texts` writes your raw transcripts to a local file (the thing
> the shared corpus deliberately avoids). Fine on a box you control; sending it
> to a third party is a deliberate egress decision. For air-gap, use your own GPU.

---

## Option B — step by step (local or remote, full control)

```bash
# 1. Generate the two inputs from your runs
python -m maverick.training.ingest        --in ~/.maverick/outbox --out trajectories.jsonl
python -m maverick.training.export_texts  --in ~/.maverick/outbox --out proposer_texts.jsonl

# 2. L2 — train the learned step PRM (CPU, seconds)
python -m maverick.training.prm_linear --data trajectories.jsonl --out prm_linear.json
export MAVERICK_PRM=linear MAVERICK_PRM_PATH="$PWD/prm_linear.json"

# 3. L3 — real DPO (GPU; needs the [training] extra)
pip install 'maverick-agent[training]'
python -m maverick.training.rlaif \
    --data trajectories.jsonl \
    --text-sidecar proposer_texts.jsonl --require-real-text \
    --base-model <hf-id> --out ./proposer_dpo
```

---

## Prove it actually learned (the part that makes "self-improving" defensible)

Run a held-out task suite twice — learning frozen vs live — score each with the
verifier, then compute the lift:

```bash
# control arm (no learning) then treatment arm (learning live), same tasks/seeds
MAVERICK_LEARNING_FROZEN=1  maverick start ...   # collect "baseline" scores
MAVERICK_LEARNING_FROZEN=0  maverick start ...   # collect "treatment" scores

# scores.json = {"baseline": [...], "treatment": [...]}  (paired per task)
maverick prove-learning --scores scores.json --strict
```

`prove-learning` reports the mean paired lift with a seeded bootstrap 95% CI
(reproducible); `--strict` exits non-zero unless learning *significantly*
improved — a CI gate you can wire in.

---

## Troubleshooting

- **"no transcripts" / "no trajectories"** → the outbox is empty. You haven't run
  goals with `donate_trajectories = true` yet (step 0).
- **DPO is extremely slow** → you're on a CPU pod. The PRM/proof steps are CPU,
  but L3 needs a GPU.
- **OOM during DPO** → the reference loop is full-param (no LoRA/4-bit); use a
  smaller `BASE_MODEL` or a bigger card. (Ask for LoRA/4-bit support if you need
  to tune a 7B+ model on one mid-range GPU.)
- **`import transformers` fails** → install the extra: `pip install 'maverick-agent[training]'`.

See also: `docs/self-learning.md` (concepts), `scripts/train_runpod.sh` (the runner).
