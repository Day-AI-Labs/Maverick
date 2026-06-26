#!/usr/bin/env bash
# One-command self-learning training run for a cloud GPU pod (RunPod, Lambda,
# Vast, a cloud VM, or any GPU host). Runs the whole flow with ZERO laptop
# involvement: install -> train the CPU step PRM (L2) -> real DPO fine-tune of
# the proposer (L3, GPU) -> optionally prove the lift. Self-contained: it only
# calls `python -m maverick.training.*` + `maverick`, so it works straight after
# a pip install -- you do NOT need the repo checked out on the pod.
#
# Quick start on a fresh GPU pod (paste once):
#
#   curl -fsSL https://raw.githubusercontent.com/Day-AI-Labs/Lightwork/main/scripts/train_runpod.sh -o train.sh
#   # upload your two inputs to the pod first (see below), then:
#   bash train.sh                      # cheap 0.5B proof run (default)
#   # …or graduate to the strongest ownable model on one 80GB GPU:
#   BASE_MODEL=Qwen/Qwen3-Coder-30B-A3B LORA=1 BITS=4 bash train.sh
#
# Inputs: the script GENERATES both from your maverick data if they're absent,
# so you bring EITHER the two JSONL files OR your ~/.maverick (outbox + world DB):
#   * TRAJECTORIES   Klear JSONL; else generated via `training.ingest` from OUTBOX.
#   * PROPOSER_TEXTS {"id","text"} raw-transcript sidecar; else generated via
#                    `training.export_texts` from OUTBOX + the world DB. Real DPO
#                    needs it; set SKIP_DPO=1 to run only the CPU PRM step.
#   Either way the data comes from REAL runs: enable [telemetry]
#   donate_trajectories = true and run goals first, or there's nothing to train on.
#
# Config (all env vars, with defaults):
#   BASE_MODEL      HF id / local path of the proposer to fine-tune
#                   (default Qwen/Qwen2.5-0.5B-Instruct -- tiny + ungated, for a
#                   cheap first PROOF run on any GPU. For a real ownable model
#                   set LORA=1 BITS=4 and a bigger BASE_MODEL, e.g.
#                   Qwen/Qwen3-8B (24GB) or Qwen/Qwen3-Coder-30B-A3B (80GB)).
#   TRAJECTORIES    default ./trajectories.jsonl
#   PROPOSER_TEXTS  default ./proposer_texts.jsonl
#   OUT_DIR         default ./maverick-train-out
#   OUTBOX          donation outbox to auto-generate inputs from
#                   (default ~/.maverick/outbox)
#   SCORES          default ./scores.json (prove-learning runs only if present)
#   INSTALL         1 (pip install 'maverick-agent[training]') | 0 to skip
#   SKIP_DPO        0 | 1 to run only the CPU PRM step
#   DRY_RUN         0 | 1 to print the commands without executing
#   BETA EPOCHS LR MIN_MARGIN MAX_PAIRS   DPO hyperparameters (passed through)
#   LORA=1 BITS=4    QLoRA (4-bit base + LoRA) -- REQUIRED for base models >~3B.
#                    Graduate run, strongest ownable model on one 80GB GPU:
#                      BASE_MODEL=Qwen/Qwen3-Coder-30B-A3B LORA=1 BITS=4 bash train.sh
#
# Outputs (PUSH THESE OFF THE POD before you stop it -- pods are ephemeral):
#   $OUT_DIR/prm_linear.json     the learned step PRM (set MAVERICK_PRM=linear)
#   $OUT_DIR/proposer_dpo/       the DPO-tuned proposer
set -euo pipefail

case "${1:-}" in -h|--help)
  awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 && !/^#/ {exit}' "$0"
  exit 0 ;;
esac

BASE_MODEL="${BASE_MODEL:-Qwen/Qwen2.5-0.5B-Instruct}"
TRAJECTORIES="${TRAJECTORIES:-./trajectories.jsonl}"
PROPOSER_TEXTS="${PROPOSER_TEXTS:-./proposer_texts.jsonl}"
OUTBOX="${OUTBOX:-$HOME/.maverick/outbox}"
OUT_DIR="${OUT_DIR:-./maverick-train-out}"
SCORES="${SCORES:-./scores.json}"
INSTALL="${INSTALL:-1}"
SKIP_DPO="${SKIP_DPO:-0}"
DRY_RUN="${DRY_RUN:-0}"
BETA="${BETA:-0.1}"; EPOCHS="${EPOCHS:-1}"
MIN_MARGIN="${MIN_MARGIN:-0.5}"; MAX_PAIRS="${MAX_PAIRS:-32}"
LORA="${LORA:-0}"; BITS="${BITS:-0}"
LORA_R="${LORA_R:-16}"; LORA_ALPHA="${LORA_ALPHA:-32}"; LORA_DROPOUT="${LORA_DROPOUT:-0.05}"
# QLoRA needs a much higher LR than full-param DPO; default per path.
if [ "$LORA" = "1" ] || [ "$BITS" != "0" ]; then LR="${LR:-1e-4}"; else LR="${LR:-5e-7}"; fi

say() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
run() { printf '+ %s\n' "$*"; [ "$DRY_RUN" = "1" ] || eval "$*"; }
die() { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

say "Maverick self-learning training run"
printf 'base_model=%s\nout_dir=%s\nskip_dpo=%s dry_run=%s\n' \
  "$BASE_MODEL" "$OUT_DIR" "$SKIP_DPO" "$DRY_RUN"
run "mkdir -p '$OUT_DIR'"

if [ "$INSTALL" = "1" ]; then
  say "1/4 Install (torch + transformers via the [training] extra)"
  run "pip install --quiet 'maverick-agent[training]'"
fi

say "2/4 GPU check"
if [ "$DRY_RUN" != "1" ]; then
  python - <<'PY' || true
try:
    import torch
    print("cuda available:", torch.cuda.is_available(),
          "| device:", (torch.cuda.get_device_name(0)
                        if torch.cuda.is_available() else "CPU"))
    if not torch.cuda.is_available():
        print("WARNING: no CUDA -> DPO will be extremely slow on CPU.")
except Exception as e:
    print("torch not importable:", e)
PY
fi

say "2b/4 Ensure training inputs (generate from your maverick data if missing)"
if [ ! -f "$TRAJECTORIES" ]; then
  printf 'no %s -> generating from %s\n' "$TRAJECTORIES" "$OUTBOX"
  run "python -m maverick.training.ingest --in '$OUTBOX' --out '$TRAJECTORIES'"
fi
if [ "$SKIP_DPO" != "1" ] && [ ! -f "$PROPOSER_TEXTS" ]; then
  printf 'no %s -> generating from %s (+ world DB)\n' "$PROPOSER_TEXTS" "$OUTBOX"
  run "python -m maverick.training.export_texts --in '$OUTBOX' --out '$PROPOSER_TEXTS'"
fi
# Validate (real runs only; generation above may have just created them).
if [ "$DRY_RUN" != "1" ]; then
  [ -s "$TRAJECTORIES" ] || die "no trajectories at $TRAJECTORIES and none generated from $OUTBOX. Run goals with [telemetry] donate_trajectories=true first (see docs/self-learning-runbook.md)."
fi

say "3a/4 Train the CPU step PRM (L2)"
run "python -m maverick.training.prm_linear --data '$TRAJECTORIES' --out '$OUT_DIR/prm_linear.json'"
export MAVERICK_PRM=linear
export MAVERICK_PRM_PATH="$OUT_DIR/prm_linear.json"
printf 'exported MAVERICK_PRM=linear MAVERICK_PRM_PATH=%s\n' "$MAVERICK_PRM_PATH"

if [ "$SKIP_DPO" = "1" ]; then
  say "3b/4 DPO fine-tune (L3) -- SKIPPED (SKIP_DPO=1)"
else
  if [ "$DRY_RUN" != "1" ] && [ ! -f "$PROPOSER_TEXTS" ]; then
    die "PROPOSER_TEXTS not found: $PROPOSER_TEXTS (real DPO needs it; set SKIP_DPO=1 to run only the PRM step)."
  fi
  LORA_ARGS=""
  if [ "$LORA" = "1" ] || [ "$BITS" != "0" ]; then
    LORA_ARGS="--lora --bits $BITS --lora-r $LORA_R --lora-alpha $LORA_ALPHA --lora-dropout $LORA_DROPOUT"
    printf 'QLoRA: 4/8-bit base + LoRA adapters (fits big models on one GPU)\n'
  fi
  say "3b/4 Real DPO fine-tune of the proposer (L3, GPU)"
  run "python -m maverick.training.rlaif \
    --data '$TRAJECTORIES' \
    --text-sidecar '$PROPOSER_TEXTS' --require-real-text \
    --base-model '$BASE_MODEL' --out '$OUT_DIR/proposer_dpo' \
    --beta $BETA --epochs $EPOCHS --lr $LR \
    --min-margin $MIN_MARGIN --max-pairs $MAX_PAIRS $LORA_ARGS"
fi

say "4/4 Prove the lift (optional)"
if [ "$DRY_RUN" != "1" ] && [ -f "$SCORES" ]; then
  run "maverick prove-learning --scores '$SCORES'"
else
  printf 'no %s found -- skipping. To prove the lift: run your held-out suite\n' "$SCORES"
  printf 'under MAVERICK_LEARNING_FROZEN=1 then =0, save paired scores as\n'
  printf '%s, and run: maverick prove-learning --scores %s --strict\n' "$SCORES" "$SCORES"
fi

say "Done"
printf 'Outputs in %s:\n  - prm_linear.json   (set MAVERICK_PRM=linear MAVERICK_PRM_PATH=...)\n' "$OUT_DIR"
[ "$SKIP_DPO" = "1" ] || printf '  - proposer_dpo/     (the DPO-tuned proposer)\n'
printf '\n\033[33mPods are ephemeral:\033[0m copy %s to S3/HF before stopping the pod.\n' "$OUT_DIR"
