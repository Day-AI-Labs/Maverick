# Lightwork from Java / JVM

Drive a locally running Lightwork swarm from a JVM app (Java, Kotlin,
Scala) over the [Model Context Protocol](https://modelcontextprotocol.io/).
Same contract every IDE-side MCP client uses — you talk to `maverick mcp`
over stdio JSON-RPC.

This is the official cross-language surface. We don't ship a separate
`maverick-jvm` port; we ship one Python kernel and you talk to it from
any language an MCP SDK exists in.

## Prereqs

```bash
pip install maverick-agent maverick-mcp-server   # in any venv on the same machine
```

Add the official [Java MCP SDK](https://github.com/modelcontextprotocol/java-sdk)
(`io.modelcontextprotocol.sdk:mcp`) to your build — pin the version for
reproducibility:

```xml
<dependency>
  <groupId>io.modelcontextprotocol.sdk</groupId>
  <artifactId>mcp</artifactId>
  <version>1.1.3</version>
</dependency>
```

(Gradle: `implementation("io.modelcontextprotocol.sdk:mcp:1.1.3")`.)
Requires JDK 17+. Set your provider key the same way the CLI expects
(e.g. `export ANTHROPIC_API_KEY=…`).

## Quickstart

```java
// Client.java — JDK 17+
import io.modelcontextprotocol.client.McpClient;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.client.transport.ServerParameters;
import io.modelcontextprotocol.client.transport.StdioClientTransport;
import io.modelcontextprotocol.json.McpJsonMapper;
import io.modelcontextprotocol.json.McpJsonMapperSupplier;
import io.modelcontextprotocol.spec.McpSchema.CallToolRequest;
import io.modelcontextprotocol.spec.McpSchema.ListToolsResult;
import java.util.Map;
import java.util.ServiceLoader;

public class Client {
    public static void main(String[] args) {
        // The default JSON mapper ships in mcp-json-jackson3 (SPI-discovered).
        McpJsonMapper json = ServiceLoader.load(McpJsonMapperSupplier.class)
                .findFirst().orElseThrow().get();

        // Spawn `maverick mcp` as a subprocess; the SDK manages its stdio.
        ServerParameters server = ServerParameters.builder("maverick").args("mcp").build();
        McpSyncClient client = McpClient.sync(new StdioClientTransport(server, json)).build();

        client.initialize(); // MCP initialize handshake

        ListToolsResult tools = client.listTools();
        System.out.println("Lightwork exposes " + tools.tools().size() + " tools");

        // maverick_start runs the swarm and returns the final answer (long-running).
        var res = client.callTool(new CallToolRequest(
                "maverick_start", Map.of("title", "Say hello from Java", "max_dollars", 0.25)));
        System.out.println(res.content());

        client.closeGracefully();
    }
}
```

```bash
mvn -q compile exec:java
```

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

## Typed results

Besides the human-readable `res.content()` text, every tool returns
`res.structuredContent()` — typed JSON matching the tool's `outputSchema`
(`maverick_facts_get` → `{ "facts": {…} }`), deserialized to a `Map`:

```java
if (res.structuredContent() instanceof Map<?, ?> structured) {
    Object facts = structured.get("facts");
}
```

The shapes are identical across languages — see the
[TypeScript quickstart](./typescript-quickstart.md) for the full
per-tool table.

## What's gated

- The 50+ third-party tools (Slack, GitHub Actions, S3, Salesforce,
  …) read credentials from the same env / `~/.maverick/config.toml`
  the CLI uses. The JVM client doesn't pass credentials — the kernel
  reads them once.
- Some tools require optional extras (`maverick-agent[redis]`,
  `[s3]`, etc.). Install only what you use.

## Limits — please respect them

- **Multi-agent orchestration stays in Python.** Don't try to
  reimplement the orchestrator-proposer-verifier topology in Java;
  spawn goals and let Lightwork run the swarm. The JVM process is the
  *client*, not a worker.
- **Sandbox / kernel features are Python-side.** Backends
  (firecracker, k8s, devcontainer) live in `maverick-core` and are
  not part of the wire protocol.
- **The MCP server is for cross-language clients, not for tunneling
  Lightwork over the public internet.** Pair with your own auth +
  TLS layer if you go remote (see `packages/maverick-mcp/http_transport.py`).

## SDK status

The Java MCP SDK is the official SDK, maintained in collaboration with
Spring AI. Pin the version (this doc uses `1.1.3`) and audit the
dependency. If the SDK API drifts, the wire protocol it speaks does
not — you can also implement the JSON-RPC handshake by hand.

## Why no `maven install maverick-core`?

See [docs/ROADMAP.md → "Language Bindings — Council Decision"](../ROADMAP.md).
Java / Kotlin is council target #5 (JVM enterprise + Android). Short
version: thin API clients port well; opinionated frameworks don't. We
don't intend to port a 1600-test, 7-sandbox, multi-agent kernel. We
intend to make sure every MCP-speaking language can drive that kernel
without giving up features.

## See also

- [Runnable example + CI smoke](../../examples/clients/java/) — the executable
  version of this quickstart, run in CI against a live `maverick mcp`.
- [TypeScript client quickstart](./typescript-quickstart.md)
- [Go client quickstart](./go-quickstart.md)
- [Rust client quickstart](./rust-quickstart.md)
- [docs/ROADMAP.md → Language Bindings — Council Decision](../ROADMAP.md)
