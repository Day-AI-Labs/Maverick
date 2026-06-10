# RFC 0002: Plugin API v3 — not warranted (triggers recorded)

**Status:** Closed — not warranted at this time · **Roadmap ref:** 2028-H2
Ecosystem "plugin API v3 RFC (if warranted)" · **Date:** June 2026

## Verdict

Plugin API v2 released recently (docs/plugin-api-v2.md: structured channel
`Reply`, enforced manifest permissions, lockfile pinning, isolation modes,
TS + gRPC hosts) with a v1 compatibility window still open. There is no
accumulated breakage, no contract the current major cannot express, and no
ecosystem pressure that v2's additive surface cannot absorb. Opening a v3
now would burn the ecosystem's migration budget for zero capability.

## Triggers that WOULD warrant v3 (re-open this RFC when one fires)

1. A needed change to the Tool/Channel/Skill/Persona contracts that cannot be
   made additively under v2 (the gRPC/NDJSON wire protocols version
   independently and do not require a v3).
2. The v1 window's removal (deprecations registry: `plugins.api_v1`,
   remove_in 0.3.0) surfacing latent breakage that demands contract changes.
3. Capability-manifest semantics needing breaking changes (e.g. mandatory
   signed manifests via the plugin CA becoming the floor).

Until then: additive evolution under v2, with the compatibility-matrix CI
gate guarding the majors.
