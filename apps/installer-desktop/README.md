# maverick-installer-desktop

Native Tauri GUI installer for users who never open a terminal.
Wraps the same `maverick_installer.wizard` logic the CLI uses, behind a
Svelte UI.

## Status: scaffold (not yet shippable)

The Tauri shell, Cargo manifest, Svelte frontend skeleton, and the
Python sidecar IPC are in place. **The bundle does not build today.**
Items still missing:

- `src-tauri/icons/` (generate via `cargo tauri icon`)
- `[[bin]]` target in `Cargo.toml`
- Tauri v2 `src-tauri/capabilities/default.json` allowlist
- Embedded Python runtime via `python-build-standalone` (the sidecar
  currently shells out to system `python3`, which won't exist in a
  packaged `.app`/`.msi`)
- GitHub Actions matrix wired to `tauri-apps/tauri-action`
- Code-signing identifiers (`APPLE_*`, `WINDOWS_PFX_*`) wired through
  workflow secrets

Use the CLI wizard (`maverick init`) until these are addressed.

## Local development

```bash
cd apps/installer-desktop
pnpm install
pnpm tauri dev
```

This starts the Tauri dev shell with hot-reload on the Svelte frontend
and the Python sidecar (`bridge.py`) reachable from the UI via Tauri's
invoke API.

## Producing native bundles

```bash
pnpm tauri build
```

Outputs (per platform):
- macOS: `.app` + `.dmg` (sign + notarize for distribution)
- Windows: `.exe` MSI installer + standalone executable
- Linux: `.AppImage` + `.deb`

## Why Tauri vs Electron

| | Tauri | Electron |
|---|---|---|
| Bundle size | ~5 MB | ~150 MB |
| Memory at idle | ~50 MB | ~250 MB |
| Native webview | system (WebKit / WebView2 / WebKitGTK) | bundled Chromium |
| Rust shell | yes (security, smaller attack surface) | no |

Maverick already needs Rust in the toolchain for the agent-shield
performance core, so adding Tauri is essentially free.

## Architecture

```
  +------------------+      Tauri invoke      +-------------------+
  | Svelte UI (TS)   | <--------------------> | Rust shell (main) |
  +------------------+                        +---------+---------+
                                                        |
                                                        | stdin/stdout JSON-RPC
                                                        v
                                              +-------------------+
                                              | bridge.py (sidecar) |
                                              | imports maverick    |
                                              | + maverick_installer|
                                              +-------------------+
```

The Rust shell handles window + IPC. Everything else (wizard
questions, config writes, API key validation) goes through the same
Python code the CLI wizard uses.
