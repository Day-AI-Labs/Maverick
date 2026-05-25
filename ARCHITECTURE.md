# Architecture

Maverick is a recursive multi-agent swarm with a safety layer at every chokepoint.

## Big picture

```
                          ┌────────────────┐
  user message  ──────────▶ │  shield.scan   │ ──block──▶ reject
                          └───────┬────────┘
                                  │ pass
                                  ▼
                  ┌────────────────────────────────┐
                  │    Orchestrator agent (Opus)        │
                  │  plans → spawns → verifies → final  │
                  └─┬────────────────────────────────┘
                    │ spawn_swarm / spawn_subagent
      ┌──────────┼──────────┐
      ▼           ▼           ▼
  researcher    coder       writer       (parallel Sonnet workers)
      │           │           │
      └────────────────────────────┘
            shared state via SwarmContext:
              • Blackboard (per run, in-memory)
              • WorldModel (SQLite + FTS5, persistent)
              • Budget (global token/$/wall/tool caps)
              • Sandbox (local / docker / ssh)
              • Shield (input / tool / output scans)
```

## Components

### `packages/maverick-core/`

The agent kernel. Ported from `texasreaper62/research/maverick/` and evolved here.

| Module | Role |
|---|---|
| `agent.py` | The recursive `Agent`. Every node in the swarm is one of these. |
| `orchestrator.py` | Entry point `run_goal()` — wires SwarmContext, runs the root agent. |
| `swarm.py` | `SwarmContext` shared by all agents in a run. |
| `blackboard.py` | Append-only shared workspace for one run. |
| `world_model.py` | SQLite + FTS5: goals, episodes, facts, questions, messages. |
| `budget.py` | Hard caps on tokens, $, wall-clock, tool calls. Raises `BudgetExceeded`. |
| `llm.py` | Anthropic adapter — caching, thinking, streaming, per-role models. |
| `config.py` | TOML config loader. Per-role model choice lives here. |
| `skills.py` | Auto-distill successful trajectories into reusable SKILL.md files. |
| `cli.py` | `maverick start / status / answer / resume / fact / facts / skills`. |
| `sandbox/` | Execution backends: `local.py` (subprocess) today; `docker.py`, `ssh.py` next. |
| `tools/` | `read_file`, `write_file`, `list_dir`, `shell`, `ask_user`, `spawn_subagent`, `spawn_swarm`. |

### `packages/maverick-shield/`

Thin Python wrapper over `agent-shield`. Provides three chokepoints:

- `Shield.scan_input(text)` — before user input enters the orchestrator
- `Shield.scan_tool_call(name, args)` — before any tool executes
- `Shield.scan_output(text)` — before the final answer reaches the user

If `agent-shield` is not installed, all methods become no-ops (with a startup warning). This keeps the kernel usable for research, while making the safe path the default for end users installed via the wizard.

### `apps/installer-cli/`

`maverick init` — the interactive wizard. The single source of truth for user-facing UX. Walks through:

1. Deployment target (Desktop / Docker / VPS / Phone companion)
2. AI providers (Anthropic / OpenAI / OpenRouter / Ollama)
3. Per-role model picks
4. Safety profile (Strict / Balanced / Permissive / Off)
5. Sandbox backend
6. Budget caps
7. API keys (stored in `~/.maverick/.env`, chmod 600)

Writes `~/.maverick/config.toml`, then runs a smoke test.

### `apps/installer-desktop/` (planned)

Tauri-based GUI installer for users who would never open a terminal. Reuses the same wizard logic by calling into the Python core; ships as a notarized DMG / signed .exe / AppImage.

## Long-horizon properties

What makes Maverick different from OpenClaw / Hermes on the long-horizon axis:

1. **Persistent typed world model.** Goals, facts, episodes, and questions survive restarts. The agent can pause overnight and resume.
2. **Recursive spawning with depth + budget caps.** Sub-agents can spawn sub-sub-agents until depth or budget runs out, never longer. Both `spawn_subagent` (blocking) and `spawn_swarm` (parallel) tools.
3. **Closed learning loop.** Every successful run distills into `~/.maverick/skills/<name>.md`. Future runs auto-load relevant skills into the orchestrator's brief via lexical match (embeddings later).
4. **Per-role model routing.** Heavy roles (orchestrator, revisor) get the strongest model; cheap roles (summarizer) get the smallest. Configurable per user.
5. **Async + streaming.** Workers run in parallel via `asyncio.gather`; orchestrator streams output back to user.

## Multi-agent properties

What makes Maverick a real multi-agent system, not just N parallel instances:

1. **Shared blackboard.** Specialists never talk directly; they post observations and findings to a single board the orchestrator reads.
2. **Shared world model.** Facts written by one agent are visible to siblings.
3. **Shared budget.** Tokens, $, tool calls are counted across the entire swarm. One greedy worker can't drain the run.
4. **Shared sandbox.** All workers see the same filesystem and tool state.
5. **Verifier role.** The orchestrator verifies child outputs before synthesizing. On failure, a `revisor` re-runs with extended thinking.

## Deployment targets

| Target | How it runs | Status |
|---|---|---|
| **Desktop** | `pipx install maverick`; runs in user's home dir. Single-file PyInstaller / notarized signed app next. | v0.1 today |
| **Docker** | `docker run -v ~/.maverick:/root/.maverick ghcr.io/texasreaper62/maverick`. Isolated sandbox. | next |
| **VPS** | systemd unit + Caddy reverse proxy. `maverick init --target=vps` generates the stack. | next |
| **Phone (companion)** | Maverick runs on Desktop or VPS; phone talks to it via Telegram / iMessage / WhatsApp bot. Native iOS/Android later. | next |

## Adding a new feature

The rule of thumb (see CLAUDE.md):

- Capability code goes in a package under `packages/`.
- Entry points / UX go under `apps/`.
- The wizard (`apps/installer-cli/`) must learn to enable/disable it, otherwise non-technical users can't reach it.
- Defaults live in code; user overrides live in `~/.maverick/config.toml`.
