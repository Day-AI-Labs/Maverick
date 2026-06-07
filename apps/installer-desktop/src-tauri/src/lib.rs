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

use std::fs;
use std::io::Write;
use std::process::Stdio;
use tauri::{AppHandle, Emitter};
use tempfile::TempDir;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;

// Source the installer pulls from. The desktop installer always pins
// the checkout to the commit captured when the signed app was built.
const REPO: &str = "Day-AI-Labs/Maverick";
const GIT_REF: &str = env!("MAVERICK_INSTALL_REF");

#[cfg(windows)]
const INSTALL_SCRIPT: &str = include_str!("../../../../deploy/desktop/install.ps1");
#[cfg(not(windows))]
const INSTALL_SCRIPT: &str = include_str!("../../../../deploy/desktop/install.sh");

/// Build the platform bootstrap command. Runs in headless mode
/// (`MAVERICK_NO_WIZARD`) so the install completes without the
/// interactive wizard, which a GUI can't drive over a pipe.
struct BootstrapCommand {
    command: Command,
    _script_dir: TempDir,
}

fn stage_install_script() -> Result<(TempDir, std::path::PathBuf), String> {
    let extension = if cfg!(windows) { "ps1" } else { "sh" };
    let script_dir = tempfile::Builder::new()
        .prefix("maverick-install-")
        .tempdir()
        .map_err(|e| format!("Could not create a private installer staging directory: {e}"))?;
    let script_path = script_dir.path().join(format!("install.{extension}"));
    let mut script = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&script_path)
        .map_err(|e| format!("Could not create the staged installer script: {e}"))?;
    script
        .write_all(INSTALL_SCRIPT.as_bytes())
        .and_then(|_| script.sync_all())
        .map_err(|e| format!("Could not write the bundled installer script: {e}"))?;
    Ok((script_dir, script_path))
}

fn bootstrap_command() -> Result<BootstrapCommand, String> {
    let (script_dir, script_path) = stage_install_script()?;

    #[cfg(windows)]
    {
        let mut command = Command::new("powershell");
        command.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]);
        command.arg(&script_path);
        command
            .env("MAVERICK_NO_WIZARD", "1")
            .env("MAVERICK_REPO", REPO)
            .env("MAVERICK_REF", GIT_REF);
        Ok(BootstrapCommand {
            command,
            _script_dir: script_dir,
        })
    }
    #[cfg(not(windows))]
    {
        let mut command = Command::new("bash");
        command.arg(&script_path);
        command
            .env("MAVERICK_NO_WIZARD", "1")
            .env("MAVERICK_REPO", REPO)
            .env("MAVERICK_REF", GIT_REF);
        Ok(BootstrapCommand {
            command,
            _script_dir: script_dir,
        })
    }
}

/// Run the bootstrap, streaming stdout+stderr to the UI as `install-log`
/// events, then emit `install-done` (success) or `install-failed`.
#[tauri::command]
async fn install(app: AppHandle) -> Result<(), String> {
    let mut bootstrap = bootstrap_command()?;
    bootstrap
        .command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = bootstrap
        .command
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
