# Java / JVM MCP client example

The runnable version of [`docs/clients/java-quickstart.md`](../../../docs/clients/java-quickstart.md),
and the CI smoke test for Lightwork's JVM cross-language MCP surface.

`Client.java` spawns `maverick mcp` (stdio JSON-RPC) and runs the documented
client flow — `initialize` → `tools/list` → a no-LLM `tools/call`
(`maverick_facts_get`). It does **not** call `maverick_start` (that runs the
swarm and needs a provider key + budget), so it's safe to run unattended.

## Run it

```bash
pip install maverick-agent maverick-mcp-server   # provides the `maverick` CLI
mvn -q compile exec:java
```

Requires JDK 17+ (CI uses Temurin 21) and Maven 3.9+.

Expected output ends with:

```
Lightwork exposes 8 tools: maverick_answer, maverick_fact_set, ...
maverick_facts_get round-trip OK
OK: Java client drove Lightwork over MCP end-to-end
```

CI runs exactly this on every change to the MCP server or the clients (see
`.github/workflows/mcp-client-java.yml`), so a break in `maverick mcp` or the
documented tool surface fails the build.

## SDK

Uses the official [Java MCP SDK](https://github.com/modelcontextprotocol/java-sdk)
(`io.modelcontextprotocol.sdk:mcp`), pinned in `pom.xml` for reproducible CI.
