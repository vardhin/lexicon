use tauri::Manager;
use tauri::WebviewUrl;
use tauri::webview::WebviewWindowBuilder;

static BRAIN_URL: &str = "http://127.0.0.1:8000";

/// Helper: hide one window, then show another with a small gap
/// so the compositor doesn't fight between two fullscreen surfaces.
fn switch_window(from: &tauri::WebviewWindow, to: &tauri::WebviewWindow) {
    // Step 1: de-fullscreen the outgoing window
    let _ = from.set_always_on_top(false);
    let _ = from.set_fullscreen(false);
    // Step 2: hide it
    let _ = from.hide();
    // Step 3: small delay to let the compositor release the surface
    std::thread::sleep(std::time::Duration::from_millis(80));
    // Step 4: show + fullscreen the incoming window
    let _ = to.show();
    let _ = to.set_always_on_top(true);
    let _ = to.set_fullscreen(true);
    let _ = to.set_focus();
}

/// Toggle main window visibility — called from frontend via IPC.
/// Also handles the case where the WhatsApp organ is visible:
/// if WhatsApp is showing, hide it and restore main instead.
#[tauri::command]
fn toggle_window(app: tauri::AppHandle) {
    // If WhatsApp organ is visible, hide it and show main
    if let Some(wa) = app.get_webview_window("whatsapp-organ") {
        if wa.is_visible().unwrap_or(false) {
            if let Some(main) = app.get_webview_window("main") {
                switch_window(&wa, &main);
            }
            eprintln!("[lexicon] toggle: WhatsApp hidden → main restored");
            return;
        }
    }

    // Normal toggle of main window
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.set_always_on_top(false);
            let _ = window.set_fullscreen(false);
            let _ = window.hide();
            eprintln!("[lexicon] window hidden");
        } else {
            let _ = window.show();
            let _ = window.set_always_on_top(true);
            let _ = window.set_fullscreen(true);
            let _ = window.set_focus();
            eprintln!("[lexicon] window shown + fullscreen");
        }
    }
}

// ── WhatsApp Organ ─────────────────────────────────────────────
//
// The WhatsApp organ is a real web.whatsapp.com tab running in its own
// WebviewWindow. It is NOT headless — the user can switch to it to:
//   - Scan the QR code and log in
//   - Browse full chats, read messages, etc.
//
// When the user is on the main Lexicon canvas, the WhatsApp window is
// hidden but still running. The injected monitor.js POSTs incoming
// messages to the Brain (http://127.0.0.1:8000/whatsapp/message).
//
// Flow:
//   sidebar 💬 / "whatsapp open" → open_whatsapp_organ()
//                                    → creates WhatsApp window (or shows it)
//   sidebar 💬 again / Escape      → show_whatsapp_organ(false) hides it
//   User logs in via QR             → monitor.js starts observing DOM
//   New message arrives              → POST to Brain → broadcast to frontend
//

/// Create the WhatsApp organ window if it doesn't exist.
/// If it already exists, just bring it to front.
#[tauri::command]
fn open_whatsapp_organ(app: tauri::AppHandle) {
    // Already exists — just show it
    if let Some(wa) = app.get_webview_window("whatsapp-organ") {
        if let Some(main) = app.get_webview_window("main") {
            switch_window(&main, &wa);
        } else {
            let _ = wa.show();
            let _ = wa.set_always_on_top(true);
            let _ = wa.set_fullscreen(true);
            let _ = wa.set_focus();
        }
        eprintln!("[lexicon] WhatsApp organ brought to front");
        return;
    }

    // Create the WhatsApp window — do NOT set always_on_top here,
    // we'll set it after build so the compositor doesn't fight.
    let injection_js = include_str!("../injections/whatsapp_monitor.js");

    let builder = WebviewWindowBuilder::new(
        &app,
        "whatsapp-organ",
        WebviewUrl::External("https://web.whatsapp.com".parse().unwrap()),
    )
    .title("Lexicon — WhatsApp")
    .inner_size(1920.0, 1080.0)
    .decorations(false)
    .initialization_script(injection_js);

    match builder.build() {
        Ok(wv) => {
            // Hide main first, then bring WhatsApp to fullscreen
            if let Some(main) = app.get_webview_window("main") {
                let _ = main.set_always_on_top(false);
                let _ = main.set_fullscreen(false);
                let _ = main.hide();
            }
            std::thread::sleep(std::time::Duration::from_millis(100));
            let _ = wv.set_always_on_top(true);
            let _ = wv.set_fullscreen(true);
            let _ = wv.set_focus();
            eprintln!("[lexicon] WhatsApp organ created (fullscreen)");
        }
        Err(e) => {
            eprintln!("[lexicon] failed to create WhatsApp organ: {e}");
        }
    }
}

