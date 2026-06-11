# Plugin API v2 — release notes

`MAVERICK_API_VERSION = "2"`. Declare it in your `maverick-plugin.toml`:

```toml
[plugin]
name        = "my-plugin"
version     = "0.1.0"
api_version = "2"
```

## What's new in v2

- **Structured channel replies.** Channel handlers may return
  `maverick_channels.Reply` (text + attachments + thread_ref) instead of bare
  `str`. Adapters route through `Channel.dispatch` / `dispatch_text`, so a v2
  handler works on every adapter; platforms without a file API drop
  attachments with a debug note and always deliver the text.
- **Manifest permissions are enforced by default.** A plugin that requests an
  ungranted permission (`network` / `fs_write` / `subprocess` /
  `sensitive_envs`) is skipped unless the user grants it via
  `[plugins] grant = [...]`. (`enforce_permissions = false` downgrades to a
  load-with-warning.)
- **Lockfile pinning.** `maverick plugin lock` records each enabled plugin's
  distribution + version; under enforcement a drifted version is refused.
- **Isolation modes.** `[plugins] isolation = "subprocess" | "subinterpreter"`
  runs plugin tool *calls* outside the host interpreter (scrubbed env, fault
  isolation) while their schemas stay in-process.
- **TypeScript plugins.** `sdks/plugin-ts` (`@maverick/plugin-sdk`) authors a
  tool in TypeScript over the `maverick-plugin/1` NDJSON stdio protocol;
  `[plugins] ts = [["node", "/path/plugin.js"]]` loads it like any other tool
  (no-shadowing rule included).

## Compatibility

- `SUPPORTED_API_MAJORS = (1, 2)`: a v1 plugin **keeps loading** for one minor
  release, with a deprecation warning in its manifest validation. Migrate by
  bumping `api_version = "2"` (and adopting `Reply` if you ship a channel).
- A plugin declaring `api_version = "3"` (or malformed) is refused — the
  kernel never loads a contract it doesn't understand.

## Unchanged from v1

Entry-point groups (`maverick.tools` / `.channels` / `.skills` /
`.personas`), the allowlist (`[plugins] enabled`), and the name-squat defense
(`name@dist` pinning) all work exactly as before.
