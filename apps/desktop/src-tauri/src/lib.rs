//! Tauri shell for the local Maverick dashboard.
//!
//! The window first shows a bundled splash page (ui/index.html) that polls
//! `http://127.0.0.1:8765/healthz` (an auth-exempt endpoint, see
//! maverick_dashboard/app.py `_AUTH_EXEMPT`) and redirects to the dashboard
//! as soon as the port answers. On the Rust side, if nothing is listening on
//! 127.0.0.1:8765 at launch we spawn the user's installed CLI —
//! `maverick dashboard --host 127.0.0.1 --port 8765` — as a child process
//! and kill it again on exit. A dashboard the user already runs is left
//! untouched (we only ever kill a child we spawned).
//!
//! Why spawn the installed CLI instead of bundling a true Tauri "sidecar"
//! binary: the dashboard is a Python process; bundling it would mean
//! shipping a Python runtime inside the app. The CLI installers
//! (apps/installer-desktop, apps/installer-msi, pipx) already own "how
//! Maverick gets installed"; this shell stays a thin window.

use std::net::{SocketAddr, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::Manager;

const DASHBOARD_PORT: u16 = 8765;

struct Sidecar(Mutex<Option<Child>>);

fn dashboard_listening() -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], DASHBOARD_PORT));
    TcpStream::connect_timeout(&addr, Duration::from_millis(400)).is_ok()
}

fn spawn_dashboard() -> Option<Child> {
    // Loopback-only bind and no token: the dashboard serves loopback
    // without auth by design (see maverick_dashboard/app.py bearer_auth).
    match Command::new("maverick")
        .args(["dashboard", "--host", "127.0.0.1", "--port", "8765"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(child) => Some(child),
        Err(e) => {
            // Not fatal: the splash keeps polling and tells the user to run
            // `maverick dashboard` themselves (or install the CLI).
            eprintln!("maverick-desktop: could not spawn `maverick dashboard`: {e}");
            None
        }
    }
}

pub fn run() {
    let child = if dashboard_listening() {
        None
    } else {
        spawn_dashboard()
    };

    tauri::Builder::default()
        .manage(Sidecar(Mutex::new(child)))
        .build(tauri::generate_context!())
        .expect("error while building the Maverick desktop shell")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
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