/// Show or hide the WhatsApp organ window.
/// When hiding, bring the main Lexicon window back.
#[tauri::command]
fn show_whatsapp_organ(app: tauri::AppHandle, visible: bool) {
    if let Some(wa) = app.get_webview_window("whatsapp-organ") {
        if visible {
            // Switch: main → WhatsApp
            if let Some(main) = app.get_webview_window("main") {
                switch_window(&main, &wa);
            } else {
                let _ = wa.show();
                let _ = wa.set_always_on_top(true);
                let _ = wa.set_fullscreen(true);
                let _ = wa.set_focus();
            }
            eprintln!("[lexicon] WhatsApp organ shown");
        } else {
            // Switch: WhatsApp → main
            if let Some(main) = app.get_webview_window("main") {
                switch_window(&wa, &main);
            } else {
                let _ = wa.set_always_on_top(false);
                let _ = wa.set_fullscreen(false);
                let _ = wa.hide();
            }
            eprintln!("[lexicon] WhatsApp organ hidden → main restored");
        }
    }
}

/// Destroy the WhatsApp organ entirely.
#[tauri::command]
fn close_whatsapp_organ(app: tauri::AppHandle) {
    if let Some(wa) = app.get_webview_window("whatsapp-organ") {
        let _ = wa.set_always_on_top(false);
        let _ = wa.set_fullscreen(false);
        let _ = wa.hide();
        std::thread::sleep(std::time::Duration::from_millis(80));
        let _ = wa.destroy();
        // Bring main back if needed
        if let Some(main) = app.get_webview_window("main") {
            let _ = main.show();
            let _ = main.set_always_on_top(true);
            let _ = main.set_fullscreen(true);
            let _ = main.set_focus();
        }
        eprintln!("[lexicon] WhatsApp organ destroyed");
    }
}

/// Get the current state of the WhatsApp organ.
/// Returns: "closed" | "visible" | "background"
#[tauri::command]
fn whatsapp_organ_status(app: tauri::AppHandle) -> String {
    match app.get_webview_window("whatsapp-organ") {
        Some(wa) => {
            if wa.is_visible().unwrap_or(false) {
                "visible".to_string()
            } else {
                "background".to_string()
            }
        }
        None => "closed".to_string(),
    }
}

// ── IPC Relay commands ─────────────────────────────────────────
// Called from the injected JS in the WhatsApp webview.
// Tauri IPC bypasses CSP so this works even on web.whatsapp.com.
// We forward the data to the Brain via HTTP from the Rust side.

/// Relay a WhatsApp message from the injected monitor to the Brain.
#[tauri::command]
fn wa_relay_message(payload: String) {
    std::thread::spawn(move || {
        let client = reqwest::blocking::Client::new();
        match client
            .post(format!("{}/whatsapp/message", BRAIN_URL))
            .header("Content-Type", "application/json")
            .body(payload)
            .send()
        {
            Ok(resp) => {
                eprintln!("[lexicon] wa_relay_message → Brain: {}", resp.status());
            }
            Err(e) => {
                eprintln!("[lexicon] wa_relay_message failed: {e}");
            }
        }
    });
}

/// Relay a WhatsApp status update from the injected monitor to the Brain.
#[tauri::command]
fn wa_relay_status(status: String) {
    std::thread::spawn(move || {
        let body = format!(
            r#"{{"status":"{}","timestamp":"{}"}}"#,
            status,
            chrono::Utc::now().to_rfc3339()
        );
        let client = reqwest::blocking::Client::new();
        match client
            .post(format!("{}/whatsapp/status", BRAIN_URL))
            .header("Content-Type", "application/json")
            .body(body)
            .send()
        {
            Ok(resp) => {
                eprintln!("[lexicon] wa_relay_status({status}) → Brain: {}", resp.status());
            }
            Err(e) => {
                eprintln!("[lexicon] wa_relay_status failed: {e}");
            }
        }
    });
}

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
            wa_relay_message,
            wa_relay_status,
        ])
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
