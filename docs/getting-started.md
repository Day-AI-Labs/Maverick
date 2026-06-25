# Getting started

## Install

The safest terminal path installs the published package with pipx instead of executing a remote bootstrap script:

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

If you need the no-prerequisite desktop bootstrap, download `deploy/desktop/install.sh` or `deploy/desktop/install.ps1` from a commit or release you trust, verify it, and set `MAVERICK_REF` to a full 40-character commit SHA. The scripts reject mutable branch/tag refs by default.

The PyPI package is `maverick-agent` (the `maverick` name is
squatted). The `[installer]` extra pulls the wizard into the same
pipx environment as the kernel so `maverick init` resolves.

From source while iterating:

```bash
git clone https://github.com/Day-AI-Labs/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install -e ./apps/installer-cli
maverick init
```

## First run

```bash
maverick init
```

The wizard takes ~2 minutes. It writes `~/.maverick/config.toml` and `~/.maverick/.env`.

Then:

```bash
maverick start "Build a CLI that emails me a digest of today's top Hacker News stories — research the API, write it, and verify it runs"
```

## Watch the swarm decompose

Run `maverick monitor` in a second terminal. The orchestrator plans the goal, then spawns specialist sub-agents that work in parallel — here a researcher pins down the API, a coder writes the tool, and a verifier runs it:

```
Goal #1 active  2m elapsed
Build a CLI that emails me a digest of today's top Hacker News stories

Plan tree
  ├─        done  #2 Research the Hacker News Firebase API
  ├─      active  #3 Write the digest CLI (fetch + format + send)
  ├─      active  #4 Verify it runs and emails a sample digest
  ├─     pending  #5 Write a short usage README

Latest episode #7 (running)  $0.0431  in=18,204 out=2,910 tools=11

Recent activity
  4s ago [researcher] decision: top stories live at /v0/topstories.json, then /v0/item/<id>.json
  3s ago [coder] tool_call: write_file hn_digest.py (118 lines)
  1s ago [verifier] tool_call: run "python hn_digest.py --dry-run" -> printed 10 stories

Cumulative spend on this DB: $0.21
```

When done:

```bash
maverick status      # what's currently active or blocked
maverick skills      # what the swarm distilled from this run
maverick facts       # what it learned about you
```

## Pausing / resuming

If the swarm needs something only you can answer, it pauses and queues a question:

```bash
maverick status
# shows: open questions: #3 (goal 1): Which dates are you traveling?

maverick answer 3 "May 15-29"
maverick resume
```

Goals survive restarts. You can shut your laptop and come back tomorrow.

## Changing models or providers

Re-run the wizard any time:

```bash
maverick init
```

Or edit `~/.maverick/config.toml` directly. The `[models]` section maps each agent role to a `provider:model-id` string. See [`configuration.md`](./configuration.md) for the schema.

## Where data lives

| File | What |
|---|---|
| `~/.maverick/config.toml` | Your config (deployment, models, safety, budget) |
| `~/.maverick/.env` | API keys (chmod 600) |
| `~/.maverick/world.db` | Persistent world model: goals, facts, episodes |
| `~/.maverick/skills/` | Auto-distilled SKILL.md files from successful runs |
| `~/maverick-workspace/` | Default sandbox working directory |
| `~/.maverick/learned-skills/` | Skills distilled by the learning loops |
| `~/.maverick/dreams/` | Consolidated insights, rehearsal queue, learning snapshots |

All local. Nothing is uploaded except your prompts to the cloud LLM you chose.

Once you have a few runs behind you, the learning surface is four commands:
`maverick dream` (consolidate experience), `maverick hindsight` (did learning
help or regress?), `maverick proof` (deliverables, cost avoided, ROI), and
`maverick domains-lint` (audit the 2,020-agent specialist catalog), plus
`maverick domains-audit` (governance posture: what each agent can reach, denies,
and refuses) and `maverick domains-eval --check` (behavioral golden cases).
