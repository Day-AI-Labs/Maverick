# @maverick/plugin-sdk

Author Lightwork agent tools in TypeScript. A plugin is a plain Node script:
Lightwork spawns it, discovers its tools, and calls them over stdio.

## Writing a plugin

```ts
import { defineTool, servePlugin } from "@maverick/plugin-sdk";

const greet = defineTool({
  name: "greet",
  description: "Greet someone by name.",
  inputSchema: { type: "object", properties: { who: { type: "string" } }, required: ["who"] },
  handler: (args) => `Hello, ${args.who}!`,
});

await servePlugin([greet]);
```

Compile it (`npm run build` here is just `tsc`) and you have a plugin.
Handlers return a string (or a promise of one); a thrown error becomes an
`"ERROR: <tool> failed: <message>"` result string, the same convention
Lightwork's built-in Python tools use. Log to stderr (`console.error`) only —
stdout belongs to the protocol.

## How Lightwork loads it

Opt in via `~/.maverick/config.toml` (the command is an argv list, run with a
secret-scrubbed environment — your plugin never sees provider API keys):

```toml
[plugins]
ts = [["node", "/abs/path/to/plugin.js"]]
```

`maverick.ts_plugin_host.load_ts_plugin(command)` runs `command --describe` to
read the manifest and builds one Lightwork tool per entry. Tool calls go to a
single persistent child process, started lazily; if it crashes mid-call it is
restarted and the call retried once, and a call that exceeds the timeout kills
it and returns an `ERROR:` string.

## Wire protocol (`maverick-plugin/1`)

NDJSON: one JSON object per line, UTF-8.

- `plugin --describe` prints the manifest and exits:

  ```json
  {"protocol": "maverick-plugin/1", "tools": [{"name": "greet", "description": "...", "inputSchema": {...}}]}
  ```

- Otherwise the plugin reads requests on stdin and answers on stdout, echoing
  back each request's `id`:

  ```json
  {"id": 1, "tool": "greet", "args": {"who": "Lightwork"}}
  {"id": 1, "result": "Hello, Lightwork!"}
  ```

  Protocol-level failures (unknown tool, malformed request) use
  `{"id": 1, "error": "..."}` instead; the host renders both shapes as
  `ERROR:` strings for the model. stdin closing means shut down.

The protocol is language-neutral — anything that speaks it can be loaded the
same way; this SDK is just the TypeScript implementation.

## Structured page context

The Maverick browser extension (`extensions/browser/`) can attach a bounded,
observe-only accessibility/DOM snapshot of the active page to a goal. This SDK
exports types and a safe parser for consuming that snapshot in a plugin:

```ts
import { parseStructuredPageContext, summarizePageContext } from "@maverick/plugin-sdk";

const ctx = parseStructuredPageContext(args.page); // object or JSON string
if (ctx) {
  console.error(summarizePageContext(ctx)); // logging goes to stderr
  // ctx.elements: interactive controls (name/role/tag/selector/type/value)
  // ctx.landmarks: landmarks + headings; ctx.lang/counts/truncated metadata
}
```

`parseStructuredPageContext` validates untrusted input and re-applies the
extension's caps (≤60 elements, ≤25 landmarks, per-string length limits),
returning `null` for anything that isn't a usable snapshot — so a plugin never
trusts oversized or malformed page context. See `StructuredPageContext`,
`PageElement`, and `PageLandmark` for the shapes.

## Developing

```sh
npm install   # dev deps: typescript + @types/node
npm test      # tsc && node --test
```

The `.ts` sources are authoritative and committed; `dist/` is build output.
