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

// --------------------------------------------------------------------------
// Structured page context (browser extension <-> agent).
//
// The Maverick browser extension (extensions/browser/) can attach a bounded,
// OBSERVE-ONLY accessibility/DOM snapshot of the active page to a goal. These
// types + parser let a TypeScript plugin consume that snapshot safely: parse
// validates/normalizes untrusted JSON and re-applies the same bounds the
// extension enforces, so a plugin never trusts oversized or malformed input.
// --------------------------------------------------------------------------

/** One interactive control (button/link/input/…) from the page snapshot. */
export interface PageElement {
  /** ARIA role or tag name, e.g. "button", "link", "textbox". */
  role: string;
  /** Lowercase tag name, e.g. "a", "button", "input". */
  tag: string;
  /** Accessible name/label (may be empty). */
  name: string;
  /** Advisory selector hint (#id / tag[name=…] / :nth-of-type); not guaranteed. */
  selector: string;
  /** Input type, when the element is a form field. */
  type?: string;
  /** Visible value or placeholder (never a password value). */
  value?: string;
  /** True when the control is disabled. */
  disabled?: boolean;
}

/** A landmark or heading giving the page outline. */
export interface PageLandmark {
  role: string;
  tag: string;
  name: string;
}

/** The structured snapshot the extension attaches to a goal. */
export interface StructuredPageContext {
  /** Document language (BCP-47-ish), may be empty. */
  lang: string;
  counts: { elements: number; landmarks: number };
  /** True when caps were hit and the snapshot is partial. */
  truncated: boolean;
  landmarks: PageLandmark[];
  elements: PageElement[];
}

// Bounds mirror content.js so a plugin re-clamps untrusted input.
const PCTX_MAX_ELEMENTS = 60;
const PCTX_MAX_LANDMARKS = 25;
const PCTX_MAX_NAME = 120;
const PCTX_MAX_SELECTOR = 120;
const PCTX_MAX_VALUE = 80;

function pctxStr(v: unknown, max: number): string {
  return typeof v === "string" ? v.slice(0, max) : "";
}

function pctxElement(raw: unknown): PageElement {
  const o = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  const el: PageElement = {
    role: pctxStr(o.role, 32),
    tag: pctxStr(o.tag, 32),
    name: pctxStr(o.name, PCTX_MAX_NAME),
    selector: pctxStr(o.selector, PCTX_MAX_SELECTOR),
  };
  if (typeof o.type === "string") el.type = o.type.slice(0, 24);
  if (typeof o.value === "string") el.value = o.value.slice(0, PCTX_MAX_VALUE);
  if (o.disabled === true) el.disabled = true;
  return el;
}

function pctxLandmark(raw: unknown): PageLandmark {
  const o = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  return {
    role: pctxStr(o.role, 32),
    tag: pctxStr(o.tag, 32),
    name: pctxStr(o.name, PCTX_MAX_NAME),
  };
}

/**
 * Parse + validate an untrusted structured-page-context value (object or JSON
 * string) into a normalized {@link StructuredPageContext}, re-applying the
 * extension's caps. Returns null when the input is not a usable snapshot.
 */
export function parseStructuredPageContext(input: unknown): StructuredPageContext | null {
  let raw: unknown = input;
  if (typeof input === "string") {
    try {
      raw = JSON.parse(input);
    } catch {
      return null;
    }
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const o = raw as Record<string, unknown>;
  const elementsIn = Array.isArray(o.elements) ? o.elements : [];
  const landmarksIn = Array.isArray(o.landmarks) ? o.landmarks : [];
  const elements = elementsIn.slice(0, PCTX_MAX_ELEMENTS).map(pctxElement);
  const landmarks = landmarksIn.slice(0, PCTX_MAX_LANDMARKS).map(pctxLandmark);
  const counts = (typeof o.counts === "object" && o.counts !== null ? o.counts : {}) as Record<string, unknown>;
  return {
    lang: pctxStr(o.lang, 16),
    counts: {
      elements: typeof counts.elements === "number" ? counts.elements : elements.length,
      landmarks: typeof counts.landmarks === "number" ? counts.landmarks : landmarks.length,
    },
    truncated: o.truncated === true,
    landmarks,
    elements,
  };
}

/** Render a parsed snapshot to a compact, human/agent-readable summary. */
export function summarizePageContext(ctx: StructuredPageContext): string {
  const lines: string[] = [];
  lines.push(
    `page: ${ctx.counts.elements} interactive, ${ctx.counts.landmarks} landmarks` +
      (ctx.truncated ? " (truncated)" : "") +
      (ctx.lang ? `, lang=${ctx.lang}` : ""),
  );
  for (const l of ctx.landmarks) {
    lines.push(`  [${l.tag}${l.role && l.role !== l.tag ? "/" + l.role : ""}] ${l.name}`.trimEnd());
  }
  for (const e of ctx.elements) {
    let line = `  <${e.role || e.tag}> ${e.name}`.trimEnd();
    if (e.type) line += ` type=${e.type}`;
    if (e.disabled) line += " (disabled)";
    if (e.selector) line += ` @ ${e.selector}`;
    lines.push(line);
  }
  return lines.join("\n");
}
