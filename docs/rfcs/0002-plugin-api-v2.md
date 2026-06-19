# RFC 0002: Plugin API v2

- Status: **Draft — open for comment**
- Tracking: roadmap item "Plugin API v2 RFC" (2028-H1 Ecosystem)

## What v1 is

Entry points in four groups (`maverick.tools/channels/skills/personas`),
gated by allowlist + name-squat defense + manifest permissions
(`plugins.py`), with 1.x-era additions that are already de-facto API:
hot reload, the isolation seam (subinterpreter/subprocess), the version
lockfile, and opt-in telemetry.

## Problems v2 solves

1. **No declared compatibility** — a plugin can't say which Lightwork versions
   it supports; breakage is discovered at import time.
2. **Capability opacity** — manifests declare *permissions*, but not the
   tools/channels they provide, so `maverick plugin list` must import code to
   answer "what would this add?"
3. **No lifecycle hooks** — plugins can't run setup/teardown (e.g. open a
   connection pool) outside tool-call time.
4. **Python-only** — the gRPC plugin host (2028 roadmap) needs a wire-level
   contract, which v1's "import a callable" cannot express.

## Proposed v2 surface

```toml
# pyproject.toml of a plugin
[project.entry-points."maverick.plugin_v2"]
acme = "acme_maverick:manifest"
```

`manifest()` returns a static dict (no side effects):

```python
{
  "api": 2,
  "requires_maverick": ">=2.0,<3",
  "provides": {"tools": ["acme_search"], "channels": []},
  "permissions": ["network"],
  "lifecycle": "acme_maverick:plugin",   # optional: setup()/teardown()
}
```

- Discovery reads the manifest *without importing plugin code* (the v1 gates
  — allowlist, lockfile, permissions — run against it first).
- `lifecycle.setup(context)` runs once per process under the isolation policy;
  `context` carries the granted permission set and a scoped data dir.
- The same manifest shape serializes over the wire for the gRPC plugin host
  (out-of-process / non-Python plugins): `provides` becomes the service's
  advertised tool list, calls route like MCP tools do today.

## Back-compat

v1 entry points keep working for all of 2.x; `maverick plugin list` labels
them `api: 1`. The lockfile/telemetry/isolation seams apply to both.

## Open questions

1. Is `requires_maverick` enforced at load (refuse) or warn-only by default?
2. Should `provides` be verified post-load (a plugin that registers more than
   it declared gets refused) — strict, or drift-warn like the lockfile?
3. gRPC host transport: reuse the existing `grpc_api` proto file or a
   dedicated `plugin.proto`?

Comment by PR on this file.
