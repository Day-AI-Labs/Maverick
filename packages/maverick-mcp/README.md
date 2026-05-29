# maverick-mcp-server

A Model Context Protocol (MCP) server that exposes Maverick's agent
loop as a set of MCP tools. Any MCP-compatible client (Claude Code,
Claude Desktop, Cursor, etc.) can drive Maverick over stdio JSON-RPC.

## Why

Maverick is a swarm of agents with persistent memory, budget caps,
and verifier loops. Most MCP clients are single-turn. By plugging
Maverick in via MCP, you get:

- A "think hard for an hour" tool from inside Claude Code
- Persistent goals that survive editor restarts
- Per-role model routing controlled by your `~/.maverick/config.toml`
- Auto-distilled skills that compound across sessions

## Install

```bash
pip install -e ./packages/maverick-mcp
```

## Wire into Claude Code

Add to your Claude Code MCP config (typically
`~/.config/claude-code/mcp.json` or similar):

```json
{
  "mcpServers": {
    "maverick": {
      "command": "maverick-mcp",
      "args": []
    }
  }
}
```

Then restart Claude Code. The Maverick tools should appear under the
MCP servers menu.

## Tools exposed

| Tool | What it does |
|---|---|
| `maverick_start` | Start a new goal, run the swarm, return the final answer |
| `maverick_status` | List recent goals + open questions |
| `maverick_resume` | Resume a paused goal |
| `maverick_answer` | Answer a queued question |
| `maverick_skill_install` | Install a SKILL.md from URL / gh:org/repo / local path |
| `maverick_skills_list` | List installed / distilled skills |
| `maverick_fact_set` | Set a fact in the world model |
| `maverick_facts_get` | Get all known facts |

All calls go through `maverick.orchestrator.run_goal` -- same Shield
chokepoints, same budget caps, same per-role model routing.

## Protocol

Minimal JSON-RPC 2.0 over stdio, matching the MCP 2024-11-05 spec
(`initialize`, `tools/list`, `tools/call`). No external dependencies.
The full `mcp` Python SDK is an option for a future hardening pass;
this hand-rolled version keeps the dependency footprint tiny.
