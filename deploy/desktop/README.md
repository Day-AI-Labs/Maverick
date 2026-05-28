# Desktop deployment

For v0.1, install via pipx:

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
