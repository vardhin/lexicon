<p align="center">
  <img src="architecture/Mermaid Chart - Create complex, visual diagrams with text.-2026-02-24-134541.png" width="700" alt="Lexicon Architecture" />
</p>

<h1 align="center">Lexicon</h1>

<p align="center">
  A transparent, fullscreen overlay OS layer for Linux — triggered by a hotkey, driven by natural language, rendered as floating glass widgets.
</p>

<p align="center">
  <a href="#architecture">Architecture</a> •
  <a href="#status">Status</a> •
  <a href="#getting-started">Getting Started</a> •
  <a href="#adding-extensions">Adding Extensions</a> •
  <a href="#roadmap">Roadmap</a>
</p>

---

## What is Lexicon?

Lexicon is a **desktop overlay intelligence layer**. You press `Super + `` ` on your desktop, a transparent fullscreen window appears with a centered input bar (the **Synapse Bar**), and you type natural language commands like `"clock"`, `"timer 5m"`, or `"weather"`. Lexicon interprets the command and renders **floating glass widgets** on the overlay in real time.

It's not a terminal. It's not an app launcher. It's a **programmable visual nervous system** for your desktop.

The Tauri client runs persistently in the background (no taskbar icon, zero CPU when hidden) and toggles instantly via `lexicon-toggle` — a script you bind to any hotkey in any desktop environment. The toggle flows through ZeroMQ (the Spine) → FastAPI (the Brain) → WebSocket → Svelte → Rust IPC show/hide. Escape hides the overlay. Entire round-trip <5ms. Works on GNOME, KDE, Hyprland, Sway, and any X11/Wayland compositor.

---

## Architecture

Lexicon is a multi-layer system:

| Layer | Name | Tech | Role |
|-------|------|------|------|
| **0** | **The Body** | Tauri + Bun + SvelteKit | Transparent fullscreen window, IPC, WebView rendering |
| **0+** | **Organs** | Tauri child webviews + injected JS | Real web apps (WhatsApp, etc.) embedded inside widgets, DOM scanning → batched events |
| **1** | **The Brain** | Python + FastAPI + uv | Rule-based grammar engine, WebSocket hub, extension loader |
| **2** | **The Spine** | ZeroMQ (pyzmq) | PUSH/PULL + PUB event bus between layers |
| **3** | **The Memory** | SurrealDB (embedded) | Persistent graph + document storage for UI state, command history, WhatsApp messages, context |
| **4** | **External Sensors** | CLI scripts, daemons *(planned)* | System monitors, ad-hoc data pushers |

### Data Flow

```
Boot                  →  dev.sh starts backend (+ Spine) + Tauri client
                      →  Tauri window opens briefly (WebView boots, JS executes)
                      →  Svelte connects to WebSocket (ws://127.0.0.1:8000/ws)
                      →  Rust auto-hides the window after 2s (WebView stays alive)
                      →  Lexicon is now idle — zero CPU, no taskbar icon

User presses Super+`  →  lexicon-toggle PUSHes "lexicon/toggle" to Spine (Layer 2)
                      →  Spine dispatches to Brain (Layer 1)
                      →  Brain broadcasts TOGGLE_VISIBILITY over WebSocket
                      →  Svelte calls invoke("toggle_window") → Rust IPC
                      →  Rust shows window + sets fullscreen + focuses
                      →  Backend sends RESTORE_STATE with saved widgets from SurrealDB (Layer 3)
                      →  Svelte re-hydrates the render list — widgets reappear instantly

User presses Escape   →  Svelte calls invoke("toggle_window") → Rust hides window
                      →  Window disappears instantly, WebView stays connected

User types "clock"    →  Svelte sends { type: "query", text: "clock" } via WebSocket
                      →  FastAPI receives it (Layer 1), logs command to Memory
                      →  GrammarEngine runs text through extensions/
                      →  extensions/clock.py match() hits → action() returns:
                           { type: "RENDER_WIDGET", widget_type: "clock", x: 50, y: 50, w: 320, h: 180 }
                      →  Sent back over WebSocket
                      →  +page.svelte handleMessage() looks up registry["clock"]
                      →  Adds entry to widgets[] render list, saves state to Memory
                      →  Svelte renders <ClockWidget> at (50, 50) with glass blur frame

