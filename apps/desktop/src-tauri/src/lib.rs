// RoadTwin Tauri shell — Phase 1: sidecar spawn + /health handshake
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::ShellExt;

#[derive(Default)]
pub struct SidecarState {
    pub port: u16,
    pub child: Option<tauri_plugin_shell::process::CommandChild>,
    /// OS pid of the spawned sidecar. Kept separately from `child` because the
    /// fallback spawn path below produces a std::process::Child, not a
    /// CommandChild, and because CommandChild::kill() consumes the handle --
    /// we still need the pid after that to verify the tree is gone.
    pub pid: Option<u32>,
}

/// Terminate the sidecar and everything it spawned.
///
/// api.exe is a PyInstaller ONEFILE binary: the bootloader process extracts the
/// payload to %TEMP%\_MEIxxxx and launches a SECOND process which is the one
/// that actually binds the port. Killing only the pid we spawned therefore
/// leaves the real server alive -- that is exactly the orphan observed in P1
/// verification (app closed, 2 api.exe survived, :8765 still served /health,
/// and the next launch silently attached to the zombie instead of spawning).
///
/// So kill the whole process TREE, then confirm the port is actually released
/// before letting the app exit.
fn shutdown_sidecar(state: &Arc<Mutex<SidecarState>>) {
    let (child, pid, port) = {
        // Scoped so the mutex is released before we block on taskkill/polling.
        match state.lock() {
            Ok(mut guard) => (guard.child.take(), guard.pid.take(), guard.port),
            // A poisoned mutex must not stop shutdown -- that would orphan the
            // sidecar, which is the whole bug we are fixing.
            Err(poisoned) => {
                let mut guard = poisoned.into_inner();
                (guard.child.take(), guard.pid.take(), guard.port)
            }
        }
    };

    if let Some(pid) = pid {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            // /T = tree (gets the extracted PyInstaller child), /F = force.
            // Non-zero exit just means it was already gone; not an error here.
            let _ = std::process::Command::new("taskkill")
                .args(["/PID", &pid.to_string(), "/T", "/F"])
                .creation_flags(CREATE_NO_WINDOW)
                .status();
        }
        #[cfg(not(windows))]
        {
            let _ = std::process::Command::new("kill")
                .args(["-9", &pid.to_string()])
                .status();
        }
    }

    // Belt and braces: if the plugin still holds a live handle, close it too.
    // Already-dead is fine -- kill() returns Err rather than panicking.
    if let Some(c) = child {
        let _ = c.kill();
    }

    // Wait (bounded) for :8765 to stop answering, so a restart cannot race the
    // dying process and mistake it for its own sidecar. Capped at ~2 s: this
    // runs on the exit path and must never hang the app on shutdown.
    if port != 0 {
        use std::time::Duration;
        let url = format!("http://127.0.0.1:{}/health", port);
        for _ in 0..20 {
            if ureq::get(&url)
                .timeout(Duration::from_millis(150))
                .call()
                .is_err()
            {
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        eprintln!("sidecar still answering on :{port} after shutdown wait");
    }
}

fn wait_for_health(port: u16, timeout_secs: u64) -> Result<(), String> {
    use std::time::{Duration, Instant};
    let url = format!("http://127.0.0.1:{}/health", port);
    let deadline = Instant::now() + Duration::from_secs(timeout_secs);
    loop {
        if let Ok(resp) = ureq::get(&url).call() {
            if resp.status() == 200 {
                return Ok(());
            }
        }
        if Instant::now() > deadline {
            return Err(format!(
                "Sidecar did not respond on :{} within {}s",
                port, timeout_secs
            ));
        }
        std::thread::sleep(Duration::from_millis(300));
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .manage(Arc::new(Mutex::new(SidecarState::default())))
        .setup(|app| {
            let port: u16 = 8765;

            // Attempt to spawn sidecar via Tauri shell plugin
            let sidecar_res = app
                .shell()
                .sidecar("api")
                .map(|cmd| cmd.env("ROADTWIN_PORT", port.to_string()))
                .and_then(|cmd| cmd.spawn());

            match sidecar_res {
                Ok((_rx, child)) => {
                    let state = app.state::<Arc<Mutex<SidecarState>>>();
                    let mut guard = state.lock().unwrap();
                    guard.port = port;
                    guard.pid = Some(child.pid());
                    guard.child = Some(child);
                }
                Err(e) => {
                    eprintln!("Sidecar spawn via plugin failed: {e}. Trying std::process::Command...");
                    // Fallback to direct executable spawn next to current exe or in resources
                    if let Ok(current_exe) = std::env::current_exe() {
                        let exe_dir = current_exe.parent().unwrap_or(std::path::Path::new("."));
                        let candidates = [
                            exe_dir.join("api.exe"),
                            exe_dir.join("api-x86_64-pc-windows-msvc.exe"),
                            exe_dir.join("binaries").join("api-x86_64-pc-windows-msvc.exe"),
                        ];
                        for candidate in &candidates {
                            if candidate.exists() {
                                // Record the pid. This path used to discard the
                                // handle entirely, so a sidecar started by the
                                // fallback could never be shut down.
                                if let Ok(ch) = std::process::Command::new(candidate)
                                    .env("ROADTWIN_PORT", port.to_string())
                                    .spawn()
                                {
                                    let state = app.state::<Arc<Mutex<SidecarState>>>();
                                    let mut guard = state.lock().unwrap();
                                    guard.port = port;
                                    guard.pid = Some(ch.id());
                                }
                                break;
                            }
                        }
                    }
                }
            }

            // Wait for /health in a background thread, then emit event to UI
            let handle: AppHandle = app.handle().clone();
            std::thread::spawn(move || {
                match wait_for_health(port, 20) {
                    Ok(()) => {
                        let _ = handle.emit("sidecar-ready", port);
                    }
                    Err(msg) => {
                        eprintln!("Health check error: {msg}");
                        let _ = handle.emit("sidecar-error", msg);
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // Exit is the last event before the process goes away, and it fires
            // however the app was closed (window X, task bar, quit). Without
            // this the sidecar was simply left running.
            if let tauri::RunEvent::Exit = event {
                let state = app_handle.state::<Arc<Mutex<SidecarState>>>();
                shutdown_sidecar(&state);
            }
        });
}
