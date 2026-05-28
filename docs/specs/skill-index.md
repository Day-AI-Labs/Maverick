# Skill marketplace index (spec)

A static JSON manifest hosted at `https://skills.maverick.dev/index.json`
that the `maverick skills search` / `maverick skills install` flow
reads. Federated: users can configure additional index URLs in
`~/.maverick/config.toml` under `[skills.indexes]`.

This doc is the **schema spec**. Tooling on the publisher side and the
client side must agree on this shape; bumps are versioned via the
top-level `v` field.

## Top-level shape (v1)

```json
{
  "v": 1,
  "generated_at": "2026-04-01T12:00:00Z",
  "source_repo": "https://github.com/cdayAI/awesome-maverick-skills",
  "skills": [
    {
      "name": "pr-review",
      "version": "1.0.0",
      "summary": "Review a PR diff for logic bugs and missing edge cases.",
      "description": "Longer markdown allowed here.",
      "publisher": {
        "github": "alice",
        "email": "alice@example.com",
        "trusted": false
      },
      "license": "MIT",
      "source": "gh:alice/maverick-skill-pr-review@v1.0.0",
      "sha256": "abc123...",
      "signature": "ed25519:base64sig",
      "triggers": ["pr review", "code review", "/review"],
      "tags": ["code", "review", "github"],
      "stars": 42,
      "install_count": 137,
      "min_maverick_api": "1",
      "permissions": {
        "network": false,
        "fs_write": true,
        "subprocess": false,
        "sensitive_envs": []
      },
      "verified": false,
      "last_audit": "2026-03-15T10:00:00Z"
    }
  ]
}
```

## Required fields

Each skill entry MUST have:

- `name` — kebab-case, globally unique within the index
- `version` — semver
- `summary` — ≤120 char one-liner
- `source` — `gh:<owner>/<repo>[@<ref>]` install URL
- `sha256` — hash of the resolved skill source bundle (tar.gz of the repo at ref)
- `triggers` — at least one match string for the agent's trigger heuristic

## Optional fields

- `signature` — Ed25519 signature of `sha256` by the publisher's verified key.
  Clients with `[skills] require_signed = true` ignore unsigned skills.
- `publisher.trusted` — only set true by the index maintainer (not the
  publisher). Used to show the trusted-publisher badge in the CLI.
- `permissions` — declared by the publisher per `maverick.plugin_manifest`;
  the index just echoes it.

## Client behavior

`maverick skills search <q>`:

1. Fetch each configured index URL (default: `skills.maverick.dev/index.json`).
2. Filter by substring match on `name`, `summary`, `tags`, `triggers`.
3. Sort: trusted publisher first, then by stars desc, then install_count desc.
4. Display: `name  v<version>  ✓<trusted-badge>  <summary>  (<stars>★)`

`maverick skills install <name>[@<version>]`:

1. Resolve the entry from the index.
2. Verify `signature` if present and `require_signed = true`.
3. Fetch the source bundle via `gh:` URL.
4. Verify the bundle's sha256 matches the index entry.
5. Inspect the manifest for permission/api compatibility.
6. Prompt the user (unless `--yes`) summarizing permissions + publisher.
7. Install to `~/.maverick/skills/<name>/`.

## Federation

Users add custom indexes:

```toml
[skills]
indexes = [
  "https://skills.maverick.dev/index.json",
  "https://my-internal-index.corp/skills.json",
]
require_signed = false
```

The first index URL wins on name collision. Skills from internal indexes
get a tiny `<index-host>` annotation in CLI output so users can tell
provenance at a glance.

## Publishing flow

A skill author publishes by:

1. Writing the skill as a GitHub repo with a top-level `maverick-skill.toml`
   matching `maverick.plugin_manifest` schema.
2. Tagging a release.
3. Opening a PR to `awesome-maverick-skills` adding their entry to
   `_data/skills.yaml`.
4. CI on the awesome-list repo regenerates `index.json` and publishes.

Signed publication is a Q2 2026 roadmap item; until then, `signature`
is optional and `require_signed` defaults to false.

## Versioning policy

- `v: 1` — current. Additive changes (new optional fields) bump no
  versions. Removing required fields or breaking field semantics bumps
  to `v: 2` and clients must handle both during a 6-month overlap.
- Old client + new index → ignore unknown fields silently.
- New client + old index → handle missing optional fields gracefully.

## Trust model

This index is **discovery, not authority**. Skills install arbitrary
Python code into the user's home directory. Trust signals:

1. `verified` (audit pass) — manually granted by index maintainer; revocable.
2. `publisher.trusted` — the publisher is on the trusted-publisher allowlist.
3. `signature` — proves the bundle hasn't been swapped under the publisher.

Users SHOULD be prompted before installing unsigned + unverified skills.
The wizard installs `require_signed = false` by default so getting
started is friction-free; production deployments should flip the bit.
