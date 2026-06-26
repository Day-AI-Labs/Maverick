# Design Spec: MCP Server Registry

**Status:** Shipped (discovery + install + config write + CLI; OAuth deferred) · **Roadmap ref:** [`ROADMAP.md`](../ROADMAP.md) → "Current state & gap analysis" (B2) · **Related:** [`catalog.md`](./catalog.md), [`skill-index.md`](./skill-index.md) · **Date:** June 2026

## 1. Problem

Lightwork can *consume* external MCP servers once they're in
`[mcp_servers.<name>]` (stdio via `MCPClient`, remote HTTP via
`StreamableHttpMCPClient`). What was missing (roadmap B2) is **discovery +
install**: a user shouldn't have to hand-write a server's command/args/url. A
registry gives `maverick mcp-registry browse` / `add <name>` so servers install
by name, the same way `maverick skill add` works for skills.

OAuth 2.1 (the other half of B2) is out of scope here — it needs real accounts
to validate. Static-bearer remote servers already work via `auth_token`.

## 2. The registry is a federated catalog

A registry is a self-hostable JSON index served at `<base>/mcp/index.json`,
reusing the generic [`catalog.py`](./catalog.md) infra (fetch + 6h cache +
SSRF-guarded `guarded_urlopen` + https-only + stale-serve + multi-index merge,
earlier index wins). Point `[mcp_registries] indexes` at your own base(s);
default is the built-in awesome-maverick index (`DEFAULT_MCP_REGISTRIES`).

```toml
# ~/.maverick/config.toml — only needed to override the default
[mcp_registries]
indexes = ["https://registry.example.com/catalog", "https://internal.acme/catalog"]
```

## 3. Index schema (`<base>/mcp/index.json`)

```json
{
  "schema_version": 1,
  "kind": "mcp",
  "entries": [
    {
      "name": "github",
      "version": "1.0.0",
      "summary": "GitHub MCP server (issues, PRs, code search).",
      "author": "modelcontextprotocol",
      "verified": true,
      "spec": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
        "pin_sha256": "<optional: hash of the resolved executable>"
      }
    },
    {
      "name": "acme-remote",
      "version": "2.0.0",
      "summary": "Acme's hosted MCP server.",
      "spec": {"url": "https://mcp.acme.com/sse", "headers": {"X-Tenant": "acme"}}
    }
  ]
}
```

**Why the spec is inline (vs. skills' fetched `SKILL.md` + `sha256`).** An MCP
server's installable artifact is *configuration*, not a content file. There's
nothing to fetch and hash — the actual server binary is resolved at spawn time
(`npx`/`pip`/a URL). So the entry carries the `spec` (a `[mcp_servers.<name>]`
dict) directly, and `source`/`sha256` are optional. `CatalogEntry` gained an
optional `spec: dict` field for exactly this; content kinds (skills, personas)
leave it empty and keep fetching `source`.

## 4. Trust model

- The index is **curated** (a PR against the registry repo adds an entry) and
  served over **https** through the SSRF guard.
- `verified` is **self-asserted by the index** and is NOT a trust signal (the
  index host is unauthenticated), exactly as in `catalog.md`.
- The real supply-chain defense for an MCP server is **`pin_sha256`** in the
  spec: `MCPClient.start()` hashes the resolved executable and refuses to spawn
  on mismatch (the CVE-2026-30615 STDIO-trifecta class). A registry curator
  SHOULD pin `pin_sha256` for stdio servers.
- On install, the spec is validated through `MCPServerSpec.from_config` — the
  same subprocess-injection / shell-metacharacter / url-scheme checks the kernel
  applies to hand-written config — so a hostile entry (`command` with a shell
  metacharacter, a non-http url) is rejected, not written.
- Installing never executes anything: it writes config. Code runs only when the
  agent later spawns the server, behind `pin_sha256`.

## 5. Code

`packages/maverick-core/maverick/mcp_registry.py`:

- `load_mcp_registry()` / `resolve_mcp(name)` → `catalog.load_catalog("mcp", …)`
  with the `[mcp_registries] indexes`.
- `spec_from_entry(entry)` → a validated `MCPServerSpec` from `entry.spec`.
- `install_mcp_from_registry(name)` → resolve + validate, returns the spec (pure;
  the caller writes config, so a preview/dry-run is possible).
- `add_mcp_server_to_config(name, spec_dict)` / `remove_mcp_server_from_config(name)`
  — dependency-free TOML mutation (append the one table on add; text-scan removal
  on remove) so the rest of a hand-edited `config.toml` — comments, ordering,
  unrelated tables — is preserved. (`tomli_w` is not a dependency; Python ships no
  stdlib TOML writer.)

`MCPServerSpec.to_dict()` (in `mcp_client.py`) is the inverse of `from_config`,
used to serialize a resolved spec into config.

## 6. CLI

`maverick mcp-registry` (a group distinct from `maverick mcp`, which starts
Lightwork's *own* server):

- `browse` — list registry servers (name, version, transport, verified badge).
- `add <name>` — resolve + validate + write `[mcp_servers.<name>]`; loads on the
  next run. Refuses to overwrite an existing entry.
- `remove <name>` — drop the table from config.
- `list` — show the MCP servers currently configured (via the kernel's loader).

## 7. Config knob + wizard (CLAUDE.md #5/#6)

- Knob: `[mcp_registries] indexes` (list of base URLs). Discovery works with **no
  config** (built-in default), so the knob is only for custom/self-hosted
  registries.
- Wizard: `write_config` emits `[mcp_registries]` when custom indexes are
  supplied, so the installer can write the knob; it's omitted by default to keep
  the config minimal.

## 8. Deferred

- **OAuth 2.1** for remote servers (the other half of B2) — needs real accounts.
- **Signed registry entries** (Ed25519, mirroring the skills `trusted_pubkeys`
  path) — the inline-spec + `pin_sha256` model already gives integrity for the
  high-risk (stdio) case; entry signing is a future hardening for authenticity.
- **`install_count` / ranking** — the schema carries the field; surfacing it is
  cosmetic.
