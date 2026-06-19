# maverick-installer-desktop

Native Tauri GUI installer for users who never open a terminal. A
double-click app with one button: it runs the same bootstrap the CLI
one-liners use (`deploy/desktop/install.{ps1,sh}`) behind a live
progress screen, so the user gets Lightwork installed without touching a
shell.

## How it works

```
  +------------------+   invoke('install')    +-------------------+
  | Svelte UI (TS)   | ────────────────────► | Rust shell (lib)  |
  |  Install button  | ◄───── events ──────── |  spawns bootstrap |
  +------------------+  install-log / -done    +---------+---------+
                                                          │
                                                          │ stdout/stderr
                                                          ▼
                                          deploy/desktop/install.{ps1,sh}
                                          (MAVERICK_NO_WIZARD=1):
                                          installs Python + git if needed,
                                          then pipx-installs Lightwork
```

The Rust shell owns the window and runs the bootstrap as a subprocess,
streaming each line to the UI as a Tauri event. **No Python is required
on the machine first** — the bootstrap installs it. This is why we shell
out to the existing scripts instead of embedding a Python runtime: those
scripts are already tested and are the single source of truth for "how
to install" (winget/brew/apt, PATH, pipx, PEP 668). When the bootstrap
finishes, the UI tells the user to run `maverick init` to configure.

## Status

Builds **unsigned** bundles on macOS / Windows / Linux via
`.github/workflows/desktop.yml`. The only thing between this and a
consumer-grade release is **code signing** — unsigned bundles trip
SmartScreen (Windows) and Gatekeeper (macOS), so users see an "unknown
developer" warning they must click through. Signing activates once the
Apple Developer Program / Windows code-signing certs exist (the
`desktop.yml` secret placeholders are where they plug in).

> **Needs real-machine testing.** CI confirms the bundle *builds*, but
> the actual install run (winget/brew, network, the GUI driving the
> bootstrap) has to be exercised on real Windows/macOS/Linux. Treat the
> first build as a release candidate to smoke-test, not a shipped
> artifact.

## Local development

```bash
cd apps/installer-desktop
pnpm install
pnpm tauri dev
```

Hot-reloads the Svelte frontend. Clicking **Install** runs the bundled
bootstrap, so test in a throwaway VM/container unless you actually want
Lightwork installed on your dev box. The desktop app pins the installed
source to the git commit captured at build time; set
`MAVERICK_INSTALL_REF=<commit-or-tag>` while building only when you need
to override that ref intentionally.

## Producing native bundles

```bash
pnpm tauri build
```

The build script records `git rev-parse HEAD` as the install ref, so the
signed GUI installer does not fetch and execute a mutable `main` branch
bootstrap at install time.

Outputs per platform:
- macOS: `.app` + `.dmg` (sign + notarize for distribution)
- Windows: `.msi` + `.exe` (NSIS)
- Linux: `.AppImage` + `.deb`

## Why Tauri vs Electron

| | Tauri | Electron |
|---|---|---|
| Bundle size | ~5 MB | ~150 MB |
| Memory at idle | ~50 MB | ~250 MB |
| Native webview | system (WebKit / WebView2 / WebKitGTK) | bundled Chromium |
| Rust shell | yes (security, smaller attack surface) | no |

Lightwork already needs Rust in the toolchain for the agent-shield
performance core, so adding Tauri is essentially free.
