# maverick-desktop

Native desktop window for the **local** Maverick dashboard. A Tauri v2
shell: the window opens on a bundled splash page, the Rust side spawns
`maverick dashboard --host 127.0.0.1 --port 8765` if nothing is listening
there yet, and the splash redirects to `http://127.0.0.1:8765` as soon as
`/healthz` answers.

## How it works

```
  +--------------------+        spawn if 8765 closed        +----------------------+
  | Rust shell (lib.rs)| ─────────────────────────────────► | maverick dashboard   |
  |  owns the window   |        kill own child on exit      |  (user's installed   |
  +---------+----------+                                    |   Python CLI)        |
            │ loads                                         +----------+-----------+
            ▼                                                          │
  ui/index.html splash ── polls /healthz (auth-exempt) ── redirects ───┘
                                                       http://127.0.0.1:8765
```

- **Dashboard already running?** The shell leaves it alone and only
  redirects; it never kills a process it didn't spawn.
- **CLI not installed?** The spawn fails, the splash keeps polling and
  tells the user to run `maverick dashboard` (or install the CLI first —
  `apps/installer-desktop`, `apps/installer-msi`, pipx).
- **Why not a true Tauri sidecar binary:** the dashboard is a Python
  process; bundling it means shipping a Python runtime. The installers own
  "how Maverick gets installed"; this shell stays a thin native window over
  the loopback dashboard (which serves loopback without a token by design —
  see `maverick_dashboard/app.py` `bearer_auth`).

## Status

Ships **unsigned** bundles — exactly the same posture as
`apps/installer-desktop`: unsigned bundles trip SmartScreen (Windows) and
Gatekeeper (macOS) until code-signing certs exist.

> **Authored, not built, in this environment.** Building needs Rust + the
> Tauri CLI (plus platform webview dev packages, e.g. webkit2gtk on Linux),
> none of which are available here. Two behaviours specifically need
> real-machine verification: (1) the JS `location.replace` navigation from
> the bundled splash to the external `http://127.0.0.1:8765` origin under
> Tauri v2's navigation policy, and (2) child-process cleanup on all three
> OSes. Treat the first build as a release candidate to smoke-test.

## Local development

```bash
cd apps/desktop
cargo tauri dev          # needs: cargo install tauri-cli
```

No JS toolchain: `ui/` is plain static HTML (`frontendDist: "../ui"`),
there is no bundler step.

## Producing native bundles

```bash
cargo tauri build
```

Bundle targets configured in `src-tauri/tauri.conf.json`:
- macOS: `.app` + `.dmg`
- Windows: `.msi` + `.exe` (NSIS)
- Linux: `.deb` + `.AppImage`
