//! Tauri shell for the local Maverick dashboard.
//!
//! The window first shows a bundled splash page (ui/index.html + ui/app.js)
//! that polls `http://127.0.0.1:8765/healthz` (an auth-exempt endpoint, see
//! maverick_dashboard/app.py `_AUTH_EXEMPT`) and navigates to the dashboard as
//! soon as the port answers. On the Rust side, if nothing is listening on
//! 127.0.0.1:8765 at launch we spawn the user's installed CLI —
//! `maverick dashboard --host 127.0.0.1 --port 8765` — as a child process and
//! kill it again on exit. A dashboard the user already runs is left untouched
//! (we only ever kill a child we spawned).
//!
//! Why spawn the installed CLI instead of bundling a true Tauri "sidecar"
//! binary: the dashboard is a Python process; bundling it would mean shipping a
//! Python runtime inside the app. The CLI installers (apps/installer-desktop,
//! apps/installer-msi, pipx) already own "how Maverick gets installed"; this
//! shell stays a thin window.

use std::ffi::OsString;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::menu::{MenuBuilder, MenuItemBuilder, PredefinedMenuItem, SubmenuBuilder};
use tauri::{Manager, RunEvent};

const DASHBOARD_PORT: u16 = 8765;

struct Sidecar(Mutex<Option<Child>>);

fn dashboard_url() -> String {
    format!("http://127.0.0.1:{DASHBOARD_PORT}/")
}

fn dashboard_listening() -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], DASHBOARD_PORT));
    TcpStream::connect_timeout(&addr, Duration::from_millis(400)).is_ok()
}

/// Locate the `maverick` CLI.
///
/// A GUI launch (Finder/Dock/Explorer) does **not** inherit the shell's `PATH`
/// — it gets a minimal one (`/usr/bin:/bin:…`) that omits the very directories
/// pip/pipx install into. So `Command::new("maverick")` alone fails for almost
/// every real install. We check `MAVERICK_BIN`, then the common install dirs,
/// then fall back to the bare name (which still works when launched from a
/// shell that has it on PATH).
fn maverick_bin() -> OsString {
    let exe = if cfg!(windows) { "maverick.exe" } else { "maverick" };

    if let Some(explicit) = std::env::var_os("MAVERICK_BIN") {
        return explicit;
    }

    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(home) = std::env::var_os("HOME") {
        let home = PathBuf::from(home);
        candidates.push(home.join(".local").join("bin").join(exe)); // pip/pipx --user
        candidates.push(home.join("bin").join(exe));
    }
    if let Some(profile) = std::env::var_os("USERPROFILE") {
        let profile = PathBuf::from(profile);
        candidates.push(profile.join(".local").join("bin").join(exe)); // Windows --user
    }
    for dir in ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"] {
        candidates.push(Path::new(dir).join(exe));
    }
    for c in candidates {
        if c.exists() {
            return c.into_os_string();
        }
    }
    OsString::from(exe)
}

fn spawn_dashboard() -> Option<Child> {
    // Loopback-only bind and no token: the dashboard serves loopback without
    // auth by design (see maverick_dashboard/app.py bearer_auth).
    // Use the DASHBOARD_PORT constant (not a literal) so the spawned port, the
    // URL, and the listening check can never drift apart.
    let port = DASHBOARD_PORT.to_string();
    match Command::new(maverick_bin())
        .args(["dashboard", "--host", "127.0.0.1", "--port", port.as_str()])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(child) => Some(child),
        Err(e) => {
            // Not fatal: the splash keeps polling and shows the user how to
            // start it themselves (or install the CLI).
            eprintln!("maverick-desktop: could not spawn `maverick dashboard`: {e}");
            None
        }
    }
}

/// Open a URL in the user's default browser (std only — no extra plugin/dep).
fn open_in_browser(url: &str) {
    let spawn = |program: &str, args: &[&str]| {
        let _ = Command::new(program).args(args).spawn();
    };
    #[cfg(target_os = "macos")]
    spawn("open", &[url]);
    #[cfg(target_os = "windows")]
    spawn("cmd", &["/C", "start", "", url]);
    #[cfg(all(unix, not(target_os = "macos")))]
    spawn("xdg-open", &[url]);
}

pub fn run() {
    let child = if dashboard_listening() {
        None
    } else {
        spawn_dashboard()
    };

    tauri::Builder::default()
        .manage(Sidecar(Mutex::new(child)))
        // A real menu: Reload / Open in Browser / Quit, plus a standard Edit
        // menu so Cmd-C / Cmd-V / Select-All work in the dashboard's text
        // fields (on macOS the webview has no clipboard shortcuts without it).
        .menu(|handle| {
            let open_browser = MenuItemBuilder::with_id("open_browser", "Open in Browser")
                .accelerator("CmdOrCtrl+Shift+O")
                .build(handle)?;
            let reload = MenuItemBuilder::with_id("reload", "Reload Dashboard")
                .accelerator("CmdOrCtrl+R")
                .build(handle)?;
            let quit = PredefinedMenuItem::quit(handle, Some("Quit Maverick"))?;
            let app_menu = SubmenuBuilder::new(handle, "Maverick")
                .item(&open_browser)
                .item(&reload)
                .separator()
                .item(&quit)
                .build()?;
            let edit = SubmenuBuilder::new(handle, "Edit")
                .undo()
                .redo()
                .separator()
                .cut()
                .copy()
                .paste()
                .select_all()
                .build()?;
            MenuBuilder::new(handle).item(&app_menu).item(&edit).build()
        })
        .on_menu_event(|app, event| match event.id().as_ref() {
            "reload" => {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.eval("window.location.reload()");
                }
            }
            "open_browser" => open_in_browser(&dashboard_url()),
            _ => {}
        })
        .build(tauri::generate_context!())
        .expect("error while building the Maverick desktop shell")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                // Kill only the dashboard *we* started; an externally started
                // one was never put into the Sidecar state.
                if let Ok(mut guard) = app.state::<Sidecar>().0.lock() {
                    if let Some(child) = guard.as_mut() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        });
}
