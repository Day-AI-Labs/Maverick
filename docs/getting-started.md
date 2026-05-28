# Getting started

## Install

The fastest path needs nothing installed first — the script pulls in
Python + git if they're missing, then runs the wizard.

**Windows** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/texasreaper62/maverick/main/deploy/desktop/install.ps1 | iex
```

**macOS / Linux**:

```bash
curl -fsSL https://raw.githubusercontent.com/texasreaper62/maverick/main/deploy/desktop/install.sh | bash
```

If you already have Python 3.10+, you can use pipx instead:

```bash
pipx install 'maverick-agent[installer]'
```

The PyPI package is `maverick-agent` (the `maverick` name is
squatted). The `[installer]` extra pulls the wizard into the same
pipx environment as the kernel so `maverick init` resolves.

From source while iterating:

```bash
git clone https://github.com/texasreaper62/maverick
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
maverick start "Plan a 2-week trip to Japan. Write the itinerary to trip.md."
```

Watch the swarm work. When done:

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

All local. Nothing is uploaded except your prompts to the cloud LLM you chose.
