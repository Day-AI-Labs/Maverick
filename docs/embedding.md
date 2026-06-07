# Embedding Maverick

How to drive Maverick from inside another application — Python web frameworks
(FastAPI / Django / Flask), chat channels (Slack / Discord / Telegram), or any
language over MCP. Maverick is a library first; the CLI is just one caller.

> **One rule that bites everyone:** `run_goal_sync()` is **blocking** and runs
> its own event loop internally (`asyncio.run`). In an async app (FastAPI,
> async Django) you **must** call it in a worker thread — never `await` it
> directly and never call it on the running event loop, or you'll get
> `asyncio.run() cannot be called from a running event loop`.

## In-process (Python)

The kernel API the CLI itself uses. Set `MAVERICK_NO_CLI=1` before import to skip
the Click import cost if you only need the library.

```python
import os
os.environ.setdefault("MAVERICK_NO_CLI", "1")

from maverick.world_model import open_world          # SQLite-backed state
from maverick.llm import LLM                          # model facade (reads ~/.maverick/config.toml)
from maverick.budget import budget_from_config        # honors [budget] + caps
from maverick.sandbox import build_sandbox            # honors [sandbox] backend
from maverick.orchestrator import run_goal_sync       # drives the swarm

def run(goal: str, *, max_dollars: float = 5.0, max_depth: int = 3) -> str:
    world = open_world()                               # default ~/.maverick/world.db
    try:
        goal_id = world.create_goal(goal, "")
        llm = LLM()                                    # default model from config
        budget = budget_from_config(defaults={"max_dollars": max_dollars,
                                              "max_wall_seconds": 3600.0})
        return run_goal_sync(llm, world, budget, goal_id,
                             sandbox=build_sandbox(), max_depth=max_depth)
    finally:
        world.close()

print(run("Summarize the top 3 AI papers this week into report.md"))
```

Provider keys come from the environment / `~/.maverick/config.toml` exactly as
for the CLI (`ANTHROPIC_API_KEY`, etc.).

## FastAPI

Dispatch the blocking run on a thread so it never wedges the event loop:

```python
import asyncio
from fastapi import FastAPI
from myapp.maverick_runner import run   # the run() above

app = FastAPI()

@app.post("/goals")
async def start_goal(goal: str):
    result = await asyncio.to_thread(run, goal)   # blocking call off the loop
    return {"result": result}
```

## Flask

Flask views are synchronous, so call `run()` directly (use a task queue —
Celery/RQ — for long goals so the request doesn't hang):

```python
from flask import Flask, request, jsonify
from myapp.maverick_runner import run

app = Flask(__name__)

@app.post("/goals")
def start_goal():
    return jsonify(result=run(request.json["goal"]))
```

## Django

Sync view: call `run()` directly. Async view: wrap it in `sync_to_async` (which
runs it in a threadpool):

```python
# async view
from asgiref.sync import sync_to_async
from django.http import JsonResponse
from myapp.maverick_runner import run

async def start_goal(request):
    result = await sync_to_async(run, thread_sensitive=False)(request.POST["goal"])
    return JsonResponse({"result": result})
```

For production, run goals in a worker (Celery/Django-Q) and return a job id; poll
the world model (`open_world().get_goal(goal_id)`) for status.

## Chat channels (Slack / Discord / Telegram / …)

Channels are **config-driven** — you don't write adapter code. Enable them in
`~/.maverick/config.toml` (the installer wizard writes this) and run the channel
server:

```toml
[channels.slack]
bot_token = "${SLACK_BOT_TOKEN}"
app_token = "${SLACK_APP_TOKEN}"
allowed_user_ids = ["U123..."]      # authz allowlist

[channels.telegram]
bot_token = "${TELEGRAM_BOT_TOKEN}"
```

```bash
maverick serve         # starts every configured channel; each message becomes a goal
```

Discord, Telegram, SMS/Twilio, Email, Matrix, and more ship the same way — one
`[channels.<name>]` block each. See `docs/configuration.md` for the full list.

## Any language, or another agent (MCP / A2A)

- **MCP** — Maverick's official cross-language surface. Run `maverick mcp` (stdio)
  or `maverick mcp --http` and drive it from TypeScript / Go / Rust / .NET / JVM,
  or any MCP-speaking IDE client. See [`docs/clients/`](./clients/) for ~20-line
  quickstarts.
- **A2A** — to let *other agents* discover and delegate goals to this instance,
  enable A2A (`MAVERICK_A2A_ENABLED=1`); it serves an Agent Card at
  `/.well-known/agent-card.json` and a task endpoint at `/a2a/v1`. See
  [`docs/a2a.md`](./a2a.md).

## REST (the dashboard API)

`maverick dashboard` exposes a REST API (interactive docs at `/docs`) for goals,
episodes, and the world model — handy for a custom web UI without embedding the
Python kernel directly.

## Notes

- **Budget is mandatory** — always pass a `Budget` / `budget_from_config(...)`;
  every long-running path respects it.
- **Sandboxing** — `build_sandbox()` honors your `[sandbox]` backend (local,
  docker, podman, …); shell/tool execution is mediated through it.
- **One world per process is simplest** — `open_world()` returns a SQLite-backed
  handle; close it when done. Concurrent writers serialize via WAL.
