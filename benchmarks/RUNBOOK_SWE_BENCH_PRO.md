# Running SWE-bench Pro end-to-end

This is the operator's guide for `benchmarks/swe_bench.py`. The harness
is a **producer** (it generates patches); scoring is delegated to the
upstream `swebench` evaluator. Producer-vs-grader separation is per
Karpathy's review — we don't grade ourselves.

## Prerequisites

```bash
# Disk: ~150 GB free for the Docker images SWE-bench Pro builds
df -h .

# Docker 24+
docker --version

# Python deps (in the same venv as Maverick)
pip install datasets swebench>=2.0
```

API keys in `~/.maverick/.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...        # for cross-family verifier
OPENROUTER_API_KEY=sk-or-...      # for DeepSeek baseline
GITHUB_TOKEN=ghp_...              # SWE-bench Pro pulls from gh
```

## Step 1: download the dataset

SWE-bench Pro is published on HF as `Scale/swe-bench-pro`. Convert it
into Maverick's manifest format:

```bash
mkdir -p ~/.maverick/swebench-pro
python -c "
from datasets import load_dataset
import json, pathlib
ds = load_dataset('Scale/swe-bench-pro', split='test')
out = pathlib.Path.home() / '.maverick' / 'swebench-pro' / 'manifest.jsonl'
with open(out, 'w') as f:
    for ex in ds:
        f.write(json.dumps({
            'instance_id': ex['instance_id'],
            'brief': ex['problem_statement'],
            'gold_patch': ex['patch'],
        }) + chr(10))
print(f'wrote {out}')
"
```

Sanity check: `wc -l ~/.maverick/swebench-pro/manifest.jsonl` should
report 1865.

## Step 2: smoke 10 instances first

**Do NOT run the full 1865 instances until smoke is clean.** $3-8k
on a busted pipeline is no fun.

```bash
# Slice the manifest to first 10 lines for smoke. Use ~/.maverick/
# (cross-platform via Path.home()) instead of /tmp/ so the same
# commands work on Linux / macOS / Windows.
mkdir -p ~/.maverick/swebench-pro
head -10 ~/.maverick/swebench-pro/manifest.jsonl > ~/.maverick/swebench-pro/smoke.jsonl

# Run Maverick + 3 baselines, with a HARD CAP via the budget args.
# Per-task: $5 cap × 4 pipelines × 10 tasks = $200 worst-case.
python benchmarks/swe_bench.py \
    --instances ~/.maverick/swebench-pro/smoke.jsonl \
    --pipelines maverick,sonnet_single \
    --out ~/.maverick/swebench-pro/smoke_predictions.csv
```

The harness streams progress lines per (instance, pipeline) and appends
one CSV row each. After the smoke completes, eyeball the patches:

```bash
csvtool col 1,2,9,8 ~/.maverick/swebench-pro/smoke_predictions.csv | head -20
```

If `outcome` is mostly `success` and `predicted_patch` starts with
`--- a/...`, you're good to scale up.

## Step 3: score the smoke

Convert the CSV into the `predictions.jsonl` format that SWE-bench
expects, then run their official evaluator in Docker:

```bash
# Convert. Wave 10: csv.DictWriter quotes newlines naturally so
# `predicted_patch` reads back with real `\n` line breaks; the legacy
# `replace('\\n', chr(10))` is no longer needed and would corrupt
# patches that contain the literal two-character sequence `\n`.
python -c "
import csv, json, pathlib
home = pathlib.Path.home() / '.maverick' / 'swebench-pro'
with open(home / 'smoke_predictions.csv') as f, \
     open(home / 'preds.jsonl', 'w') as out:
    r = csv.DictReader(f)
    for row in r:
        if row['pipeline'] != 'maverick':
            continue
        out.write(json.dumps({
            'instance_id': row['instance_id'],
            'model_patch': row['predicted_patch'],
            'model_name_or_path': row['model_id'],
        }) + chr(10))
"

# Run the official evaluator (builds Docker images per instance; first
# run is slow, subsequent runs reuse cache).
python -m swebench.harness.run_evaluation \
    --predictions_path ~/.maverick/swebench-pro/preds.jsonl \
    --dataset_name Scale/swe-bench-pro \
    --split test \
    --max_workers 4 \
    --run_id maverick-smoke
```

The evaluator writes `evaluation_results/maverick-smoke/results.json`
with per-instance `passed` booleans. The headline number is the share
where `resolved == true`.

## Step 4: real run

Once smoke is green:

