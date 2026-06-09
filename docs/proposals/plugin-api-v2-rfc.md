# RFC: Plugin API v2

**Status:** RFC (open for comment). Additive over the current plugin system;
v1 plugins keep loading for the full deprecation window.

## Motivation

The v1 plugin system loads Python entry points in-process and lets them register
tools, hooks, channels, and sandboxes. Two limits motivate v2:

1. **Isolation.** An in-process plugin runs with the kernel's full authority.
   Operators want to grant a plugin a *capability budget* and have the kernel
   enforce it, the same way tools are ACL-gated.
2. **Language.** Useful integrations exist outside Python. v2 defines an
   out-of-process plugin host so a plugin can be any process that speaks the
   protocol (the gRPC plugin host on the roadmap), without porting the kernel.

## Design

### Manifest

Every v2 plugin ships a `maverick_plugin.toml`:

```toml
[plugin]
name = "acme-widgets"
version = "1.2.0"
api = 2
entrypoint = "acme_widgets:plugin"     # in-process
# or: host = "grpc"; command = ["./acme-plugin"]   # out-of-process

[capabilities]
requires = ["tool:http_fetch", "net:egress"]   # declared, enforced
```

The kernel reads `requires`, intersects it with the operator's grant (CLAUDE.md
rule #5 — a config knob gates every capability), and refuses to load a plugin
that demands more than it's granted, with a clear message.

### Surfaces a plugin can register

`tools`, `hooks` (`PreToolUse`/`PostToolUse`/`UserPromptSubmit`), `channels`,
`sandboxes` — same four as v1, but each registration is tagged with the
plugin's identity so the audit log and `maverick whoami` can attribute actions.

### Out-of-process host

The gRPC plugin host exposes the same registration RPCs; a plugin process
advertises its tools at handshake and the kernel proxies calls to it, applying
the shield + capability checks at the boundary exactly as for an MCP server.
This reuses the existing MCP-style chokepoint rather than inventing a new one.

### Version pinning

A `maverick-plugins.lock` (see the shipped `plugin_lockfile` tool) records each
plugin's `name == version == sha256`; `maverick plugins verify` fails on drift.

## Compatibility

`api = 1` plugins load unchanged. `api = 2` unlocks capability enforcement and
the out-of-process host. The `[plugins]` enable/disable wizard step gains a
per-plugin capability-grant prompt.

## Open questions

- Hot reload (on the roadmap) interacts with out-of-process hosts — restart the
  child vs signal it? Leaning: protocol `Reload` RPC, fall back to restart.
- Do we sign plugin manifests now (plugin signing CA is later) or only lock-pin?
  Leaning: lock-pin in v2, signing CA as a follow-up.
