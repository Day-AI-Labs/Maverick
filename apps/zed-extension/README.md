# maverick-zed-extension

Drive the [Lightwork](https://github.com/Day-AI-Labs/maverick) agent runtime
from the [Zed](https://zed.dev) editor. Two surfaces:

1. **Assistant context server (MCP).** The extension registers
   `maverick mcp` — Lightwork's official MCP server
   (`packages/maverick-mcp`, stdio transport) — as a Zed context server, so
   Zed's assistant can start goals, check status, and read results through
   MCP tools.
2. **Terminal tasks.** `tasks/maverick.json` ships ready-made Zed tasks for
   the CLI verbs that actually exist in `maverick/cli.py`: `status`,
   `monitor`, `runs`, `budget`, `doctor`, `start`, `halt`, `unhalt`. Copy
   them into `.zed/tasks.json` (project) or `~/.config/zed/tasks.json`
   (global) and run via `task: spawn`.

## Why tasks and not slash commands for the CLI verbs

Zed extensions are Rust compiled to **WASM running in a WASI sandbox**: the
extension code cannot spawn processes, so a slash command implemented in
`src/lib.rs` cannot shell out to `maverick status`. The only extension hook
that results in a real local process is the context-server hook, where the
extension returns a command **and Zed spawns it** — that is exactly what
`src/lib.rs` does with `maverick mcp`. Everything terminal-shaped is
delivered as tasks, which Zed runs in its own terminal. This is the honest
split; anything else would be pretending the sandbox isn't there.

## Prerequisites

- The `maverick` CLI installed and on PATH, with the MCP server package:
  `pip install maverick-agent maverick-mcp-server` (or the installers under
  `apps/` / `deploy/`).
- Zed (stable) with assistant/context-server support.

## Building / installing as a dev extension

Requires **Rust** with the `wasm32-wasip1` target and the
**`zed_extension_api`** crate (pulled by Cargo):

```bash
rustup target add wasm32-wasip1
# Zed builds the extension itself when you install it as a dev extension:
# zed: Extensions -> Install Dev Extension -> select apps/zed-extension/
```

Zed compiles `src/lib.rs` against the WIT world for the pinned
`zed_extension_api` version when installing a dev extension; you do not run
`cargo build` by hand for normal installs.

## Status — honest

- **Not compiled or run here.** This environment has neither the Zed SDK
  nor a `wasm32-wasip1` toolchain, so the extension was authored against the
  documented `zed_extension_api` 0.2.x surface
  (`Extension::context_server_command`) but has not been built or exercised
  in Zed. Same posture as the other editor scaffolds in this repo: treat the
  first dev-extension install as the smoke test.
- The `zed_extension_api` pin in `Cargo.toml` may need a bump to match the
  Zed release you install into; the API is versioned and Zed only loads
  extensions built against versions it supports.
- The extension does not install the Lightwork CLI; it assumes `maverick`
  resolves on PATH and surfaces Zed's own error if it does not.
