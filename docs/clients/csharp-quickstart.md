# Lightwork from C# / .NET

Drive a locally running Lightwork swarm from a .NET app over the
[Model Context Protocol](https://modelcontextprotocol.io/). Same
contract every IDE-side MCP client uses — you talk to `maverick mcp`
over stdio JSON-RPC.

This is the official cross-language surface. We don't ship a separate
`Lightwork.Core` NuGet package; we ship one Python kernel and you talk to
it from any language an MCP SDK exists in.

## Prereqs

```bash
pip install maverick-agent maverick-mcp-server   # in any venv on the same machine
dotnet add package ModelContextProtocol           # official C# MCP SDK
```

Target a current LTS (net8.0 or newer). Set your provider key the same
way the CLI expects (e.g. `export ANTHROPIC_API_KEY=…`).

## 20-line quickstart

```csharp
// Program.cs — net8.0+
using ModelContextProtocol.Client;

// Start `maverick mcp` as a subprocess; the SDK manages stdio JSON-RPC.
var transport = new StdioClientTransport(new()
{
    Name = "csharp-quickstart",
    Command = "maverick",
    Arguments = ["mcp"],
});

// CreateAsync performs the MCP initialize handshake.
await using var client = await McpClient.CreateAsync(transport);

var tools = await client.ListToolsAsync();
Console.WriteLine($"Lightwork exposes {tools.Count} tools");

// Start a goal. maverick_start runs the swarm and returns the final
// answer (it's long-running — give it a real budget/timeout).
var result = await client.CallToolAsync("maverick_start", new Dictionary<string, object?>
{
    ["title"] = "Say hello from C#",
    ["description"] = "Reply with a one-line greeting.",
    ["max_dollars"] = 0.25,
});
foreach (var block in result.Content)
{
    Console.WriteLine(block);
}
```

Run with `dotnet run`.

You should see the tool list (10 tools), then the swarm's final answer.

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
- `maverick_fleet_ingest` `{agent_id, vendor, kind, goal_text}` — deposit an
  external agent's experience into governed fleet memory (roster-gated).
- `maverick_fleet_recall` `{agent_id, vendor, query}` — governed, audited
  memory read for an external fleet agent.

The ~70 in-kernel tools (web search, repo map, editor, Slack, S3, …)
are **not** individually exposed over MCP — the swarm decides which to
use while running a goal.

## What's gated

- The 50+ third-party tools (Slack, GitHub Actions, S3, Salesforce,
  …) read credentials from the same env / `~/.maverick/config.toml`
  the CLI uses. The C# client doesn't pass credentials — the kernel
  reads them once.
- Some tools require optional extras (`maverick-agent[redis]`,
  `[s3]`, etc.). Install only what you use.

## Limits — please respect them

- **Multi-agent orchestration stays in Python.** Don't try to
  reimplement the orchestrator-proposer-verifier topology in C#;
  spawn goals and let Lightwork run the swarm. The .NET process is the
  *client*, not a worker.
- **Sandbox / kernel features are Python-side.** Backends
  (firecracker, k8s, devcontainer) live in `maverick-core` and are
  not part of the wire protocol.
- **The MCP server is for cross-language clients, not for tunneling
  Lightwork over the public internet.** Pair with your own auth +
  TLS layer if you go remote (see `packages/maverick-mcp/http_transport.py`).

## Why no `Lightwork.Core` NuGet package?

See [docs/ROADMAP.md → "Language Bindings — Council Decision"](../ROADMAP.md).
Short version: thin API clients port well; opinionated frameworks
don't. We don't intend to port a 1600-test, 7-sandbox, multi-agent
kernel. We intend to make sure every MCP-speaking language can drive
that kernel without giving up features. .NET is council target #4
(Microsoft / Unity / game-dev; .NET Aspire and Semantic Kernel users
want a turnkey agent backend).

## SDK status

The C# MCP SDK is the official
[`ModelContextProtocol`](https://www.nuget.org/packages/ModelContextProtocol)
package (`github.com/modelcontextprotocol/csharp-sdk`). Pin a specific
version and audit the dependency. If the SDK API drifts, the wire
protocol it speaks does not — you can also implement the JSON-RPC
handshake by hand.

## See also

- [Runnable example + CI smoke](../../examples/clients/csharp/) — the executable
  version of this quickstart, run in CI against a live `maverick mcp`.
- [TypeScript client quickstart](./typescript-quickstart.md)
- [Go client quickstart](./go-quickstart.md)
- [Rust client quickstart](./rust-quickstart.md)
- `packages/maverick-mcp/README.md` — what tools are exposed + how
  to wire into Claude Code / Cursor / Continue / Zed
