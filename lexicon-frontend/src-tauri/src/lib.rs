use tauri::Manager;

/// Toggle main window visibility — called from frontend via IPC.
#[tauri::command]
fn toggle_window(app: tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.set_fullscreen(false);
            let _ = window.hide();
            eprintln!("[lexicon] window hidden");
        } else {
            let _ = window.show();
            let _ = window.set_fullscreen(true);
            let _ = window.set_focus();
            eprintln!("[lexicon] window shown + fullscreen");
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![toggle_window])
        .setup(|app| {
            // Window starts visible so the WebView boots and JS executes
            // (hidden windows don't run JS on GNOME Wayland).
            // We hide it after a brief delay once the WebView has loaded.
            if let Some(window) = app.get_webview_window("main") {
                let w = window.clone();
                std::thread::spawn(move || {
                    // Give the WebView time to load and establish the WebSocket
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
