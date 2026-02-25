#!/usr/bin/env python3
"""
WhatsApp Organ — standalone WebKitGTK browser for web.whatsapp.com.

This runs as a SEPARATE OS process from the Tauri app, using its own
WebKitGTK instance. This completely eliminates the GPU/compositor
stuttering caused by sharing a WebKit process with the main UI.

Architecture:
  Tauri spawns this script → it opens a fullscreen WebKit window
  → user logs into WhatsApp → injected JS monitors DOM for messages
  → messages are POSTed directly to the Brain (localhost:8000)
  → Brain broadcasts to the Tauri frontend via WebSocket

Communication:
  - Tauri → this process: spawns/kills via shell, sends SIGUSR1 to toggle visibility
  - This process → Brain: HTTP POST /whatsapp/batch, /whatsapp/status
  - Brain → Tauri frontend: WebSocket broadcast

The PID is written to /tmp/lexicon-whatsapp.pid so Tauri can signal it.
"""

import gi
import json
import os
import signal
import sys

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")

from gi.repository import Gtk, WebKit, GLib, Gdk  # noqa: E402


BRAIN_URL = "http://127.0.0.1:8000"
PID_FILE = "/tmp/lexicon-whatsapp.pid"

# The JavaScript to inject into web.whatsapp.com
MONITOR_JS = None


def load_monitor_js():
    """Load the monitor script from the injections directory."""
    global MONITOR_JS
    # Try multiple paths
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "..", "injections", "whatsapp_organ_monitor.js"),
        os.path.join(here, "whatsapp_organ_monitor.js"),
    ]
    for path in candidates:
        path = os.path.normpath(path)
        if os.path.isfile(path):
            with open(path, "r") as f:
                MONITOR_JS = f.read()
            print(f"[wa-organ] Loaded monitor JS from {path}")
            return
    print("[wa-organ] WARNING: No monitor JS found, using minimal stub")
    MONITOR_JS = "console.log('[lexicon/wa] organ monitor stub loaded');"


class WhatsAppOrgan(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.vardhin.lexicon.whatsapp")
        self.window = None
        self.webview = None
        self._visible = True

    def do_activate(self):
        if self.window:
            self.window.present()
            return

        # ── Window setup ──
        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title("Lexicon — WhatsApp")
        self.window.set_default_size(1920, 1080)
        self.window.set_decorated(False)

        # ── WebView setup ──
        # Use a separate network session so cookies/storage don't collide
        # with the Tauri webview's session.
        data_dir = os.path.expanduser("~/.local/share/lexicon/whatsapp")
        cache_dir = os.path.expanduser("~/.cache/lexicon/whatsapp")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)

        network_session = WebKit.NetworkSession.new(
            data_dir, cache_dir
        )

        self.webview = WebKit.WebView(network_session=network_session)

        settings = self.webview.get_settings()
        settings.set_enable_javascript(True)
        settings.set_javascript_can_access_clipboard(True)
        settings.set_enable_developer_extras(True)
        settings.set_enable_media_stream(True)  # For voice/video calls
        settings.set_enable_webaudio(True)
        settings.set_hardware_acceleration_policy(
            WebKit.HardwareAccelerationPolicy.ALWAYS
        )
        # Set a real browser user-agent so WhatsApp doesn't block us
        settings.set_user_agent(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        self.webview.set_settings(settings)

        # ── Inject the monitor script when pages load ──
        content_manager = self.webview.get_user_content_manager()
        script = WebKit.UserScript.new(
            MONITOR_JS,
            WebKit.UserContentInjectedFrames.TOP_FRAME,
            WebKit.UserScriptInjectionTime.END,
            None,  # allow list (None = all)
            None,  # block list
        )
        content_manager.add_script(script)

        # ── Register message handler for JS → Python communication ──
        content_manager.register_script_message_handler("lexicon")
        content_manager.connect("script-message-received::lexicon", self._on_script_message)

        # Load WhatsApp
        self.webview.load_uri("https://web.whatsapp.com")

        self.window.set_child(self.webview)
        self.window.fullscreen()
        self.window.present()

        # Write PID file so Tauri can signal us
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))

        print(f"[wa-organ] Window created, PID={os.getpid()}")

        # ── Signal handlers ──
        # SIGUSR1 = toggle visibility (Tauri sends this)
        # SIGUSR2 = bring to front
        # SIGTERM = clean shutdown
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR1, self._toggle_visibility)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGUSR2, self._bring_to_front)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, self._shutdown)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, self._shutdown)

    def _on_script_message(self, content_manager, js_result):
        """Handle messages from the injected JS via window.webkit.messageHandlers.lexicon."""
        try:
            msg_str = js_result.to_string()
            msg = json.loads(msg_str)
            action = msg.get("action")

            if action == "back_to_lexicon":
                self._hide_window()
            elif action == "status":
                self._relay_status(msg.get("status", "unknown"))
            # batch/message relay is handled directly by fetch() in the JS
            # since this process doesn't share CSP with WhatsApp
        except Exception as e:
            print(f"[wa-organ] Script message error: {e}")

    def _toggle_visibility(self):
        """SIGUSR1 handler — toggle window visibility."""
        if self._visible:
            self._hide_window()
        else:
            self._show_window()
        return True  # Keep the signal handler registered

    def _bring_to_front(self):
        """SIGUSR2 handler — show and focus."""
        self._show_window()
        return True

    def _show_window(self):
        if self.window:
            self.window.present()
            self.window.fullscreen()
            self._visible = True
            print("[wa-organ] Window shown")

    def _hide_window(self):
        if self.window:
            self.window.unfullscreen()
            self.window.minimize()
            self._visible = False
            print("[wa-organ] Window hidden")

    def _relay_status(self, status):
        """Send status to the Brain via HTTP."""
        import urllib.request
        try:
            data = json.dumps({
                "status": status,
                "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            }).encode()
            req = urllib.request.Request(
                f"{BRAIN_URL}/whatsapp/status",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception as e:
            print(f"[wa-organ] Status relay failed: {e}")

    def _shutdown(self):
        """Clean shutdown."""
        print("[wa-organ] Shutting down...")
        try:
            os.unlink(PID_FILE)
        except OSError:
            pass
        self.quit()
        return False


def main():
    load_monitor_js()

    # Clean up stale PID file
    if os.path.exists(PID_FILE):
        try:
            old_pid = int(open(PID_FILE).read().strip())
            os.kill(old_pid, 0)  # Check if process exists
            print(f"[wa-organ] Another instance running (PID {old_pid}), killing it")
            os.kill(old_pid, signal.SIGTERM)
            import time; time.sleep(0.5)
        except (ProcessLookupError, ValueError):
            pass
        try:
            os.unlink(PID_FILE)
        except OSError:
            pass

    app = WhatsAppOrgan()
    app.run(None)


if __name__ == "__main__":
    main()
