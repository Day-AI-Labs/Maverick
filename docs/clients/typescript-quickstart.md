# Maverick from TypeScript / JavaScript

Drive a locally running Maverick swarm from a TS / Node app over the
[Model Context Protocol](https://modelcontextprotocol.io/). Same
contract every IDE-side MCP client uses — you talk to `maverick mcp`
over stdio JSON-RPC.

This is the official cross-language surface. We don't ship a separate
`@maverick/core` port; we ship one Python kernel and you talk to it
from any language an MCP SDK exists in.

## Prereqs

```bash
pip install maverick-agent maverick-mcp-server   # in any venv on the same machine
npm i @modelcontextprotocol/sdk
```

Set your provider key the same way the CLI expects (e.g.
`export ANTHROPIC_API_KEY=…`).

## 20-line quickstart

```ts
// quickstart.ts — node 20+ / bun / deno
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const transport = new StdioClientTransport({
  command: "maverick",
  args: ["mcp"],
});

const client = new Client({ name: "ts-quickstart", version: "0.1.0" }, {
  capabilities: {},
});
await client.connect(transport);

const tools = await client.listTools();
console.log("Maverick exposes", tools.tools.length, "tools");

// Start a goal. maverick_start runs the swarm and returns the final
// answer (it's long-running — give it a real budget/timeout).
const result = await client.callTool({
  name: "maverick_start",
  arguments: {
    title: "Say hello from TypeScript",
    description: "Reply with a one-line greeting.",
    max_dollars: 0.25,
  },
});
console.log(result.content);

await client.close();
```

Run with `npx tsx quickstart.ts` (or `bun run quickstart.ts`,
`deno run --allow-all quickstart.ts`).

You should see the tool list (8 tools), then the swarm's final answer.

## What works

The MCP server exposes a small, stable control surface — **8
`maverick_*` tools**, not the ~70 in-kernel tools. You drive the swarm;
the kernel runs the tools internally.

- `maverick_start` `{title, description?, max_dollars?, max_wall_seconds?, max_depth?}`
  — start a goal; returns the final answer.
- `maverick_status` — list recent goals + open questions.
- `maverick_resume` `{goal_id}` — resume a paused goal.
- `maverick_answer` `{question_id, answer}` — answer a queued question.
- `maverick_skill_install` `{source}` / `maverick_skills_list`.
- `maverick_fact_set` `{key, value}` / `maverick_facts_get`.

The ~70 in-kernel tools (web search, repo map, editor, Slack, S3, …)
are **not** individually exposed over MCP — the swarm decides which to
use while running a goal.

## What's gated

- The 50+ third-party tools (Slack, GitHub Actions, S3, Salesforce,
  …) read credentials from the same env / `~/.maverick/config.toml`
  the CLI uses. The TS client doesn't pass credentials — the kernel
  reads them once.
- Some tools require optional extras (`maverick-agent[redis]`,
  `[s3]`, etc.). Install only what you use.

## Limits — please respect them

- **Multi-agent orchestration stays in Python.** Don't try to
  reimplement the orchestrator-proposer-verifier topology in TS;
  spawn goals and let Maverick run the swarm. The TS process is the
  *client*, not a worker.
- **Sandbox / kernel features are Python-side.** Backends
  (firecracker, k8s, devcontainer) live in `maverick-core` and are
  not part of the wire protocol.
- **The MCP server is for cross-language clients, not for tunneling
  Maverick over the public internet.** Pair with your own auth +
  TLS layer if you go remote (see `packages/maverick-mcp/http_transport.py`).

## Why no `npm install @maverick/core`?

See [docs/ROADMAP.md → "Language Bindings — Council Decision"](../ROADMAP.md).
Short version: thin API clients port well; opinionated frameworks
don't. We don't intend to port a 1600-test, 7-sandbox, multi-agent
kernel. We intend to make sure every MCP-speaking language can drive
that kernel without giving up features.

## See also

- [Go client quickstart](./go-quickstart.md)
- [Rust client quickstart](./rust-quickstart.md)
- [C# / .NET client quickstart](./csharp-quickstart.md)
- [Java / JVM client quickstart](./java-quickstart.md)
- `packages/maverick-mcp/README.md` — what tools are exposed + how
  to wire into Claude Code / Cursor / Continue / Zed
