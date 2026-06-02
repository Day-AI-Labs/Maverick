// Maverick VS Code extension (MVP).
//
// Minimum-surface integration: sidebar tree view of recent runs +
// commands that shell out to the user's local `maverick` CLI. No
// daemon, no embedded Python, no auth: we trust the user's local
// `maverick` install and re-use its world model.
//
// Future versions will speak to `maverick serve` over a local REST
// API for richer features (streaming run output, plan-tree updates),
// but the shell-out path is good enough for v0.1.

import { spawn } from "child_process";
import * as vscode from "vscode";

function getCli(): string {
  return vscode.workspace.getConfiguration("maverick").get<string>("cliPath", "maverick");
}

const TERMINAL_CONTROL_RE = /(?:\x1B\][^\x07\x1B]*(?:\x07|\x1B\\|$))|(?:\x1B\[[0-?]*[ -/]*[@-~])|(?:\x1B[@-Z\\-_])|[\x00-\x1F\x7F-\x9F]/g;

function stripTerminalControl(text: string): string {
  return text.replace(TERMINAL_CONTROL_RE, "");
}

function getCwd(): string | undefined {
  const useWs = vscode.workspace.getConfiguration("maverick").get<boolean>("workspaceCwd", true);
  if (!useWs) return undefined;
  const folders = vscode.workspace.workspaceFolders;
  return folders && folders.length > 0 ? folders[0].uri.fsPath : undefined;
}

function runCliCapture(args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    const cli = getCli();
    const cwd = getCwd();
    const child = spawn(cli, args, { cwd });
    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (data: Buffer) => {
      stdout += data.toString();
    });
    child.stderr.on("data", (data: Buffer) => {
      stderr += data.toString();
    });
    child.on("error", reject);
    child.on("close", (code: number | null) => {
      if ((code ?? 0) !== 0) {
        reject(new Error(`maverick exited with code ${code ?? 0}\n${stderr}`));
        return;
      }
      resolve(stdout);
    });
  });
}

function runCliStream(args: string[], onLine: (line: string) => void): Promise<number> {
  return new Promise((resolve, reject) => {
    const cli = getCli();
    const cwd = getCwd();
    const child = spawn(cli, args, { cwd });
    let buf = "";
    const flush = (data: Buffer) => {
      buf += data.toString();
      let idx: number;
      while ((idx = buf.indexOf("\n")) >= 0) {
        onLine(buf.slice(0, idx));
        buf = buf.slice(idx + 1);
      }
    };
    child.stdout.on("data", flush);
    child.stderr.on("data", flush);
    child.on("error", reject);
    child.on("close", (code: number | null) => {
      if (buf) onLine(buf);
      resolve(code ?? 0);
    });
  });
}

// One run = one episode, as emitted by `maverick runs --json`. Keep in
// sync with the record built in maverick/cli.py::runs.
interface RunRecord {
  episode_id: number;
  goal_id: number;
  goal_title: string | null;
  goal_status: string | null;
  outcome: string | null;
  running: boolean;
  started_at: number | null;
  ended_at: number | null;
  duration_s: number | null;
  cost_dollars: number;
  input_tokens: number;
  output_tokens: number;
  tool_calls: number;
}

class RunItem extends vscode.TreeItem {
  constructor(public readonly run: RunRecord) {
    const title = stripTerminalControl(run.goal_title ?? `goal ${run.goal_id}`);
    super(`#${run.episode_id} ${title}`, vscode.TreeItemCollapsibleState.None);
    const state = run.running ? "running" : run.outcome ?? "done";
    const dur = run.duration_s != null ? `${run.duration_s.toFixed(1)}s` : "—";
    this.description = `${state} · $${run.cost_dollars.toFixed(4)}`;
    const tooltip = new vscode.MarkdownString();
    tooltip.appendMarkdown(`**Episode #${run.episode_id}** (goal #${run.goal_id})\n\n`);
    tooltip.appendMarkdown("Goal: ");
    tooltip.appendText(title);
    tooltip.appendMarkdown(
      `\n\nState: \`${state}\`` +
      `\n\nCost: \`$${run.cost_dollars.toFixed(4)}\`` +
      `\n\nTokens: \`${run.input_tokens} in / ${run.output_tokens} out\`` +
      `\n\nTool calls: \`${run.tool_calls}\`` +
      `\n\nDuration: \`${dur}\``,
    );
    this.tooltip = tooltip;
    this.iconPath = new vscode.ThemeIcon(
      run.running ? "sync"
      : state === "completed" || state === "succeeded" || state === "done" ? "check"
      : state === "failed" || state === "blocked" || state === "error" ? "error"
      : "circle-outline",
    );
    this.contextValue = "maverickRun";
  }
}