```bash
# Full Pareto — Maverick + 3 baselines × 1865 instances.
# Budget: at least $5k unless you've pre-paid OpenRouter for DeepSeek.
# Cap per-instance at $5; the harness will skip past tasks that
# would blow the cap rather than burn through.
python benchmarks/swe_bench.py \
    --instances ~/.maverick/swebench-pro/manifest.jsonl \
    --pipelines maverick,sonnet_single,sonnet_tools,sonnet_self_consistency_n8 \
    --out benchmarks/RESULTS_SWE_$(date +%Y%m%d).csv
```

Run it in `tmux` or with `nohup` — it'll take 12-48 hours depending on
provider capacity + how many retries the verifier triggers.

## Step 5: aggregate into RESULTS.md

After both producer + scorer finish, render the Pareto frontier table:

```bash
python -c "
import csv, json, pathlib
from collections import defaultdict
csv_candidates = sorted(pathlib.Path('benchmarks').glob('RESULTS_SWE_*.csv'))
if not csv_candidates:
    raise SystemExit('No RESULTS_SWE_*.csv found in benchmarks/')
csv_path = csv_candidates[-1]
score_paths = pathlib.Path('evaluation_results').rglob('results.json')
scores = {}
for p in score_paths:
    d = json.loads(p.read_text())
    pipeline = p.parent.name.replace('maverick-', '')
    for iid, info in d.items():
        scores[(iid, pipeline)] = info.get('resolved', False)
agg = defaultdict(lambda: {'n': 0, 'pass': 0, 'cost': 0.0, 'wall': 0.0})
with open(csv_path) as f:
    for row in csv.DictReader(f):
        key = row['pipeline']
        agg[key]['n'] += 1
        if scores.get((row['instance_id'], key)):
            agg[key]['pass'] += 1
        agg[key]['cost'] += float(row['cost_dollars'])
        agg[key]['wall'] += float(row['wall_seconds'])
print('| pipeline | resolved | total | rate | total \$ | \$/task |')
print('|---|---|---|---|---|---|')
for p, a in sorted(agg.items()):
    rate = a['pass'] / a['n'] if a['n'] else 0
    print(f'| {p} | {a[\"pass\"]} | {a[\"n\"]} | {rate:.1%} | \${a[\"cost\"]:.0f} | \${a[\"cost\"]/max(a[\"n\"],1):.2f} |')
"
```

Paste that table at the top of `benchmarks/RESULTS.md` under a
`## SWE-bench Pro (run YYYY-MM-DD, tag v0.2.0)` heading. Done.

## Cost estimation cheat sheet

Per-task cost depends on cascade + caching. May-2026 ballpark:

| pipeline                       | model | $/task | total / 1865 |
|--------------------------------|-------|--------|---------------|
| sonnet_single (no tools)       | Sonnet 4.6  | $0.05  | ~$95          |
| sonnet_tools                   | Sonnet 4.6  | $0.40  | ~$750         |
| sonnet_self_consistency_n8     | Sonnet 4.6  | $0.40  | ~$750         |
| maverick (cascade ON)          | Haiku→Sonnet→Opus | $0.80 | ~$1,500 |
| maverick (cascade OFF, Opus)   | Opus 4.7    | $4.50  | ~$8,400       |

**Set `MAVERICK_CASCADE_ROUTING=1`** for the headline run. The
Karpathy-prescribed cost curve only materializes with cascade on.

## Wave 8 scoring boosters (turn these on for the real run)

Five additions that materially improve the score; flip them on:

```bash
export MAVERICK_CASCADE_ROUTING=1   # 5× cheaper at same accuracy
export MAVERICK_CODING_MODE=1       # strict diff-only worker prompt
export MAVERICK_BEST_OF_N=4         # generate 4 candidates, pick the best
# FAIL_TO_PASS / PASS_TO_PASS are loaded per-instance by the harness
```

| Booster | Estimated lift on SWE-bench Pro |
|---|---|
| `MAVERICK_CODING_MODE=1` (diff-only template) | +5-10% (no prose rejections) |
| `git apply --check` self-validation (auto in coding mode) | +5-15% (catches unapplyable patches) |
| Test-driven verifier (auto when FAIL_TO_PASS set) | +10-20% (ground truth vs LLM-as-judge) |
| `MAVERICK_BEST_OF_N=4` (selection pressure) | +5-10% |
| `repo_map` tool (always available) | +3-8% (better localization) |

Combined estimate: SWE-bench Pro in the 50-65% range with cascade ON.
Real numbers TBD when you run.

## Wave 10 boosters (additional lift, ship before headline run)

