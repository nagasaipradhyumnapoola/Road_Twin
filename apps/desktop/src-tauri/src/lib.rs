// RoadTwin Tauri shell — Phase 1: sidecar spawn + /health handshake
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::ShellExt;

#[derive(Default)]
pub struct SidecarState {
    pub port: u16,
    pub child: Option<tauri_plugin_shell::process::CommandChild>,
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
                                let _ = std::process::Command::new(candidate)
                                    .env("ROADTWIN_PORT", port.to_string())
                                    .spawn();
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
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
