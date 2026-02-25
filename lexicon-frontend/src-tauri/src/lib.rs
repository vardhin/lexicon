use tauri::Manager;

use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};

/// Track whether the main overlay is visible.
static OVERLAY_VISIBLE: AtomicBool = AtomicBool::new(false);

/// WhatsApp organ process PID — None if not running.
static WA_PID: Mutex<Option<u32>> = Mutex::new(None);

/// Path to the WhatsApp organ Python script.
fn wa_organ_script() -> String {
    // Try multiple locations
    let candidates = [
        // Development path (relative to Cargo.toml)
        Some(format!(
            "{}/organs/whatsapp_organ.py",
            env!("CARGO_MANIFEST_DIR")
        )),
    ];
    for c in &candidates {
        if let Some(path) = c {
            if std::path::Path::new(path).exists() {
                return path.clone();
            }
        }
    }
    // Fallback
    format!("{}/organs/whatsapp_organ.py", env!("CARGO_MANIFEST_DIR"))
}

// ── Toggle main overlay ────────────────────────────────────────

#[tauri::command]
fn toggle_window(app: tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.set_always_on_top(false);
            let _ = window.set_fullscreen(false);
            let _ = window.hide();
            OVERLAY_VISIBLE.store(false, Ordering::Relaxed);
            eprintln!("[lexicon] window hidden");
        } else {
            let _ = window.show();
            let _ = window.set_always_on_top(true);
            let _ = window.set_fullscreen(true);
            let _ = window.set_focus();
            OVERLAY_VISIBLE.store(true, Ordering::Relaxed);
            eprintln!("[lexicon] window shown + fullscreen");
        }
    }
}

// ── WhatsApp Organ (separate OS process) ───────────────────────
//
// Architecture:
//   WhatsApp runs in a SEPARATE PROCESS (whatsapp_organ.py) using
//   WebKitGTK — its own window, its own compositor surface.
//
//   Communication:
//     Tauri → Organ:   Unix signals (SIGUSR1 toggle, SIGUSR2 focus, SIGTERM kill)
//     Organ → Brain:   HTTP POST (messages, status, debug snapshots)
//     Brain → Tauri:   WebSocket broadcast (Svelte receives and renders)
//
//   Why not a child webview?
//     - External HTTPS pages (web.whatsapp.com) can't fetch() to localhost HTTP
//     - No Tauri IPC available in external-origin webviews
//     - Child webview captures all keyboard/mouse input
//     - Focus management between webviews is impossible
//
//   The organ process writes its PID to /tmp/lexicon-whatsapp.pid.
//   We read that PID and signal it. Simple, reliable, zero overhead.
//

/// Spawn the WhatsApp organ as a separate process.
/// If already running, just bring it to front.
#[tauri::command]
fn open_whatsapp_organ() -> Result<String, String> {
    let mut pid_lock = WA_PID.lock().map_err(|e| e.to_string())?;

    // Check if already running (via PID file first, then our tracked PID)
    if let Some(pid) = read_pid_file().or(*pid_lock) {
        if is_process_alive(pid) {
            *pid_lock = Some(pid);
            // Bring to front (SIGUSR2)
            send_signal(pid, libc::SIGUSR2);
            eprintln!("[lexicon] WhatsApp organ brought to front (PID {pid})");
            return Ok("visible".to_string());
        }
    }

    // Spawn new process
    let script = wa_organ_script();
    eprintln!("[lexicon] Spawning WhatsApp organ: python3 {script}");

    let child = std::process::Command::new("python3")
        .arg(&script)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn WhatsApp organ: {e}"))?;

    let child_pid = child.id();
    *pid_lock = Some(child_pid);
    eprintln!("[lexicon] WhatsApp organ spawned, PID={child_pid}");

    // Detach — let the process run independently
    std::mem::forget(child);

    Ok("launched".to_string())
}

/// Show or hide the WhatsApp organ window.
#[tauri::command]
fn show_whatsapp_organ(visible: bool) -> Result<(), String> {
    let pid = get_wa_pid().ok_or("WhatsApp organ not running")?;

    if visible {
        send_signal(pid, libc::SIGUSR2);
        eprintln!("[lexicon] WhatsApp organ: show (SIGUSR2)");
    } else {
        send_signal(pid, libc::SIGUSR1);
        eprintln!("[lexicon] WhatsApp organ: hide (SIGUSR1)");
    }
    Ok(())
}

/// Close/kill the WhatsApp organ process.
#[tauri::command]
fn close_whatsapp_organ() -> Result<(), String> {
    let mut pid_lock = WA_PID.lock().map_err(|e| e.to_string())?;

    // Kill via PID file too (in case we lost track)
    if let Some(pid) = read_pid_file().or(*pid_lock) {
        if is_process_alive(pid) {
            send_signal(pid, libc::SIGTERM);
            eprintln!("[lexicon] WhatsApp organ killed (SIGTERM), PID={pid}");
        }
    }
    *pid_lock = None;

    // Clean up PID file
    let _ = std::fs::remove_file("/tmp/lexicon-whatsapp.pid");
    Ok(())
}

/// Get organ status: "closed" | "running"
#[tauri::command]
fn whatsapp_organ_status() -> String {
    if let Some(pid) = get_wa_pid() {
        if is_process_alive(pid) {
            return "running".to_string();
        }
    }
    "closed".to_string()
}

// ── Helpers ────────────────────────────────────────────────────

fn read_pid_file() -> Option<u32> {
    std::fs::read_to_string("/tmp/lexicon-whatsapp.pid")
        .ok()
        .and_then(|s| s.trim().parse().ok())
}

fn get_wa_pid() -> Option<u32> {
    // Check PID file first (organ writes it), then our tracked PID
    if let Some(pid) = read_pid_file() {
        if is_process_alive(pid) {
            // Update tracking
            if let Ok(mut lock) = WA_PID.lock() {
                *lock = Some(pid);
            }
            return Some(pid);
        }
    }
    if let Ok(lock) = WA_PID.lock() {
        if let Some(pid) = *lock {
            if is_process_alive(pid) {
                return Some(pid);
            }
        }
    }
    None
}

fn is_process_alive(pid: u32) -> bool {
    unsafe { libc::kill(pid as i32, 0) == 0 }
}

fn send_signal(pid: u32, sig: i32) {
    unsafe {
        libc::kill(pid as i32, sig);
    }
}

// ── App entry ──────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            toggle_window,
            open_whatsapp_organ,
            show_whatsapp_organ,
            close_whatsapp_organ,
            whatsapp_organ_status,
        ])
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                let w = window.clone();
                std::thread::spawn(move || {
                    std::thread::sleep(std::time::Duration::from_secs(2));
                    let _ = w.hide();
                    eprintln!("[lexicon] WebView booted → window hidden (waiting for toggle)");
                });
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
