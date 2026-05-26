# Running SWE-bench Verified end-to-end

Operator's guide for the SWE-bench **Verified** path (500 instances,
Python-only, curated by Princeton). This is the headline benchmark for
launch — every comparable agent (Opus 4.7, Sonnet 4.6, GPT 5.5) reports
a Verified number, and [vals.ai](https://www.vals.ai/benchmarks/swebench)
publishes cost-per-test for apples-to-apples comparison.

Use the Pro runbook (`RUNBOOK_SWE_BENCH_PRO.md`) for the multi-language
1,865-instance follow-up run.

## Verified facts (sourced, May 2026)

| Item | Value | Source |
|------|-------|--------|
| Dataset size | 500 instances | [HF dataset card](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified) |
| Domain | Python-only, real GitHub issues | same |
| Difficulty mix | 194 (<15min), 261 (15m-1h), 42 (1-4h), 3 (>4h) | [vals.ai](https://www.vals.ai/benchmarks/swebench) |
| Top score | GPT 5.5 @ 82.60% | [vals.ai](https://www.vals.ai/benchmarks/swebench) (5/16/2026) |
| Cost reference (Opus 4.7) | $2.42/test = $1,210 full | [vals.ai](https://www.vals.ai/benchmarks/swebench) |
| Cost reference (Sonnet 4.6) | $1.30/test = $650 full | same |
| Eval Docker images (Epoch optimized) | 30 GiB | [Epoch AI](https://epoch.ai/blog/swebench-docker) |
| Eval Docker images (default) | ~100 GiB | [SWE-bench docs](https://www.swebench.com/SWE-bench/guides/docker_setup/) |
| Grading wall time | ~62-70 min on 32-core / 128 GB | Epoch AI |

## Prerequisites

```bash
# Disk: ~50 GB for cloned repos + 30 GB for Epoch-optimized Docker
# eval images. 80 GB total recommended.
df -h .

# Docker 24+ (only required for grading; can produce patches without)
docker --version

# Python deps
pip install datasets swebench>=2.0
pip install -e packages/maverick-core
pip install -e packages/maverick-shield  # optional but recommended
```

API key:

```bash
# Generate a scoped key with workspace spend cap at:
#   https://console.anthropic.com/settings/keys
# Set the workspace limit to your max budget (e.g. $1500 for full run).
export ANTHROPIC_API_KEY=sk-ant-...
```

## Step 1: stage instances

Use the included fetcher (Wave 12 hotfix companion) to download the
HF dataset, convert to Maverick manifest format, and (optionally)
clone each instance's repo:

```bash
# 50-instance smoke list — no clones yet (manifest only)
python benchmarks/fetch_swe_bench_verified.py \
    --limit 50 \
    --out-manifest ~/.maverick/verified/smoke50.jsonl

# Full Verified manifest + clone all 500 repos at base_commit
python benchmarks/fetch_swe_bench_verified.py \
    --out-manifest ~/.maverick/verified/manifest.jsonl \
    --stage \
    --repos-dir ~/.maverick/verified/repos

# Sanity check
wc -l ~/.maverick/verified/manifest.jsonl    # should be 500
ls ~/.maverick/verified/repos | wc -l         # should be 500 with --stage
```

The fetcher correctly handles HF's JSON-encoded `FAIL_TO_PASS` /
`PASS_TO_PASS` fields, prepends `https://github.com/` to the
`owner/name` `repo`, and excludes `test_patch` (that's the grader's
holdout — the agent must never see it).

## Step 2: configure for single-Opus-brain (the advertised architecture)

The default ROLE_MODELS already wire orchestrator → Opus and coder →
Sonnet. For Verified we run a SINGLE attempt per instance (no BoN
override) so the published score reflects the actual multi-agent
architecture.

```bash
# Wave 12 verified env vars (single Opus-brain)
export MAVERICK_CODING_MODE=1
export MAVERICK_BENCHMARK_OPAQUE=1
export MAVERICK_USE_SKILLS=0
export MAVERICK_MAX_STEPS=25
export MAVERICK_INSTANCE_HARD_CAP=5.0
export MAVERICK_INSTANCE_WALL_SEC=1500
export MAVERICK_TRACE_DIR=~/.maverick/verified/traces

# CRITICAL: do NOT set MAVERICK_BEST_OF_N (or set to 1). BoN overrides
# the orchestrator role to a single model, defeating the architecture.
unset MAVERICK_BEST_OF_N
```

The harness will:
1. Read the manifest (one JSONL line per instance)
2. Set `MAVERICK_GOLD_PATCH` per instance from the manifest's
   `gold_patch` field (Wave 12 hotfix: this completes the
   defensive_validate cheating-detector plumbing that was previously
   half-wired)
3. Reset the workdir to `base_commit` for each instance
4. Invoke Maverick with Opus as the orchestrator role + Sonnet sub-agents

## Step 3: run smoke (50 instances first)

```bash
# Per-instance cap: $5 × 50 = $250 worst-case.
python benchmarks/swe_bench.py \
    --instances ~/.maverick/verified/smoke50.jsonl \
    --pipelines maverick \
    --out ~/.maverick/verified/smoke_predictions.csv \
    --abort-at-total-dollars 250 \
    --max-consecutive-failures 5
```

The harness streams a line per (instance, pipeline) and appends to the
CSV. After completion check the cost summary printed to stderr.

**If smoke is healthy** (no consecutive errors, costs in line with the
$2-3/test reference), proceed to full Verified. Otherwise debug before
committing the full budget.

## Step 4: run full Verified

```bash
# 500 instances × $5 cap = $2500 worst-case; expected ~$1000-1500
# at Opus 4.7 pricing ($5/$25 per MTok).
python benchmarks/swe_bench.py \
    --instances ~/.maverick/verified/manifest.jsonl \
    --pipelines maverick \
    --out ~/.maverick/verified/predictions.csv \
    --abort-at-total-dollars 2000 \
    --max-consecutive-failures 10 \
    --instance-hard-cap 5.0
```

Wall time: budget 6-12 hours per 500 instances at 25 steps each.

## Step 5: grade with the official SWE-bench evaluator

The harness produces `predicted_patch` per instance. Pass it to the
upstream grader for actual scoring:

```bash
# Convert CSV → JSONL in the format swebench.harness expects
python -c "
import csv, json
from pathlib import Path
predictions = []
with open('$HOME/.maverick/verified/predictions.csv') as f:
    for row in csv.DictReader(f):
        if row['pipeline'] != 'maverick':
            continue
        predictions.append({
            'instance_id': row['instance_id'],
            'model_name_or_path': 'maverick',
            'model_patch': row['predicted_patch'],
        })
Path('$HOME/.maverick/verified/predictions.jsonl').write_text(
    '\\n'.join(json.dumps(p) for p in predictions),
    encoding='utf-8',
)
print(f'wrote {len(predictions)} predictions')
"

# Run the grader (Epoch's optimized image cache: ~30 GB instead of 100 GB)
python -m swebench.harness.run_evaluation \
    --dataset_name princeton-nlp/SWE-bench_Verified \
    --predictions_path ~/.maverick/verified/predictions.jsonl \
    --max_workers 8 \
    --run_id maverick_verified_$(date +%Y%m%d) \
    --cache_level env
```

**Don't have a 30 GB / 32-core machine?** Use [sb-cli](https://github.com/SWE-bench/sb-cli)
to offload grading to Modal:

```bash
pip install sb-cli
sb-cli grade \
    --predictions ~/.maverick/verified/predictions.jsonl \
    --benchmark verified
```

## Reading the result

The grader emits `<run_id>.json` with `resolved_instances`,
`unresolved_instances`, and per-instance breakdowns. Score is
`len(resolved) / 500`.

Save:
- `predictions.csv` (the producer output)
- `run_meta.json` (Wave 12 provenance — git SHA, manifest SHA, env)
- The grader's report JSON
- `traces/<instance>.jsonl` if `MAVERICK_TRACE_DIR` was set

These together let you reproduce the run and defend the score.

## What's known to fail

From prior Wave 11/12 council reviews + Princeton's SWE-bench issues:

1. **Prompt caching no-op on small prompts.** Maverick's system+tools
   total ~1,800 tokens; the 4,096-token min for Sonnet 4.6 / Opus 4.7
   means cache_control on system/tools is silently ignored. The
   messages cache breakpoint still works once history grows past 4k.
   The provider logs a one-time warning surfacing this.

2. **`pip install -e` inside the worktree** silently imports unpatched
   code from the original tree. Maverick's shell tool blocks this in
   opaque mode. If you see "tests still failing despite correct patch"
   in traces, this is usually it.

3. **Instance-specific environment pins.** SWE-bench Verified rows
   include `environment_setup_commit` for a working pre-bug environment.
   The current fetcher records but doesn't act on it — running specific
   instance env setup is left to upstream `swebench` for grading. For
   inference, Maverick reads the workdir as-is.

4. **Defensive validator's cheating detector** requires `gold_patch`
   in env. The Wave 12 hotfix (commit `305ae5f`) wires this from the
   manifest. If you're using a custom manifest builder, ensure
   `gold_patch` field is set.
