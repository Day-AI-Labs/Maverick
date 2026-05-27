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

import { spawn, exec, ExecException } from "child_process";
import * as vscode from "vscode";

function getCli(): string {
  return vscode.workspace.getConfiguration("maverick").get<string>("cliPath", "maverick");
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
    exec([cli, ...args].join(" "), { cwd }, (err: ExecException | null, stdout: string, stderr: string) => {
      if (err) {
        reject(new Error(`${err.message}\n${stderr}`));
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

class RunItem extends vscode.TreeItem {
  constructor(
    public readonly id: number,
    label: string,
    public readonly status: string,
    public readonly dollars: number,
  ) {
    super(`#${id} ${label}`, vscode.TreeItemCollapsibleState.None);
    this.description = `${status} · $${dollars.toFixed(4)}`;
    this.tooltip = new vscode.MarkdownString(
      `**Goal #${id}**\n\nStatus: \`${status}\`\n\nCost: \`$${dollars.toFixed(4)}\``,
    );
    this.iconPath = new vscode.ThemeIcon(
      status === "succeeded" || status === "done" ? "check"
      : status === "failed" || status === "blocked" ? "error"
      : status === "in_progress" || status === "running" ? "sync"
      : "circle-outline",
    );
    this.contextValue = "maverickRun";
  }
}

class RunsProvider implements vscode.TreeDataProvider<RunItem> {
  private _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  refresh() {
    this._onDidChange.fire();
  }

  getTreeItem(el: RunItem): vscode.TreeItem {
    return el;
  }

  async getChildren(): Promise<RunItem[]> {
    try {
      // Parse `maverick cost` to get totals (used as a probe) +
      // `maverick logs --day` for the recent run list. For v0.1 we
      // just use `cost` to confirm the CLI works; richer parsing
      // lands when `maverick runs --json` exists.
      const out = await runCliCapture(["cost"]);
      const dollarsMatch = /Dollars:\s+\$([0-9.]+)/.exec(out);
      const epsMatch = /Episodes:\s+(\d+)/.exec(out);
      if (!dollarsMatch || !epsMatch) {
        return [new RunItem(0, "(no runs yet)", "pending", 0)];
      }
      // Placeholder: a single summary tile. Full per-run parsing is
      // the next iteration -- needs a new `maverick runs --json` cmd.
      const total = parseFloat(dollarsMatch[1]);
      const eps = parseInt(epsMatch[1], 10);
      return [new RunItem(eps, `lifetime: ${eps} run(s)`, "summary", total)];
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      vscode.window.showErrorMessage(`Maverick CLI failed: ${msg}`);
      return [];
    }
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
  const code = await runCliStream(["start", goal], (line) => out.appendLine(line));
  out.appendLine(`[exit ${code}]`);
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
  vscode.window.registerTreeDataProvider("maverick.runs", runs);

  context.subscriptions.push(
    vscode.commands.registerCommand("maverick.start", startGoalCommand),
    vscode.commands.registerCommand("maverick.status", statusCommand),
    vscode.commands.registerCommand("maverick.halt", async () => {
      await runCliCapture(["halt"]);
      vscode.window.showInformationMessage("Maverick halted.");
    }),
    vscode.commands.registerCommand("maverick.unhalt", async () => {
      await runCliCapture(["unhalt"]);
      vscode.window.showInformationMessage("Maverick resumed.");
    }),
    vscode.commands.registerCommand("maverick.openExport", exportCommand),
    vscode.commands.registerCommand("maverick.refreshRuns", () => runs.refresh()),
  );
}

export function deactivate(): void {
  if (outputChannel) outputChannel.dispose();
}