class RunsProvider implements vscode.TreeDataProvider<RunItem>, vscode.Disposable {
  private _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  refresh() {
    this._onDidChange.fire();
  }

  dispose() {
    this._onDidChange.dispose();
  }

  getTreeItem(el: RunItem): vscode.TreeItem {
    return el;
  }

  async getChildren(): Promise<RunItem[]> {
    let out: string;
    try {
      out = await runCliCapture(["runs", "--json"]);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      vscode.window.showErrorMessage(`Maverick CLI failed: ${msg}`);
      return [];
    }
    let rows: RunRecord[];
    try {
      rows = JSON.parse(out.trim() || "[]") as RunRecord[];
    } catch {
      vscode.window.showErrorMessage(
        "Maverick: could not parse `maverick runs --json` output.",
      );
      return [];
    }
    return rows.map((r) => new RunItem(r));
  }
}

let outputChannel: vscode.OutputChannel | undefined;

function getOutput(): vscode.OutputChannel {
  if (!outputChannel) {
    outputChannel = vscode.window.createOutputChannel("Maverick");
  }
  return outputChannel;
}

async function startGoalCommand() {
  const goal = await vscode.window.showInputBox({
    prompt: "Describe the goal for the agent",
    placeHolder: 'e.g. "review my latest commit and find bugs"',
    ignoreFocusOut: true,
  });
  if (!goal) return;
  const out = getOutput();
  out.show(true);
  out.appendLine(`> maverick start "${goal}"`);
  try {
    const code = await runCliStream(["start", goal], (line) => out.appendLine(line));
    out.appendLine(`[exit ${code}]`);
  } catch (e: unknown) {
    vscode.window.showErrorMessage(`Maverick start failed: ${(e as Error).message}`);
  }
}

async function statusCommand() {
  try {
    const txt = await runCliCapture(["status"]);
    const out = getOutput();
    out.show(true);
    out.append(txt);
  } catch (e: unknown) {
    vscode.window.showErrorMessage(`Maverick status failed: ${(e as Error).message}`);
  }
}

async function exportCommand() {
  const idStr = await vscode.window.showInputBox({
    prompt: "Goal ID to export",
    placeHolder: "e.g. 42",
    validateInput: (v) => (/^\d+$/.test(v.trim()) ? null : "must be a number"),
  });
  if (!idStr) return;
  const dest = await vscode.window.showSaveDialog({
    defaultUri: vscode.Uri.file(`goal-${idStr.trim()}.json`),
    filters: { JSON: ["json"] },
  });
  if (!dest) return;
  try {
    await runCliCapture(["export", idStr.trim(), "-o", dest.fsPath]);
    vscode.window.showInformationMessage(`Exported goal ${idStr} → ${dest.fsPath}`);
  } catch (e: unknown) {
    vscode.window.showErrorMessage(`Maverick export failed: ${(e as Error).message}`);
  }
}

export function activate(context: vscode.ExtensionContext): void {
  const runs = new RunsProvider();

  context.subscriptions.push(
    // Push the provider (disposes its EventEmitter) and the tree-view
    // registration so a reload/deactivate tears them down instead of leaking.
    runs,
    vscode.window.registerTreeDataProvider("maverick.runs", runs),
    vscode.commands.registerCommand("maverick.start", startGoalCommand),
    vscode.commands.registerCommand("maverick.status", statusCommand),
    vscode.commands.registerCommand("maverick.halt", async () => {
      try {
        await runCliCapture(["halt"]);
        vscode.window.showInformationMessage("Maverick halted.");
      } catch (e: unknown) {
        // A silent failure here is dangerous: the user would believe the
        // agent was halted when the CLI call actually failed.
        vscode.window.showErrorMessage(`Maverick halt failed: ${(e as Error).message}`);
      }
    }),
    vscode.commands.registerCommand("maverick.unhalt", async () => {
      try {
        await runCliCapture(["unhalt"]);
        vscode.window.showInformationMessage("Maverick resumed.");
      } catch (e: unknown) {
        vscode.window.showErrorMessage(`Maverick unhalt failed: ${(e as Error).message}`);
      }
    }),
    vscode.commands.registerCommand("maverick.openExport", exportCommand),
    vscode.commands.registerCommand("maverick.refreshRuns", () => runs.refresh()),
  );
}

export function deactivate(): void {
  if (outputChannel) outputChannel.dispose();
}