User opens WhatsApp   →  Sidebar 💬 button toggles WhatsAppWidget on the canvas
                      →  Widget calls invoke("open_whatsapp_organ", { x, y, w, h })
                      →  Rust creates a CHILD WEBVIEW loading web.whatsapp.com
                      →  Child webview positioned to exactly overlay the widget's DOM rect
                      →  Injected whatsapp_monitor.js scans sidebar + open chat DOM
                      →  Messages batched (500ms) → Tauri IPC → Rust → HTTP POST /whatsapp/batch
                      →  Brain stores in SurrealDB, broadcasts WHATSAPP_BATCH over WebSocket
                      →  WhatsAppWidget receives batch, groups by chat name, updates UI
                      →  Widget has two views: dashboard (chat list) or live (WhatsApp inside)
                      →  Dismissing widget hides the webview but keeps it running in background
```

---

## Status

> **Current phase: Layer 0 + Layer 1 + Layer 2 + Organs — core loop + Spine + WhatsApp organ functional.**

### ✅ Implemented

| Component | Status | Details |
|-----------|--------|---------|
| **Tauri shell (Layer 0)** | ✅ Complete | Transparent, borderless, always-on-top, fullscreen. Boots visible (so WebView JS executes and WebSocket connects), then Rust auto-hides after 2s. Toggle via `lexicon-toggle` (ZeroMQ PUSH → Spine → Brain → WebSocket → Svelte `invoke("toggle_window")` → Rust IPC show/hide). Escape hides when input is empty. Fallback: `curl -X POST localhost:8000/toggle`. Builds to release binary (~16MB). |
| **Svelte frontend (Layer 0)** | ✅ Complete | SPA mode, static adapter, frost-glass overlay, Synapse Bar with command history (↑↓), feedback toasts, connection status dot. |
| **Paged workspace (Layer 0)** | ✅ Complete | Vertically scrolling canvas divided into pages by thin aesthetic divider lines. Sidebar with page numbers for smooth scroll navigation. Auto-expands pages as content grows. Widgets freely span across dividers. |
| **Widget renderer (Layer 0)** | ✅ Complete | Dynamic render list driven by WebSocket. Widgets positioned absolutely at `(x, y, w, h)` from backend. Glass-blur frames, pop-in animation, per-widget dismiss. |
| **Widget registry (Layer 0)** | ✅ Complete | `src/lib/widgets/index.js` — maps `widget_type` strings → Svelte components. Adding a widget = 1 import + 1 line. |
| **Widget dragging (Layer 0)** | ✅ Complete | Pointer-based drag via top handle strip. Accounts for scroll offset in paged canvas. Positions persist to SurrealDB Memory and restore on relaunch. |
| **Widget resizing (Layer 0)** | ✅ Complete | Corner resize handle (bottom-right) on hover. Min size 160×100. Sizes persist alongside positions. |
| **Shell mode (Layer 0+1)** | ✅ Complete | Synapse Bar doubles as a **real zsh shell** with your full Arch env. Persistent zsh session per connection — `cd`, `z`, `export` changes stick between commands. TUI programs (`btop`, `vim`, `htop`) detected and rejected with helpful message. Ctrl+C / ^C button to kill running commands. 60s timeout. Prefix `!` or `$`, or type common commands (`ls`, `git`, `cat`, etc.) directly. Output streams line-by-line between green dividers on the canvas, auto-scrolling. Every command + full output + exit code persisted to SurrealDB and restored on reconnect. |
| **Workspaces (Layer 0+3)** | ✅ Complete | Named workspaces stored in SurrealDB. Click ✦ logo → workspace menu: create, switch, delete workspaces. Each workspace has independent widgets, shell history, and state. 🧹 clear button wipes current workspace canvas + DB. Auto-saves on switch, auto-restores on load. |
| **WebSocket client (Layer 0)** | ✅ Complete | Auto-reconnect with exponential backoff (2s → 30s cap). Handles `RENDER_WIDGET`, `REMOVE_WIDGET`, `CLEAR_WIDGETS`, `CLEAR_SHELL`, `FEEDBACK`, `RESTORE_STATE`, `RESTORE_SHELL`, `SHELL_OUTPUT`, `SHELL_DONE`, `WORKSPACE_INFO`, `TOGGLE_VISIBILITY`, `WHATSAPP_BATCH`, `WHATSAPP_MESSAGE`, `WHATSAPP_STATUS`. |
| **FastAPI server (Layer 1)** | ✅ Complete | WebSocket at `/ws`, health at `/health`, toggle at `POST /toggle`, system stats at `/system`. WhatsApp endpoints: `POST /whatsapp/batch`, `POST /whatsapp/message`, `POST /whatsapp/status`, `GET /whatsapp/chats`, `GET /whatsapp/messages`, `GET /whatsapp/contacts`. Persistent shell session per connection. Connection manager with broadcast, CORS enabled. Sends `WORKSPACE_INFO` + `RESTORE_STATE` + `RESTORE_SHELL` on connect. Workspace CRUD. |
| **Grammar engine (Layer 1)** | ✅ Complete | Dynamically loads every `.py` from `extensions/`, runs `match()` → `action()` pipeline, returns action list. Fallback feedback for unknown commands. |
| **Extension: clock** | ✅ Complete | Matches ~7 natural language patterns ("what's the time", "show clock", etc). Returns `RENDER_WIDGET` with clock type. Frontend renders live-updating `HH:MM:SS` with gradient text. |
| **Extension: clear** | ✅ Complete | Matches "clear", "dismiss all", "close", etc. Returns `CLEAR_WIDGETS` to wipe the render list. |
| **Extension: timer** | ✅ Complete | Countdown timer — "timer 5 min", "countdown 1h30m", "set timer 30s". Parses h/m/s durations. Widget has start/pause/reset controls and progress bar. |
| **Extension: date** | ✅ Complete | Rich date display — "what's the date", "what day is it". Shows weekday, date, year, day-of-year, week number, and year-progress bar. |
| **Extension: note** | ✅ Complete | Sticky notes — "note buy groceries", "remind me to call bob". Editable text with click-to-edit. |
| **Extension: calculator** | ✅ Complete | Inline math — "calc 2+2", "= pi * 2", "math sqrt(144)". Safe eval with trig, log, constants. Shows expression → result. |
| **Extension: sysmon** | ✅ Complete | Live system monitor — "system", "show stats". CPU/RAM/disk bars with live polling from `/system` endpoint (reads `/proc`, zero dependencies). |
| **Extension: weather** | ✅ Complete | Weather widget (demo mode) — "weather", "forecast". Time-based display placeholder. Ready for real API integration. |
| **Extension: help** | ✅ Complete | Dynamic help guide — "help", "commands", "?". Auto-collects help metadata from all loaded extensions. Shows icons, descriptions, example commands, and usage tips. |
| **WhatsApp Organ (Layer 0)** | ✅ Complete | Real `web.whatsapp.com` rendered **inside a widget** on the canvas via Tauri child webview. Injected `whatsapp_monitor.js` scans the WhatsApp DOM (sidebar contacts + open chat messages), batches them (500ms flush), relays via Tauri IPC → Rust → HTTP POST to Brain. Brain stores in SurrealDB, broadcasts `WHATSAPP_BATCH` over WebSocket. Widget shows: dashboard (chat list grouped by conversation, message preview, unread counts) or live view (actual WhatsApp rendered inside the widget frame). Child webview positioned to exactly overlay the widget's DOM rect — looks embedded. Stays logged in across toggles (hide doesn't destroy the webview). Sidebar 💬 button toggles the widget. |
| **SurrealDB Memory (Layer 3)** | ✅ Complete | Embedded file-backed SurrealDB (`surrealkv://`). Persists UI state (open widgets), command history, **full shell sessions** (cmd + output + exit code), **named workspaces**, and **WhatsApp messages + contacts**. All data is workspace-scoped. Auto-restores widgets and shell history on reconnect. Output capped at 64KB per session. No external server needed. |
| **ZeroMQ Spine (Layer 2)** | ✅ Complete | PUSH/PULL + PUB event bus. Brain binds PULL on `:5557` and PUB on `:5556`. External scripts PUSH commands (e.g., `lexicon/toggle`). Brain dispatches to handlers which broadcast over WebSocket to the Body. Toggle goes: ZeroMQ → Brain → WebSocket → Svelte → Rust IPC (`toggle_window`). HTTP fallback at `POST /toggle`. |
| **Dev tooling** | ✅ Complete | `dev.sh` — builds Svelte → builds Tauri release binary → starts backend (+ Spine) + Tauri client. One command to rebuild and run everything. `lexicon-toggle` for hotkey binding. |

