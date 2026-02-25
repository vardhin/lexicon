use tauri::Manager;
use tauri::WebviewUrl;
use tauri::webview::WebviewBuilder;

use std::sync::LazyLock;
use std::sync::atomic::{AtomicBool, Ordering};

static BRAIN_URL: &str = "http://127.0.0.1:8000";

/// Track WhatsApp organ visibility ourselves since Webview has no is_visible().
static WA_VISIBLE: AtomicBool = AtomicBool::new(false);
/// Track whether the organ has been created.
static WA_CREATED: AtomicBool = AtomicBool::new(false);

/// Reusable HTTP client.
static HTTP: LazyLock<reqwest::blocking::Client> = LazyLock::new(|| {
    reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .pool_max_idle_per_host(2)
        .build()
        .unwrap()
});

/// Toggle main window visibility — called from frontend or global hotkey.
#[tauri::command]
fn toggle_window(app: tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if window.is_visible().unwrap_or(false) {
            // Also hide the WhatsApp child webview if it's showing
            if WA_VISIBLE.load(Ordering::Relaxed) {
                if let Some(wa) = app.get_webview("whatsapp-organ") {
                    let _ = wa.hide();
                    WA_VISIBLE.store(false, Ordering::Relaxed);
                }
            }
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

// ── WhatsApp Organ (child webview) ─────────────────────────────
//
// WhatsApp is a CHILD WEBVIEW inside the same main Tauri window.
// This means: one window, one compositor surface, zero stuttering.
//
// The child webview sits on top of the main Lexicon webview.
// Toggling it is just webview.show()/hide() — no window switching.
// It uses .auto_resize() so it always fills the window.
//
// Flow:
//   "open whatsapp" → create child webview (or show it)
//   "back" / Escape → hide the child webview (Lexicon shows through)
//   monitor.js      → scans DOM → batches → Tauri IPC → Rust → Brain
//

/// Create the WhatsApp organ webview as a child of the main window.
/// If it already exists, just show it.
#[tauri::command]
fn open_whatsapp_organ(app: tauri::AppHandle) {
    // Already exists — just show it
    if WA_CREATED.load(Ordering::Relaxed) {
        if let Some(wa) = app.get_webview("whatsapp-organ") {
            let _ = wa.show();
            WA_VISIBLE.store(true, Ordering::Relaxed);
            eprintln!("[lexicon] WhatsApp organ shown (existing)");
            return;
        }
    }

    // Get the underlying Window (not WebviewWindow) — add_child lives on Window
    let Some(window) = app.get_window("main") else {
        eprintln!("[lexicon] No main window found");
        return;
    };

    let injection_js = include_str!("../injections/whatsapp_monitor.js");

    let builder = WebviewBuilder::new(
        "whatsapp-organ",
        WebviewUrl::External("https://web.whatsapp.com".parse().unwrap()),
    )
    .initialization_script(injection_js)
    .auto_resize();

    let size = window
        .inner_size()
        .unwrap_or(tauri::PhysicalSize::new(1920, 1080));

    match window.add_child(
        builder,
        tauri::LogicalPosition::new(0.0, 0.0),
        tauri::LogicalSize::new(size.width as f64, size.height as f64),
    ) {
        Ok(_wv) => {
            WA_CREATED.store(true, Ordering::Relaxed);
            WA_VISIBLE.store(true, Ordering::Relaxed);
            eprintln!("[lexicon] WhatsApp organ created as child webview");
        }
        Err(e) => {
            eprintln!("[lexicon] Failed to create WhatsApp organ: {e}");
        }
    }
}

/// Show or hide the WhatsApp organ webview.
#[tauri::command]
fn show_whatsapp_organ(app: tauri::AppHandle, visible: bool) {
    if let Some(wa) = app.get_webview("whatsapp-organ") {
        if visible {
            let _ = wa.show();
            WA_VISIBLE.store(true, Ordering::Relaxed);
            eprintln!("[lexicon] WhatsApp organ shown");
        } else {
            let _ = wa.hide();
            WA_VISIBLE.store(false, Ordering::Relaxed);
            eprintln!("[lexicon] WhatsApp organ hidden");
        }
    }
}

/// "Close" the organ — we just hide it. The webview stays loaded
/// so WhatsApp remains logged in and the monitor keeps running.
#[tauri::command]
fn close_whatsapp_organ(app: tauri::AppHandle) {
    if let Some(wa) = app.get_webview("whatsapp-organ") {
        let _ = wa.hide();
        WA_VISIBLE.store(false, Ordering::Relaxed);
        eprintln!("[lexicon] WhatsApp organ hidden (close)");
    }
}

/// Get organ status: "closed" | "visible" | "background"
#[tauri::command]
fn whatsapp_organ_status(_app: tauri::AppHandle) -> String {
    if !WA_CREATED.load(Ordering::Relaxed) {
        "closed".to_string()
    } else if WA_VISIBLE.load(Ordering::Relaxed) {
        "visible".to_string()
    } else {
        "background".to_string()
    }
}

// ── IPC Relay ──────────────────────────────────────────────────
// Called from the injected JS in the WhatsApp child webview.
// Tauri IPC works because the child webview is part of the Tauri app.

/// Relay a batch of WhatsApp messages to the Brain.
#[tauri::command]
fn wa_relay_batch(payload: String) {
    std::thread::spawn(move || {
        match HTTP
            .post(format!("{}/whatsapp/batch", BRAIN_URL))
            .header("Content-Type", "application/json")
            .body(payload)
            .send()
        {
            Ok(resp) => eprintln!("[lexicon] wa_relay_batch → Brain: {}", resp.status()),
            Err(e) => eprintln!("[lexicon] wa_relay_batch failed: {e}"),
        }
    });
}

/// Relay a WhatsApp status update to the Brain.
#[tauri::command]
fn wa_relay_status(status: String) {
    std::thread::spawn(move || {
        let body = format!(
            r#"{{"status":"{}","timestamp":"{}"}}"#,
            status,
            chrono::Utc::now().to_rfc3339()
        );
        match HTTP
            .post(format!("{}/whatsapp/status", BRAIN_URL))
            .header("Content-Type", "application/json")
            .body(body)
            .send()
        {
            Ok(resp) => eprintln!("[lexicon] wa_relay_status({status}) → Brain: {}", resp.status()),
            Err(e) => eprintln!("[lexicon] wa_relay_status failed: {e}"),
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
            wa_relay_batch,
            wa_relay_status,
        ])
        .setup(|app| {
            // Window starts visible so the WebView boots and JS executes.
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
