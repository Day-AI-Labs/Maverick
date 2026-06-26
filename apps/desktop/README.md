# maverick-desktop

Native desktop window for the **local** Lightwork dashboard. A Tauri v2 shell:
the window opens on a bundled splash, the Rust side starts
`maverick dashboard --host 127.0.0.1 --port 8765` if nothing is listening
there, and the splash navigates to `http://127.0.0.1:8765` the moment
`/healthz` answers.

```
  +--------------------+        spawn if 8765 closed        +----------------------+
  | Rust shell (lib.rs)| ─────────────────────────────────► | maverick dashboard   |
  |  owns the window   |        kill own child on exit      |  (user's installed   |
  +---------+----------+                                    |   Python CLI)        |
            │ loads                                         +----------+-----------+
            ▼                                                          │
  ui/index.html + app.js ── polls /healthz (no-cors) ── navigates ─────┘
                                                       http://127.0.0.1:8765
```

- **Dashboard already running?** The shell leaves it alone, only navigates;
  it never kills a process it didn't spawn.
- **CLI not installed / not found?** The splash shows a help card with a
  "Try again" button and the exact command to run; it keeps polling so it
  connects automatically once the dashboard comes up.
- **Native menu:** Reload Dashboard (Cmd/Ctrl-R), Open in Browser
  (Cmd/Ctrl-Shift-O), Quit, plus a standard Edit menu so copy/paste/select-all
  work in the dashboard's text fields (required for clipboard on macOS).

## What was fixed (vs. the first scaffold)

The original shell could not actually connect, and was bare. This version
addresses:

1. **Cross-origin probe.** The splash runs at the Tauri origin, so a request
   to `127.0.0.1:8765` is cross-origin and the dashboard sends no CORS header
   for it — a normal `fetch` is blocked and *rejects forever*. The probe now
   uses `mode: "no-cors"` (resolves when the server answers, rejects only on a
   refused connection) and then does a top-level navigation, which is not
   subject to CORS. (`ui/app.js`)
2. **CSP blocked the splash script.** The old CSP had no `script-src`, so under
   `default-src 'self'` the inline `<script>` was itself blocked. The script is
   now an external `app.js` and the CSP grants `script-src 'self'` plus
   `ws://127.0.0.1:8765` for the dashboard's WebSocket firehose.
3. **`maverick` not found on double-click.** GUI launches (Finder/Dock/Explorer)
   get a minimal `PATH` without the pip/pipx install dirs, so
   `Command::new("maverick")` failed. The shell now checks `MAVERICK_BIN`, then
   `~/.local/bin`, Homebrew, and `/usr/local/bin` before falling back to the
   bare name. (`src/lib.rs`)
4. **Polish + usability.** Branded splash with staged status and an actionable
   trouble card; a native menu; explicit `main` window label; sensible minimum
   window size.

## Icons (do this before bundling)

Only a placeholder `icons/icon.png` ships. Generate the full platform set
(`.icns`, `.ico`, sized PNGs) from a single 1024×1024 source, then expand the
`bundle.icon` list in `tauri.conf.json`:

```bash
cargo tauri icon path/to/maverick-1024.png   # writes src-tauri/icons/*
```

## Build & run

Needs Rust + the Tauri CLI (plus platform webview dev packages, e.g.
`webkit2gtk` on Linux). None of that is available in the authoring
environment, so **the first local build is the smoke-test.**

```bash
cargo install tauri-cli            # once
cd apps/desktop
cargo tauri dev                    # hot-reload dev window
cargo tauri build                  # native bundles (see targets below)
```

No JS toolchain: `ui/` is plain static HTML/CSS/JS (`frontendDist: "../ui"`),
no bundler step.

Bundle targets (`src-tauri/tauri.conf.json`):
- macOS: `.app` + `.dmg`
- Windows: `.msi` + `.exe` (NSIS)
- Linux: `.deb` + `.AppImage`

## Troubleshooting

- **Splash stuck on "Still waiting…":** the CLI isn't being found. Either run
  `maverick dashboard` yourself in a terminal (the window then connects on its
  own), or point the shell at the binary explicitly:
  `MAVERICK_BIN=/full/path/to/maverick` in the app's environment.
- **Wrong port:** this shell targets `8765` (the dashboard default). If you run
  the dashboard on another port, run it yourself on `8765`, or change
  `DASHBOARD_PORT` in `src/lib.rs`, the `PORT` in `ui/app.js`, and the CSP
  hosts in `tauri.conf.json`, then rebuild.

## Status

Ships **unsigned** bundles — same posture as `apps/installer-desktop`: unsigned
bundles trip SmartScreen (Windows) and Gatekeeper (macOS) until code-signing
certs exist. On macOS, right-click → **Open**; on Windows, **More info → Run
anyway**.
