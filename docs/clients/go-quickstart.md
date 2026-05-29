# Maverick from Go

Drive a locally running Maverick swarm from Go over the
[Model Context Protocol](https://modelcontextprotocol.io/). Same
contract every IDE-side MCP client uses — you talk to `maverick mcp`
over stdio JSON-RPC.

We don't ship a separate `maverick-go` package; you talk to the
Python kernel via the standard MCP SDK for Go.

## Prereqs

```bash
pip install maverick-agent maverick-mcp-server
go get github.com/modelcontextprotocol/go-sdk@latest   # community SDK; pin to a tag
```

Set `ANTHROPIC_API_KEY` (or whichever provider key the kernel needs).

## Quickstart

```go
// quickstart.go
package main

import (
    "context"
    "encoding/json"
    "fmt"
    "log"
    "os/exec"

    "github.com/modelcontextprotocol/go-sdk/client"
    "github.com/modelcontextprotocol/go-sdk/transport"
)

func main() {
    ctx := context.Background()

    // Start `maverick mcp` as a subprocess; the SDK manages stdio.
    cmd := exec.CommandContext(ctx, "maverick", "mcp")
    tr, err := transport.NewStdioFromCmd(cmd)
    if err != nil {
        log.Fatal(err)
    }

    c, err := client.New(ctx, tr, client.Info{Name: "go-quickstart", Version: "0.1.0"})
    if err != nil {
        log.Fatal(err)
    }
    defer c.Close()

    tools, err := c.ListTools(ctx)
    if err != nil {
        log.Fatal(err)
    }
    fmt.Printf("Maverick exposes %d tools\n", len(tools.Tools))

    // maverick_start runs the swarm and returns the final answer.
    out, err := c.CallTool(ctx, client.CallToolParams{
        Name:      "maverick_start",
        Arguments: json.RawMessage(`{"title": "Say hello from Go", "max_dollars": 0.25}`),
    })
    if err != nil {
        log.Fatal(err)
    }
    fmt.Println(string(out.Content))
}
```

```bash
go run quickstart.go
```

## SDK status

The Go MCP SDK is community-maintained; pin a specific tag and audit
the dependency. If the SDK API drifts, the wire protocol it speaks
does not — you can also implement the JSON-RPC handshake by hand in
~80 lines of Go.

## See also

- [TypeScript client quickstart](./typescript-quickstart.md)
- [Rust client quickstart](./rust-quickstart.md)
- [docs/ROADMAP.md → Language Bindings — Council Decision](../ROADMAP.md)
