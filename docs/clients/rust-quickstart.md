# Maverick from Rust

Drive a locally running Maverick swarm from Rust over the
[Model Context Protocol](https://modelcontextprotocol.io/). Same
contract every IDE-side MCP client uses — you talk to `maverick mcp`
over stdio JSON-RPC.

We don't ship a separate `maverick-rs` crate; you talk to the Python
kernel via the standard Rust MCP SDK.

## Prereqs

```bash
pip install maverick-agent maverick-mcp-server
cargo add mcp-sdk    # community crate; pin to a published version
cargo add tokio --features full
cargo add serde_json
```

Set `ANTHROPIC_API_KEY` (or whichever provider key the kernel needs).

## Quickstart

```rust
// quickstart.rs
use mcp_sdk::{client::Client, transport::StdioTransport};
use serde_json::json;
use tokio::process::Command;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Spawn `maverick mcp` as a child; SDK wires stdio JSON-RPC.
    let mut cmd = Command::new("maverick");
    cmd.arg("mcp");
    let transport = StdioTransport::from_command(cmd).await?;
    let mut client = Client::new("rust-quickstart", "0.1.0");
    client.connect(transport).await?;

    let tools = client.list_tools().await?;
    println!("Maverick exposes {} tools", tools.tools.len());

    // maverick_start runs the swarm and returns the final answer.
    let out = client
        .call_tool("maverick_start", json!({ "title": "Say hello from Rust", "max_dollars": 0.25 }))
        .await?;
    println!("{}", out.text());

    client.close().await?;
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

The Rust MCP SDK ecosystem is still consolidating; pin the crate
version + audit the dep, or implement the wire protocol by hand —
the spec is small enough to fit in ~150 lines of Rust.

## See also

- [TypeScript client quickstart](./typescript-quickstart.md)
- [Go client quickstart](./go-quickstart.md)