### 🔲 Not Yet Implemented

| Component | Layer | Notes |
|-----------|-------|-------|
| **More Organs** | 0 | Discord, Gmail, etc. — same child-webview-inside-widget pattern as WhatsApp. |
| **CSS Morph / UI Payload push** | 0 | Backend pushing live CSS/theme changes to the overlay. Push via `lexicon/theme` Spine channel. |
| **CLI event scripts** | 4 | Ad-hoc scripts that push events into the Spine (e.g., `lexicon push "meeting in 5min"` via ZeroMQ PUSH to `:5557`). |

---

## Getting Started

### Prerequisites

- **Linux** (any desktop environment — GNOME, KDE, Hyprland, Sway, etc.)
- [Rust](https://rustup.rs/) + Cargo
- [Bun](https://bun.sh/)
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Python 3.13+

### Setup

```bash
git clone https://github.com/vardhin/lexicon.git
cd lexicon

# Backend — install Python deps
cd lexicon-backend
uv sync
cd ..

# Frontend — install JS deps
cd lexicon-frontend
bun install
cd ..
```

### Build & Run

```bash
./dev.sh
```

This will:
1. Build the Svelte static site (`bun run build`)
2. Build the Tauri release binary (`bun run tauri build`)
3. Start the FastAPI backend + ZeroMQ Spine on `:8000` / `:5557`
4. Launch the Tauri client in the background (hidden)

### Toggle the overlay

Bind `lexicon-toggle` to your preferred hotkey in your desktop environment:

| DE | How to bind |
|----|-------------|
| **GNOME** | Settings → Keyboard → Custom Shortcuts → `Super+`` ` → `/path/to/lexicon/lexicon-toggle` |
| **KDE** | System Settings → Shortcuts → Custom Shortcuts → add `lexicon-toggle` |
| **Hyprland** | `bind = $mainMod, grave, exec, /path/to/lexicon/lexicon-toggle` |
| **Sway** | `bindsym $mod+grave exec /path/to/lexicon/lexicon-toggle` |

Or toggle manually:

```bash
# Via ZeroMQ (instant)
./lexicon-toggle

# Via HTTP (works from anywhere)
curl -X POST localhost:8000/toggle
```

Press **`Escape`** (with an empty input) to hide the overlay from within.

> **How it works:** `lexicon-toggle` PUSHes `"lexicon/toggle"` via ZeroMQ to the Spine (`:5557`). The Brain receives it, broadcasts `TOGGLE_VISIBILITY` over WebSocket to the Svelte frontend, which calls `invoke("toggle_window")` — a Rust IPC command that does the actual `window.show()` / `window.hide()` from the Rust side. This bypasses Wayland permission issues. The window boots visible so the WebView can load (GNOME Wayland suspends JS in hidden windows), then Rust auto-hides it after 2 seconds. The entire toggle round-trip is <5ms.

---

## Adding Extensions

Each extension is a single Python file in `extensions/` with a standard interface:

### 1. Create the backend logic

```python
# extensions/timer.py
import re, uuid

def match(text):
    m = re.search(r"timer\s+(\d+)\s*(m|min|s|sec)?", text)
    if m:
        amount = int(m.group(1))
        unit = (m.group(2) or "s")[0]
        return amount * (60 if unit == "m" else 1)
    return None

def action(original_text, seconds):
    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"timer-{uuid.uuid4().hex[:6]}",
        "widget_type": "timer",
        "x": 100, "y": 100, "w": 300, "h": 180,
        "props": {"duration_seconds": seconds},
    }

EXTENSION = {"name": "timer", "match": match, "action": action}
```

### 2. Create the frontend widget

```svelte
<!-- lexicon-frontend/src/lib/widgets/TimerWidget.svelte -->
<script>
  export let props = {};
  export let onDismiss = () => {};
  // ... timer logic
</script>
<!-- ... timer UI -->
```

### 3. Register it

```javascript
// lexicon-frontend/src/lib/widgets/index.js
import ClockWidget from './ClockWidget.svelte';
import TimerWidget from './TimerWidget.svelte';

const registry = {
  clock: ClockWidget,
  timer: TimerWidget,  // ← add here
};

export default registry;
```

Restart the backend (it auto-reloads), rebuild the frontend (`./dev.sh`). Done.

---

## Project Structure

```
lexicon/
├── dev.sh                          # Build + run everything
├── lexicon-toggle                  # Toggle script — bind to your DE hotkey
├── extensions/                     # Backend extension logic (Python)
│   ├── calculator.py               #   Inline math evaluator
│   ├── clear.py                    #   Clear all widgets
│   ├── clock.py                    #   Clock widget trigger
│   ├── date.py                     #   Date display widget
│   ├── help.py                     #   Help guide (auto-collects from all extensions)
│   ├── note.py                     #   Sticky note widget
│   ├── sysmon.py                   #   System monitor widget
│   ├── timer.py                    #   Countdown timer widget
│   └── weather.py                  #   Weather widget (demo)
├── lexicon-backend/                # Layer 1: The Brain
│   ├── pyproject.toml              #   uv project config
│   ├── run.sh                      #   Start backend standalone
│   └── src/
│       ├── main.py                 #   FastAPI app + WebSocket + WhatsApp endpoints
│       ├── engine.py               #   Grammar engine (loads extensions/)
│       ├── memory.py               #   SurrealDB embedded memory (Layer 3)
│       ├── spine.py                #   ZeroMQ PUSH/PULL + PUB event bus (Layer 2)
│       ├── shell.py                #   Persistent zsh session per connection
│       └── connection_manager.py   #   WebSocket connection tracking
├── lexicon-frontend/               # Layer 0: The Body
│   ├── package.json                #   Bun/Vite/SvelteKit config
│   ├── src/
│   │   ├── app.html                #   Shell HTML (transparent bg)
│   │   ├── routes/+page.svelte     #   Main overlay page (render list + synapse bar)
│   │   └── lib/
│   │       ├── ws.js               #   WebSocket client (auto-reconnect)
│   │       └── widgets/
│   │           ├── index.js        #   Widget registry
│   │           ├── ClockWidget.svelte
│   │           ├── TimerWidget.svelte
│   │           ├── DateWidget.svelte
│   │           ├── NoteWidget.svelte
│   │           ├── CalculatorWidget.svelte
│   │           ├── SysMonWidget.svelte
│   │           ├── WeatherWidget.svelte
│   │           ├── HelpWidget.svelte
│   │           ├── TerminalWidget.svelte
│   │           └── WhatsAppWidget.svelte   # WhatsApp dashboard + embedded live view
│   └── src-tauri/
│       ├── tauri.conf.json         #   Tauri config (transparent, borderless, always-on-top)
│       ├── capabilities/           #   Shell + IPC permissions
│       ├── injections/
│       │   └── whatsapp_monitor.js #   Injected into WhatsApp child webview (DOM scanner)
│       └── src/
│           ├── main.rs             #   Rust entry point
│           └── lib.rs              #   Tauri setup + toggle_window + WhatsApp organ IPC
├── infra/
│   └── data/                       #   SurrealDB file store (gitignored, auto-created)
└── architecture/                   # Architecture diagram (Mermaid)
```

---

## Roadmap

- [x] **SurrealDB Memory** — persist UI state, command history, auto-restore on launch
- [x] **More extensions** — timer, date, weather, notes, calculator, system monitor, help
- [x] **Widget dragging** — pointer-based repositioning with persisted positions
- [x] **Widget resizing** — corner drag handle, min-size constraints, persisted
- [x] **Paged workspace** — scrollable multi-page canvas with sidebar navigation and dividers
- [x] **Shell mode** — execute zsh commands directly in the Synapse Bar, streaming output on canvas
- [x] **ZeroMQ Spine** — PUSH/PULL + PUB event bus, `lexicon-toggle` script, `POST /toggle` HTTP fallback
- [x] **WhatsApp Organ** — real web.whatsapp.com inside a widget, DOM scanning, batched message relay, chat grouping
- [ ] **More Organs** — Discord, Gmail, etc. — same child-webview-inside-widget pattern
- [ ] **SysMon daemon** — push system metrics as events via Spine
- [ ] **CLI tool** — `lexicon push "reminder text"` from terminal via Spine
- [ ] **Theming** — runtime CSS morph pushed via `lexicon/theme` Spine channel

---

## License

MIT

---

<p align="center">
  Built by <a href="https://github.com/vardhin">@vardhin</a>
</p>
