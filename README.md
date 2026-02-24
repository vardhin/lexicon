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

Lexicon is a **desktop overlay intelligence layer**. You press `Super + `` ` on your Linux desktop, a transparent fullscreen window appears with a centered input bar (the **Synapse Bar**), and you type natural language commands like `"clock"`, `"timer 5m"`, or `"weather"`. Lexicon interprets the command and renders **floating glass widgets** on the overlay in real time.

It's not a terminal. It's not an app launcher. It's a **programmable visual nervous system** for your desktop.

---

## Architecture

Lexicon is a multi-layer system:

| Layer | Name | Tech | Role |
|-------|------|------|------|
| **0** | **The Body** | Tauri + Bun + SvelteKit | Transparent fullscreen window, IPC, WebView rendering |
| **1** | **The Brain** | Python + FastAPI + uv | Rule-based grammar engine, WebSocket hub, extension loader |
| **2** | **The Spine** | Redis / ZeroMQ *(planned)* | Pub/Sub event bus between layers |
| **3** | **The Memory** | SurrealDB *(planned)* | Graph + document storage for context, history, edges |
| **4** | **External Sensors** | CLI scripts, daemons *(planned)* | System monitors, ad-hoc data pushers |

### Data Flow

```
User presses Super+`  →  Tauri window appears (Layer 0)
User types "clock"    →  Svelte sends { type: "query", text: "clock" } via WebSocket
                      →  FastAPI receives it (Layer 1)
                      →  GrammarEngine runs text through extensions/
                      →  extensions/clock.py match() hits → action() returns:
                           { type: "RENDER_WIDGET", widget_type: "clock", x: 50, y: 50, w: 320, h: 180 }
                      →  Sent back over WebSocket
                      →  +page.svelte handleMessage() looks up registry["clock"]
                      →  Adds entry to widgets[] render list
                      →  Svelte renders <ClockWidget> at (50, 50) with glass blur frame
```

---

## Status

> **Current phase: Layer 0 + Layer 1 — core loop functional.**

### ✅ Implemented

| Component | Status | Details |
|-----------|--------|---------|
| **Tauri shell (Layer 0)** | ✅ Complete | Transparent, borderless, always-on-top, fullscreen via Hyprland IPC. `Super+`` toggle via Hyprland keybind. Builds to release binary (~16MB). |
| **Svelte frontend (Layer 0)** | ✅ Complete | SPA mode, static adapter, frost-glass overlay, Synapse Bar with command history (↑↓), feedback toasts, connection status dot. |
| **Widget renderer (Layer 0)** | ✅ Complete | Dynamic render list driven by WebSocket. Widgets positioned absolutely at `(x, y, w, h)` from backend. Glass-blur frames, pop-in animation, per-widget dismiss. |
| **Widget registry (Layer 0)** | ✅ Complete | `src/lib/widgets/index.js` — maps `widget_type` strings → Svelte components. Adding a widget = 1 import + 1 line. |
| **WebSocket client (Layer 0)** | ✅ Complete | Auto-reconnect with exponential backoff (2s → 30s cap). Handles `RENDER_WIDGET`, `REMOVE_WIDGET`, `CLEAR_WIDGETS`, `FEEDBACK`. |
| **FastAPI server (Layer 1)** | ✅ Complete | WebSocket endpoint at `/ws`, health check at `/health`, connection manager with broadcast support, CORS enabled. |
| **Grammar engine (Layer 1)** | ✅ Complete | Dynamically loads every `.py` from `extensions/`, runs `match()` → `action()` pipeline, returns action list. Fallback feedback for unknown commands. |
| **Extension: clock** | ✅ Complete | Matches ~7 natural language patterns ("what's the time", "show clock", etc). Returns `RENDER_WIDGET` with clock type. Frontend renders live-updating `HH:MM:SS` with gradient text. |
| **Extension: clear** | ✅ Complete | Matches "clear", "dismiss all", "close", etc. Returns `CLEAR_WIDGETS` to wipe the render list. |
| **Dev tooling** | ✅ Complete | `dev.sh` — builds Svelte → builds Tauri release binary → starts backend. One command to rebuild everything. |

