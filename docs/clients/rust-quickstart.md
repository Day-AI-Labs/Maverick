# Maverick from Rust

Drive a locally running Maverick swarm from Rust over the
[Model Context Protocol](https://modelcontextprotocol.io/). Same
contract every IDE-side MCP client uses — you talk to `maverick mcp`
over stdio JSON-RPC.

We don't ship a separate `maverick-rs` crate; you talk to the Python
kernel via the official [Rust MCP SDK](https://github.com/modelcontextprotocol/rust-sdk)
(the `rmcp` crate).

## Prereqs

```bash
pip install maverick-agent maverick-mcp-server
# Official Rust MCP SDK; pin a published version for reproducible builds.
# The client role and the child-process stdio transport are not on by default.
cargo add rmcp@1.7.0 --features client,transport-child-process
cargo add tokio --features macros,rt-multi-thread,process,io-util
cargo add serde_json
cargo add anyhow
```

Set `ANTHROPIC_API_KEY` (or whichever provider key the kernel needs).

## Quickstart

```rust
// src/main.rs
use anyhow::Result;
use rmcp::{
    model::CallToolRequestParams,
    object,
    transport::{ConfigureCommandExt, TokioChildProcess},
    ServiceExt,
};
use tokio::process::Command;

#[tokio::main]
async fn main() -> Result<()> {
    // Spawn `maverick mcp` as a child process; rmcp wires up stdio JSON-RPC and
    // performs the MCP initialize handshake. `()` is the (no-op) client handler.
    let client = ()
        .serve(TokioChildProcess::new(Command::new("maverick").configure(
            |cmd| {
                cmd.arg("mcp");
            },
        ))?)
        .await?;

    let tools = client.list_all_tools().await?;
    println!("Maverick exposes {} tools", tools.len());

    // maverick_start runs the swarm and returns the final answer (long-running).
    let res = client
        .call_tool(
            CallToolRequestParams::new("maverick_start")
                .with_arguments(object!({ "title": "Say hello from Rust", "max_dollars": 0.25 })),
        )
        .await?;
    for content in &res.content {
        if let Some(text) = content.as_text() {
            println!("{}", text.text);
        }
    }

    client.cancel().await?;
    Ok(())
}
```

```bash
cargo run --release
```

## Why no `maverick-rs` crate?

Same reason there's no `maverick-go` or `maverick-ts`: porting a
1600-test, 7-sandbox, multi-agent kernel to Rust is a permanent
team-headcount tax with no consumer-reach payoff. See
[docs/ROADMAP.md → Language Bindings — Council Decision](../ROADMAP.md).

Rust is the natural language for *embedders* — CLI tools and
infrastructure agents that need a small binary footprint and don't
want to ship a Python interpreter. The right Rust unit is a thin
**RPC client** that drives the Python kernel, not a re-implementation.

## SDK status

`rmcp` is the official Rust MCP SDK from the Model Context Protocol
project. It's async (tokio) and ships a child-process stdio transport
(`TokioChildProcess`) plus the client role behind feature flags. Pin a
specific version and enable only the features you need; if the API
drifts across releases, the wire protocol it speaks does not.

## See also

- [Runnable example + CI smoke](../../examples/clients/rust/) — the executable
  version of this quickstart, run in CI against a live `maverick mcp`.
- [TypeScript client quickstart](./typescript-quickstart.md)
- [Go client quickstart](./go-quickstart.md)
- [C# / .NET client quickstart](./csharp-quickstart.md)
- [docs/ROADMAP.md → Language Bindings — Council Decision](../ROADMAP.md)
