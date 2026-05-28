# Desktop deployment

## One-line install (recommended)

No Python required up front — the script installs Python + git if
they're missing, sets up an isolated environment, and launches the
setup wizard.

**Windows** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/texasreaper62/maverick/main/deploy/desktop/install.ps1 | iex
```

**macOS / Linux**:

```bash
curl -fsSL https://raw.githubusercontent.com/texasreaper62/maverick/main/deploy/desktop/install.sh | bash
```

Pin a branch/tag or fork with `MAVERICK_REPO` / `MAVERICK_REF`
(`$env:MAVERICK_REF` on Windows) before running.

## With pipx (if you already have Python 3.10+)

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

## Native bundles (planned)

The long-term plan ships native bundles per platform so users don't
need Python installed at all:

| Platform | Tool | Format | Auto-update |
|---|---|---|---|
| macOS | Tauri | Notarized DMG, signed `.app` | Sparkle via Tauri updater |
| Windows | Tauri | Signed MSIX | Tauri updater |
| Linux | Tauri | AppImage + `.deb` + `.rpm` | AppImageUpdate |

The Tauri shell ships an embedded Python runtime via
[PyOxidizer](https://pyoxidizer.readthedocs.io/) or
[python-build-standalone](https://github.com/indygreg/python-build-standalone),
and the wizard runs as a Svelte UI talking to a sidecar Python process.

See [`apps/installer-desktop/`](../../apps/installer-desktop/README.md)
for the scaffold and milestones.