### 🔲 Not Yet Implemented

| Component | Layer | Notes |
|-----------|-------|-------|
| **Hidden WebViews (Organs)** | 0 | WhatsApp, Discord, etc. via injected JS in hidden Tauri WebViews. DOM scraping → events. `src-tauri/injections/` exists but is empty. |
| **Tauri IPC commands** | 0 | Rust ↔ Svelte command layer for triggering system actions (sudo auth, shell exec). Capabilities are configured (`shell.json`) but no custom commands yet. |
| **CSS Morph / UI Payload push** | 0 | Backend pushing live CSS/theme changes to the overlay. |
| **Redis / ZeroMQ event bus (Spine)** | 2 | Pub/Sub decoupling between Brain, Sensors, and Body. `infra/` folder exists but is empty. |
| **SurrealDB (Memory)** | 3 | Graph + document storage for conversation history, context nodes, user preferences. Not started. |
| **SysMon daemon** | 4 | System resource sensor publishing CPU/RAM/disk/network events to the Spine. |
| **CLI event scripts** | 4 | Ad-hoc scripts that push events into the bus (e.g., `lexicon push "meeting in 5min"`). |
| **More extensions** | 1 | Timer, date, weather, note, system monitor widgets — logic existed previously, needs to be re-created as standalone extensions + Svelte widgets. |

---

## Getting Started

### Prerequisites

- **Arch Linux** (or any Linux with Hyprland — the WM integration is Hyprland-specific)
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
3. Start the FastAPI backend on `:8000` with hot-reload

Then press **`Super + `` `** to open the overlay (requires the Hyprland keybind below).

### Hyprland Keybind

Add to your `~/.config/hypr/config/keybinds.conf`:

```ini
bind = $mainMod, grave, exec, pkill -x lexicon-frontend || /path/to/lexicon/lexicon-frontend/src-tauri/target/release/lexicon-frontend
```

This toggles the overlay: if it's running, kill it; if not, launch it.

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
├── extensions/                     # Backend extension logic (Python)
│   ├── clock.py                    #   Clock widget trigger
│   └── clear.py                    #   Clear all widgets
├── lexicon-backend/                # Layer 1: The Brain
│   ├── pyproject.toml              #   uv project config
│   ├── run.sh                      #   Start backend standalone
│   └── src/
│       ├── main.py                 #   FastAPI app + WebSocket endpoint
│       ├── engine.py               #   Grammar engine (loads extensions/)
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
│   │           └── ClockWidget.svelte
│   └── src-tauri/
│       ├── tauri.conf.json         #   Tauri config (transparent, borderless, always-on-top)
│       ├── capabilities/           #   Shell + IPC permissions
│       ├── injections/             #   (empty) Future: injected JS for hidden WebViews
│       └── src/
│           ├── main.rs             #   Rust entry point
│           └── lib.rs              #   Tauri setup + Hyprland fullscreen hack
├── infra/                          # (empty) Future: Redis/ZeroMQ/SurrealDB configs
└── architecture/                   # Architecture diagram (Mermaid)
```

---

## Roadmap

- [ ] **More extensions** — timer, date, weather, notes, system monitor
- [ ] **Widget dragging** — let users reposition widgets on the overlay
- [ ] **Redis/ZeroMQ Spine** — decouple Brain from Body with pub/sub
- [ ] **SurrealDB Memory** — persist context, command history, widget state
- [ ] **Hidden WebViews (Organs)** — scrape WhatsApp/Discord/Gmail via injected JS
- [ ] **SysMon daemon** — push system metrics as events
- [ ] **CLI tool** — `lexicon push "reminder text"` from terminal
- [ ] **Theming** — runtime CSS morph pushed from backend

---

## License

MIT

---

<p align="center">
  Built by <a href="https://github.com/vardhin">@vardhin</a>
</p>
