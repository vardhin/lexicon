use tauri::Manager;

use std::sync::atomic::{AtomicBool, Ordering};

/// Track whether the main overlay is visible.
static OVERLAY_VISIBLE: AtomicBool = AtomicBool::new(false);

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

// ── App entry ──────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            toggle_window,
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
