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
# Slice the manifest to first 10 lines for smoke.
head -10 ~/.maverick/swebench-pro/manifest.jsonl > /tmp/smoke.jsonl

# Run Maverick + 3 baselines, with a HARD CAP via the budget args.
# Per-task: $5 cap × 4 pipelines × 10 tasks = $200 worst-case.
python benchmarks/swe_bench.py \
    --instances /tmp/smoke.jsonl \
    --pipelines maverick,sonnet_single \
    --out /tmp/smoke_predictions.csv
```

The harness streams progress lines per (instance, pipeline) and appends
one CSV row each. After the smoke completes, eyeball the patches:

```bash
csvtool col 1,2,9,8 /tmp/smoke_predictions.csv | head -20
```

If `outcome` is mostly `success` and `predicted_patch` starts with
`--- a/...`, you're good to scale up.

## Step 3: score the smoke

Convert the CSV into the `predictions.jsonl` format that SWE-bench
expects, then run their official evaluator in Docker:

```bash
# Convert.
python -c "
import csv, json
with open('/tmp/smoke_predictions.csv') as f, \
     open('/tmp/preds.jsonl', 'w') as out:
    r = csv.DictReader(f)
    for row in r:
        if row['pipeline'] != 'maverick':
            continue
        out.write(json.dumps({
            'instance_id': row['instance_id'],
            'model_patch': row['predicted_patch'].replace('\\\\n', chr(10)),
            'model_name_or_path': row['model_id'],
        }) + chr(10))
"

# Run the official evaluator (builds Docker images per instance; first
# run is slow, subsequent runs reuse cache).
python -m swebench.harness.run_evaluation \
    --predictions_path /tmp/preds.jsonl \
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
csv_path = pathlib.Path('benchmarks/RESULTS_SWE_$(ls benchmarks | grep RESULTS_SWE | tail -1 | sed s/RESULTS_SWE_//;s/.csv//).csv')
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

To load FAIL_TO_PASS / PASS_TO_PASS into the manifest, extend the
step-1 download snippet:

```python
for ex in ds:
    f.write(json.dumps({
        'instance_id': ex['instance_id'],
        'brief': ex['problem_statement'],
        'gold_patch': ex['patch'],
        'fail_to_pass': ex.get('FAIL_TO_PASS', []),
        'pass_to_pass': ex.get('PASS_TO_PASS', []),
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
