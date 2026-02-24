use tauri::Manager;
use std::process::Command;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }

            // Force fullscreen via Hyprland IPC after window maps
            std::thread::spawn(|| {
                std::thread::sleep(std::time::Duration::from_millis(800));
                // Focus the lexicon window first, then fullscreen it
                let _ = Command::new("hyprctl")
                    .args(["dispatch", "focuswindow", "class:Lexicon-frontend"])
                    .output();
                std::thread::sleep(std::time::Duration::from_millis(200));
                let _ = Command::new("hyprctl")
                    .args(["dispatch", "fullscreen", "0"])
                    .output();
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
