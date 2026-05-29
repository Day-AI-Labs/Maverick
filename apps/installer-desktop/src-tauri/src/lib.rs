//! Tauri shell for the Maverick graphical installer.
//!
//! The window hosts a one-button Svelte UI. Pressing "Install" runs the
//! same bootstrap the CLI one-liners use
//! (`deploy/desktop/install.{ps1,sh}`) with `MAVERICK_NO_WIZARD=1`, and
//! streams each output line to the UI as a Tauri event. No Python is
//! required on the machine first -- the bootstrap installs it. When it
//! finishes, the UI tells the user to run `maverick init`.
//!
//! Why shell out to the existing scripts instead of reimplementing the
//! install in Rust: those scripts are already tested and handle the
//! gnarly bits (winget/brew/apt, PATH, pipx, PEP 668). The shell stays
//! tiny and there's a single source of truth for "how to install".

use std::process::Stdio;
use tauri::{AppHandle, Emitter};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;

// Source the installer pulls from.
const REPO: &str = "cdayAI/Maverick";
const GIT_REF: &str = "main";

/// Build the platform bootstrap command. Runs in headless mode
/// (`MAVERICK_NO_WIZARD`) so the install completes without the
/// interactive wizard, which a GUI can't drive over a pipe.
fn bootstrap_command() -> Command {
    #[cfg(windows)]
    {
        let url =
            format!("https://raw.githubusercontent.com/{REPO}/{GIT_REF}/deploy/desktop/install.ps1");
        let script = format!("$env:MAVERICK_NO_WIZARD='1'; irm {url} | iex");
        let mut c = Command::new("powershell");
        c.args([
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            &script,
        ]);
        c
    }
    #[cfg(not(windows))]
    {
        let url =
            format!("https://raw.githubusercontent.com/{REPO}/{GIT_REF}/deploy/desktop/install.sh");
        let script = format!("export MAVERICK_NO_WIZARD=1; curl -fsSL {url} | bash");
        let mut c = Command::new("bash");
        c.args(["-c", &script]);
        c
    }
}

/// Run the bootstrap, streaming stdout+stderr to the UI as `install-log`
/// events, then emit `install-done` (success) or `install-failed`.
#[tauri::command]
async fn install(app: AppHandle) -> Result<(), String> {
    let mut cmd = bootstrap_command();
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("Could not start the installer: {e}"))?;

    let stdout = child.stdout.take().ok_or("no stdout handle")?;
    let stderr = child.stderr.take().ok_or("no stderr handle")?;

    // The scripts log progress to stderr and results to stdout; surface
    // both as one event stream so the user sees everything.
    let a = app.clone();
    let out = tokio::spawn(async move {
        let mut lines = BufReader::new(stdout).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            let _ = a.emit("install-log", line);
        }
    });
    let a = app.clone();
    let err = tokio::spawn(async move {
        let mut lines = BufReader::new(stderr).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            let _ = a.emit("install-log", line);
        }
    });

    let status = child.wait().await.map_err(|e| e.to_string())?;
    let _ = out.await;
    let _ = err.await;

    if status.success() {
        let _ = app.emit("install-done", ());
        Ok(())
    } else {
        let msg = format!(
            "The installer exited with an error (code {:?}).",
            status.code()
        );
        let _ = app.emit("install-failed", msg.clone());
        Err(msg)
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![install])
        .run(tauri::generate_context!())
        .expect("tauri runtime error");
}
