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
git clone https://github.com/cdayAI/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install -e ./apps/installer-cli
maverick init
```

## First run

Fastest path — one command does setup (if needed) and runs a first goal
live in your terminal:

```bash
maverick onboard
```

It runs the ~2-minute wizard the first time (writing `~/.maverick/config.toml`
and `~/.maverick/.env`), then runs a small goal **in this terminal** so you
watch the swarm decompose, work, and verify in real time. Pass your own
task to skip the demo: `maverick onboard "Summarize README.md in 5 bullets"`.

Prefer to do it in two steps:

```bash
maverick init        # ~2 minutes; safe defaults
maverick start "Plan a 2-week trip to Japan. Write the itinerary to trip.md."
```

Watch the swarm work. When done:

```bash
maverick status        # what's currently active or blocked
maverick skills        # skills the swarm distilled or installed
maverick facts         # what it learned about you
```

Over time the skill library curates itself: each skill's recall ranking
decays if it keeps riding along with failed runs. Inspect each skill's
track record with `maverick skill stats`, and prune chronic non-performers
with `maverick skill evict` (dry-run by default; add `--yes` to remove).

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

All local. Nothing is uploaded except your prompts to the cloud LLM you chose.
