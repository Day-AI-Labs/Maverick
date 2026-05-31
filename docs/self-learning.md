# Self-learning

When you ask Maverick to do something it doesn't yet have the capability
for, it can **acquire the capability itself** — install a skill, drive a
REST API, or generate a brand-new tool — instead of giving up. MCP servers
remain operator-managed because they launch host subprocesses.

It's **off by default**. The kernel runs unchanged unless you turn it on,
because "create a tool" means generating and executing fresh code in your
process — an explicit trust decision.

## Enabling it

In the installer wizard, answer **yes** to "Enable self-learning?", or
edit `~/.maverick/config.toml`:

```toml
[self_learning]
enable          = true   # master switch (default false)
preflight       = true   # pre-acquire likely skills before each run
create_tools    = true   # let the agent generate + run new tools
add_mcp_servers = false  # legacy; agent-driven MCP subprocesses are disabled
max_acquisitions = 5     # cap on auto-acquisitions per run
```

Or for a one-off run: `MAVERICK_SELF_LEARNING=1 maverick start "..."`.
The env var also force-*disables* (`MAVERICK_SELF_LEARNING=0`) over config.

## How it works

There are two triggers, and they share one acquisition engine.

**1. Pre-flight (before the run).** When `preflight` is on, the
orchestrator makes one cheap LLM call to identify specialised
capabilities the goal may need, searches the federated
[catalog](plugins.md) for matching **skills**, and installs the best
hash-verified match. Those steps are already in context on the agent's
first turn.

**2. In-loop `learn_capability` tool (during the run).** When the agent
realises mid-task that it's missing something, it calls this tool:

| op | what it does |
| --- | --- |
| `search` | find catalog skills / MCP servers / plugins matching a need, plus already-loaded tools |
| `acquire_skill` | install a catalog skill by name (hash-verified) and inject its steps immediately |
| `add_mcp_server` | disabled for agent-driven self-learning; ask an operator to add trusted `[mcp_servers.<name>]` config |
| `create_tool` | generate a Python tool from a description, validate it, and register it live |
| `find_api` | drive any REST API through the built-in `openapi_runner` (no new code) |

Anything acquired is registered into the **live** tool registry, so the
agent can use it on its very next turn — no restart.

## What persists

- **Skills** install to `~/.maverick/skills/*.md` (the normal skill store).
- **MCP servers** are not written by self-learning. Operators can still add
  trusted `[mcp_servers.<name>]` blocks to `~/.maverick/config.toml`.
- **Generated tools** are written to `~/.maverick/generated_tools/*.py`.
  When self-learning is enabled, the kernel loads them as first-class
  tools at the start of every run.
- A ledger of everything learned is appended to
  `~/.maverick/learned.ndjson`. List it with:

  ```bash
  maverick learned
  ```

## Safety

Self-learning honors the same chokepoints as the rest of the kernel:

- **Off by default** — no extra persisted state until you opt in.
- **Budget** — the generation LLM call is metered against the run's
  [budget](configuration.md); `max_acquisitions` bounds churn per run.
- **Shield** — generated tool source is scanned through the
  [Shield](safety.md) (when installed) before it is ever imported;
  blocked source is rejected.
- **Catalog trust** — `acquire_skill` only installs curated,
  SHA-256-pinned catalog entries, so a fetched skill must match the
  index byte-for-byte.
- **MCP subprocess safety** — self-learning does not persist or hot-start
  model-supplied MCP commands; operators must configure trusted servers.

Because generated tools execute in-process, enabling `create_tools` is a
genuine trust decision. Leave it off (or set `create_tools = false`) if
you only want the safer acquisition paths (skills / APIs).