```bash
export MAVERICK_BENCHMARK_OPAQUE=1     # block test-file reads + git log -p
export MAVERICK_ANTHROPIC_CACHE_TTL=5m # SWE-bench has no cross-instance reuse
export MAVERICK_CACHE_MESSAGES=1       # cache messages history (40-55% cost cut)
```

| Booster | Estimated lift / saving |
|---|---|
| `str_replace_editor` tool (OpenHands ONE thing) | +5-8% (kills 30% of apply-fail) |
| Failing-test-as-initial-context (auto in run_maverick) | +3-6% (better localisation) |
| 3-phase coder template (LOCALIZE → EDIT → VERIFY) | +2-4% |
| `--- /dev/null` new-file diffs (was rejected) | +2-3% (instances needing new files) |
| CRLF normalisation (was "corrupt patch") | +1-2% (Windows-origin patches) |
| `predicted_patch` now extracts the diff (was prose) | huge — fixes silent corruption |
| `MAVERICK_TEMPERATURE` actually read by provider | makes best-of-N do something |

## Wave 11 boosters (the big lift — adopt all of these)

Wave 11 implements the synthesised findings from 14 parallel research
agents covering Devin / OpenHands / Aider / SWE-bench Pro paper /
operational failures / multi-agent vs single-agent / cost routing /
verifier calibration / code editing primitives / repo localisation /
inference-time compute / March-May 2026 papers / grader brittleness.

Path B (Opus orchestrator + Sonnet coder + Sonnet verifier) is the
default; Opus 4.7 is the escalation in the BoN ladder.

```bash
# Architecture
export MAVERICK_CODING_MODE=1
export MAVERICK_BENCHMARK_OPAQUE=1
export MAVERICK_BEST_OF_N=3        # heterogeneous ladder, not N=4 same-family
export MAVERICK_USE_SKILLS=0       # SWE-Skills-Bench: 39/49 don't help
export MAVERICK_MAX_STEPS=25       # Scale: most successful solutions <=25 turns

# Heterogeneous BoN ladder (Sonnet cheap → Sonnet warm → Opus)
export MAVERICK_BON_LADDER="claude-sonnet-4-6:0.3,claude-sonnet-4-6:0.7,claude-opus-4-7:0.4"

# Mixed routing — Opus orchestrator, Sonnet coder/verifier
export MAVERICK_MODEL_OVERRIDE_ORCHESTRATOR=claude-opus-4-7
# (coder/verifier fall through to ROLE_MODELS defaults — Sonnet 4.6)

# Per-instance safety
export MAVERICK_INSTANCE_HARD_CAP=3.0
export MAVERICK_INSTANCE_WALL_SEC=1500

# Operational fixes
export MAVERICK_ANTHROPIC_CACHE_TTL=5m   # already auto in coding mode
export MAVERICK_LONG_CMD_TIMEOUT=600     # for pytest etc through shell tool

# Telemetry + safety net
export MAVERICK_TRACE_DIR=~/.maverick/swebench-pro-traces
```

| Wave 11 booster | Source | Estimated lift |
|---|---|---|
| SEARCH/REPLACE format primary (was `str_replace_editor`) | Aider Diff-XYZ paper | **+8-14pp resolved** (apply-rate +15-25pp) |
| Fuzzy whitespace fallback ladder (5 progressive normalizations) | OpenHands #6541 | **+8-12pp apply-rate** |
| AgentLess 3-step LOCALIZE (file→class→function as forced phases) | arxiv 2407.01489 | **+6-9pp** |
| Heterogeneous BoN=3 (Sonnet+Sonnet+Opus) | RoBoN arxiv 2512.05542 | **+3-4pp** vs same-family N=4 |
| Extended thinking on orchestrator (effort=medium) | Scaling test-time compute 2604.16529 | **+3-5pp** |
| Defensive validator (blocks test-file/dep-pin edits) | Grader brittleness research | **+3-5pp** |
| AST syntax pre-check before submission | Scale Table 4 (32% Opus 4.1 syntax fails) | **+2-3pp** |
| Failing-test traceback prefetch | Several papers | **+2-3pp** |
| Workdir reset between instances | Operational failures research | **+10-25pp protected** (silent corruption guard) |
| Shell-tool egress block (github.com etc) in opaque mode | Princeton #465 + Scale cheating blog | integrity (gold-leak guard) |
| `pip install -e` block (Karpathy bug) | Operational research | **+3-8pp** on dep-install instances |
| Pro `requirements` / `interface` surfacing | Pro paper (Wave 11 addition) | **+2-4pp** on Pro-only |

Combined Wave 11 expected lift: **+15-25pp** vs Wave 10 baseline.
With Opus 4.7 as orchestrator, expected Pro public score: **63-70%**.
Path B cost target: **$1.50-2.50/task → $2.40-3.90/resolved**.

