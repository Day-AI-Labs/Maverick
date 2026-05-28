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
pip install maverick-agent maverick-mcp   # in any venv on the same machine
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

const result = await client.callTool({
  name: "maverick_status",
  arguments: {},
});
console.log(result.content);

await client.close();
```

Run with `npx tsx quickstart.ts` (or `bun run quickstart.ts`,
`deno run --allow-all quickstart.ts`).

You should see the tool list and a status response (for a fresh install: "no goals yet").

## What works

- The MCP server currently exposes the `maverick_*` tools documented in
  `packages/maverick-mcp/README.md` (for example `maverick_start`,
  `maverick_status`, `maverick_resume`, and `maverick_answer`).
- Long-running goals: start with `maverick_start`, then check progress with
  `maverick_status` and resume/answer as needed.
- Tool names are strict; call `listTools` first and use one of the returned
  names exactly as shown.

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
- `packages/maverick-mcp/README.md` — what tools are exposed + how
  to wire into Claude Code / Cursor / Continue / Zed
