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
#   BASE_MODEL=Qwen/Qwen2.5-1.5B-Instruct bash train.sh
#
# You supply TWO files (they come from real agent usage, not hardware):
#   * TRAJECTORIES   Klear-format JSONL from maverick's ingest/donation pipeline.
#   * PROPOSER_TEXTS {"id","text"} JSONL mapping trajectory id -> the RAW
#                    proposer transcript (operator-held; kept out of the shared
#                    corpus on purpose). Required for real DPO; set SKIP_DPO=1 to
#                    run only the CPU PRM step without it.
#
# Config (all env vars, with defaults):
#   BASE_MODEL      HF id / local path of the proposer to fine-tune
#                   (default Qwen/Qwen2.5-1.5B-Instruct -- small so the naive
#                   full-param DPO loop fits a 24GB card; bigger models need a
#                   bigger GPU, the reference train() does not use LoRA/4-bit).
#   TRAJECTORIES    default ./trajectories.jsonl
#   PROPOSER_TEXTS  default ./proposer_texts.jsonl
#   OUT_DIR         default ./maverick-train-out
#   SCORES          default ./scores.json (prove-learning runs only if present)
#   INSTALL         1 (pip install 'maverick-agent[training]') | 0 to skip
#   SKIP_DPO        0 | 1 to run only the CPU PRM step
#   DRY_RUN         0 | 1 to print the commands without executing
#   BETA EPOCHS LR MIN_MARGIN MAX_PAIRS   DPO hyperparameters (passed through)
#
# Outputs (PUSH THESE OFF THE POD before you stop it -- pods are ephemeral):
#   $OUT_DIR/prm_linear.json     the learned step PRM (set MAVERICK_PRM=linear)
#   $OUT_DIR/proposer_dpo/       the DPO-tuned proposer
set -euo pipefail

case "${1:-}" in -h|--help)
  sed -n '2,52p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

BASE_MODEL="${BASE_MODEL:-Qwen/Qwen2.5-1.5B-Instruct}"
TRAJECTORIES="${TRAJECTORIES:-./trajectories.jsonl}"
PROPOSER_TEXTS="${PROPOSER_TEXTS:-./proposer_texts.jsonl}"
OUT_DIR="${OUT_DIR:-./maverick-train-out}"
SCORES="${SCORES:-./scores.json}"
INSTALL="${INSTALL:-1}"
SKIP_DPO="${SKIP_DPO:-0}"
DRY_RUN="${DRY_RUN:-0}"
BETA="${BETA:-0.1}"; EPOCHS="${EPOCHS:-1}"; LR="${LR:-5e-7}"
MIN_MARGIN="${MIN_MARGIN:-0.5}"; MAX_PAIRS="${MAX_PAIRS:-32}"

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

# Input validation (skipped in DRY_RUN so the script is inspectable anywhere).
if [ "$DRY_RUN" != "1" ]; then
  [ -f "$TRAJECTORIES" ] || die "TRAJECTORIES not found: $TRAJECTORIES"
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
  say "3b/4 Real DPO fine-tune of the proposer (L3, GPU)"
  run "python -m maverick.training.rlaif \
    --data '$TRAJECTORIES' \
    --text-sidecar '$PROPOSER_TEXTS' --require-real-text \
    --base-model '$BASE_MODEL' --out '$OUT_DIR/proposer_dpo' \
    --beta $BETA --epochs $EPOCHS --lr $LR \
    --min-margin $MIN_MARGIN --max-pairs $MAX_PAIRS"
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
