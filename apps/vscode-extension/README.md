# Lightwork for VS Code

Sidebar + commands for the [Lightwork](https://github.com/Day-AI-Labs/Lightwork)
agent framework, accessible from inside VS Code.

This is an MVP (v0.1):

- Sidebar **Lightwork** view with a recent-runs summary.
- Commands: **Start goal**, **Show status**, **Halt**, **Unhalt**,
  **Export run as JSON**, **Refresh runs**.
- All commands shell out to the user's local `maverick` CLI. No
  daemon, no embedded Python.

## Setup

1. Install Lightwork: `pip install maverick-agent` (or run the
   wizard: `maverick init`).
2. Build the extension: `cd apps/vscode-extension && npm install && npm run compile`.
3. From VS Code: **Run** → **Run Extension** (F5), or package with
   `vsce package` and install the `.vsix`.

## Config

| Setting               | Default     | Description                                      |
|-----------------------|-------------|--------------------------------------------------|
| `maverick.cliPath`    | `maverick`  | Path to the `maverick` CLI executable.           |
| `maverick.workspaceCwd` | `true`    | Use the current workspace as cwd when running.   |

## Roadmap

Next iterations of the extension (from `docs/ROADMAP.md`):

- Live run streaming via `maverick serve` REST API
  (Q1 2026 ecosystem).
- Plan-tree visualization (Q2 2026 UX).
- Approve-tool-call inline in the editor (Q4 2027 UX).
- Right-click context: "Send selection to Lightwork" (Q2 2027 ecosystem).

## License

Proprietary — same as the main project; see [`LICENSE`](../../LICENSE).
