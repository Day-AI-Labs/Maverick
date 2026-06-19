# C# / .NET MCP client example

The runnable version of [`docs/clients/csharp-quickstart.md`](../../../docs/clients/csharp-quickstart.md),
and the CI smoke test for Lightwork's cross-language MCP surface.

`Program.cs` spawns `maverick mcp` (stdio JSON-RPC) and runs the documented
client flow — `initialize` → `tools/list` → a no-LLM `tools/call`
(`maverick_facts_get`). It does **not** call `maverick_start` (that runs the
swarm and needs a provider key + budget), so it's safe to run unattended.

## Run it

```bash
pip install maverick-agent maverick-mcp-server   # provides the `maverick` CLI
dotnet run
```

Expected output ends with:

```
Lightwork exposes 8 tools: maverick_answer, maverick_fact_set, ...
maverick_facts_get round-trip OK
OK: C# client drove Lightwork over MCP end-to-end
```

CI runs exactly this on every change to the MCP server or the clients (see
`.github/workflows/mcp-client-csharp.yml`), so a break in `maverick mcp` or the
documented tool surface fails the build.

The official C# MCP SDK is the [`ModelContextProtocol`](https://www.nuget.org/packages/ModelContextProtocol)
NuGet package, pinned in `Lightwork.McpClient.Example.csproj` for reproducible CI.