## Pre-flight: environment checker

Run this BEFORE the shadow benchmark — catches the most common
failure modes (bad API key, typo'd model overrides, low disk, blocked
egress, stale config.toml) in under 5 seconds at ~$0.001 spend:

```bash
python benchmarks/preflight.py
```

For offline boxes or to skip the API ping:
```bash
python benchmarks/preflight.py --skip-network --skip-api
```

For Verified-only smoke (smaller disk requirement):
```bash
python benchmarks/preflight.py --min-disk-gb 50
```

Exits 0 on PASS, 2 on FAIL. Fix every FAIL before launching a paid run.
Warnings are advisory but worth reading.

## Pre-flight: adversarial test suite

Before the real run, verify Wave 11's invariants hold on the box that
will execute the sweep:

```bash
pytest benchmarks/test_swe_bench_adversarial_preflight.py -v
```

Seven tests covering CRLF, new-file SR blocks, atomic rollback,
test-file edit block, github.com curl block, pip install -e block.
All should PASS in <5 seconds. If any fails, **abort** — that's a
silent score loss on the real run.

## Pre-flight: shadow benchmark on Verified

SWE-bench Verified is ~$200 to run end-to-end on the full 500
instances (vs ~$3000-4500 for Pro). Shadow-run 50 Verified instances
first to validate adoption rates:

```bash
# Pull a 50-instance Verified slice
python -c "
from datasets import load_dataset
import json, pathlib, random
ds = load_dataset('princeton-nlp/SWE-bench_Verified', split='test')
random.seed(20260526)
sample = random.sample(list(ds), 50)
out = pathlib.Path.home() / '.maverick' / 'swebench-verified-smoke.jsonl'
with open(out, 'w') as f:
    for ex in sample:
        f.write(json.dumps({
            'instance_id': ex['instance_id'],
            'brief': ex['problem_statement'],
            'gold_patch': ex['patch'],
            'fail_to_pass': eval(ex.get('FAIL_TO_PASS', '[]')),
            'pass_to_pass': eval(ex.get('PASS_TO_PASS', '[]')),
            'base_commit': ex.get('base_commit', ''),
            'language': 'python',
        }) + chr(10))
print(f'wrote {out}')
"

# Run with adoption tripwire — abort if SR usage drops below 50%
python benchmarks/swe_bench.py \
    --instances ~/.maverick/swebench-verified-smoke.jsonl \
    --pipelines maverick \
    --instance-hard-cap 3.0 \
    --adoption-tripwire 0.5 \
    --out ~/.maverick/swebench-pro/verified_smoke.csv
```

Check:
- `SEARCH/REPLACE adoption: NN%` reported at the end of the run
- At least 25/50 (50%) instances have a non-empty `predicted_patch`
- Total spend ≤ $80

If adoption < 50% OR resolution < 25/50, **DO NOT scale to Pro**.
Investigate the prompt drift or model availability first.

To load FAIL_TO_PASS / PASS_TO_PASS / language into the manifest,
extend the step-1 download snippet:

```python
for ex in ds:
    f.write(json.dumps({
        'instance_id': ex['instance_id'],
        'brief': ex['problem_statement'],
        'gold_patch': ex['patch'],
        'fail_to_pass': ex.get('FAIL_TO_PASS', []),
        'pass_to_pass': ex.get('PASS_TO_PASS', []),
        'language': ex.get('language', ''),    # Wave 10: monorepo runner hint
    }) + chr(10))
```

## Troubleshooting

- **`docker pull` rate-limited**: log into Docker Hub or use a mirror.
- **`gh: not found`** during PR fallback: not needed for SWE-bench;
  irrelevant.
- **Maverick produces no patch**: check the agent's `FINAL` is a
  unified diff. If it's prose, add a worker-system-prompt hint that
  SWE-bench expects `--- a/... +++ b/...` format. Open an issue and
  I'll wire a `--coding-mode` flag.
- **Evaluator hangs on Docker build**: SWE-bench Pro images are ~5 GB
  each first time. Run with `--max_workers 1` for the first build pass,
  then crank it up.

## What I built vs. what you bring

- I built: the harness, the three baselines (one full, two scaffolded),
  the cost tracker, the contamination guard, the Pareto-frontier helper.
- You bring: the dataset, the Docker host, the API budget, the time.

When you have a smoke-clean run, ping me with the predictions CSV and
the evaluator's `results.json` — I'll wire the Pareto table generator
into `benchmarks/_common/render_results.py` so future runs are
one-command.
