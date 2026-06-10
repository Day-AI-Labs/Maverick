/**
 * @maverick/plugin-sdk — author Maverick agent tools in TypeScript.
 *
 * A plugin is a Node script that ends with `servePlugin([...tools])`. The
 * Maverick host (packages/maverick-core/maverick/ts_plugin_host.py) speaks
 * NDJSON to it, one JSON object per line:
 *
 *   plugin --describe              -> one-line manifest JSON, then exit
 *   {"id", "tool", "args"} on stdin -> {"id", "result"} | {"id", "error"} on stdout
 *
 * Handler exceptions become "ERROR: ..." result strings, matching the
 * convention of Maverick's built-in Python tools. Anything you log must go to
 * stderr (console.error) — stdout belongs to the protocol.
 */
import { createInterface } from "node:readline";

export const PROTOCOL = "maverick-plugin/1";

// Same constraint the model-facing tool catalog imposes (Anthropic tool names).
const NAME_RE = /^[A-Za-z0-9_-]{1,64}$/;

export interface ToolDef {
  /** Tool name as the model sees it: [A-Za-z0-9_-], max 64 chars. */
  name: string;
  /** One or two sentences telling the model when to use the tool. */
  description: string;
  /** JSON Schema for the args object. */
  inputSchema: Record<string, unknown>;
  /** Returns the tool result string (or a promise of one). */
  handler: (args: Record<string, unknown>) => string | Promise<string>;
}

/** Validate a tool definition; throws TypeError on a bad one. */
export function defineTool(def: ToolDef): ToolDef {
  if (typeof def?.name !== "string" || !NAME_RE.test(def.name)) {
    throw new TypeError(
      `defineTool: invalid tool name ${JSON.stringify(def?.name)} (want ${NAME_RE})`,
    );
  }
  if (typeof def.description !== "string" || def.description.length === 0) {
    throw new TypeError(`defineTool(${def.name}): description must be a non-empty string`);
  }
  if (typeof def.inputSchema !== "object" || def.inputSchema === null || Array.isArray(def.inputSchema)) {
    throw new TypeError(`defineTool(${def.name}): inputSchema must be a JSON Schema object`);
  }
  if (typeof def.handler !== "function") {
    throw new TypeError(`defineTool(${def.name}): handler must be a function`);
  }
  return def;
}

interface WireResponse {
  id: unknown;
  result?: string;
  error?: string;
}

function manifest(tools: ToolDef[]): string {
  return JSON.stringify({
    protocol: PROTOCOL,
    tools: tools.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })),
  });
}

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

async function answer(byName: Map<string, ToolDef>, line: string): Promise<WireResponse> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(line);
  } catch (e) {
    return { id: null, error: `invalid request: ${errorMessage(e)}` };
  }
  const req = (typeof parsed === "object" && parsed !== null ? parsed : {}) as Record<string, unknown>;
  const id = "id" in req ? req.id : null;
  if (typeof req.tool !== "string") {
    return { id, error: "invalid request: missing tool" };
  }
  const tool = byName.get(req.tool);
  if (tool === undefined) {
    return { id, error: `unknown tool: ${req.tool}` };
  }
  const args = (typeof req.args === "object" && req.args !== null && !Array.isArray(req.args)
    ? req.args
    : {}) as Record<string, unknown>;
  try {
    const result = await tool.handler(args);
    return { id, result: typeof result === "string" ? result : JSON.stringify(result) };
  } catch (e) {
    // Same convention as Maverick's Python tools: a failure is an
    // "ERROR: ..." result string the model can read, not a protocol error.
    return { id, result: `ERROR: ${tool.name} failed: ${errorMessage(e)}` };
  }
}

export interface ServeOptions {
  /** Request stream (default process.stdin). */
  input?: NodeJS.ReadableStream;
  /** Response stream (default process.stdout). */
  output?: NodeJS.WritableStream;
  /** CLI args (default process.argv.slice(2)). */
  argv?: string[];
}

/**
 * Serve the tools over the NDJSON wire protocol until stdin closes; with
 * `--describe` in argv, print the manifest and return immediately. Call this
 * at the end of your plugin script.
 */
export async function servePlugin(tools: ToolDef[], opts: ServeOptions = {}): Promise<void> {
  const checked = tools.map(defineTool);
  const byName = new Map(checked.map((t) => [t.name, t]));
  if (byName.size !== checked.length) {
    throw new TypeError("servePlugin: duplicate tool names");
  }
  const output = opts.output ?? process.stdout;
  const argv = opts.argv ?? process.argv.slice(2);
  if (argv.includes("--describe")) {
    output.write(manifest(checked) + "\n");
    return;
  }
  const lines = createInterface({ input: opts.input ?? process.stdin, crlfDelay: Infinity });
  for await (const line of lines) {
    if (line.trim() === "") continue;
    output.write(JSON.stringify(await answer(byName, line)) + "\n");
  }
}
