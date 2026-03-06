<p align="center">
  <img src="architecture/Mermaid Chart - Create complex, visual diagrams with text.-2026-02-24-134541.png" width="700" alt="LSD Architecture" />
</p>

<h1 align="center">LSD — Lexicon Shell Daemon</h1>

<p align="center">
  A transparent, fullscreen overlay OS layer for Linux — triggered by a hotkey, driven by natural language, rendered as floating glass widgets.
</p>

<p align="center">
  <em>"It's a shell that lives on top of your entire screen — like a heads-up display for your desktop. You press a key, a transparent layer appears, you type what you want in plain English, and it just… does it."</em>
</p>

<p align="center">
  <a href="#what-is-lsd">What is LSD?</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#status">Status</a> •
  <a href="#getting-started">Getting Started</a> •
  <a href="#adding-extensions">Adding Extensions</a> •
  <a href="#roadmap">Roadmap</a>
</p>

---

## What is LSD?

**LSD** stands for **Lexicon Shell Daemon** — but in plain terms, it's a see-through layer that sits on top of your entire Linux desktop. Think of it like a HUD in a video game, except it's for your real computer.

Here's what that means in practice:

1. **You press a hotkey** (like `Super + `` `) and a transparent fullscreen window instantly appears over whatever you were doing — your browser, your code editor, everything stays visible underneath.
2. **You type in plain English** into a bar at the bottom (the "Synapse Bar"): things like `"clock"`, `"timer 5m"`, `"what's the date"`, `"theme cyberpunk"`, or even shell commands like `ls` and `git status`.
3. **Floating glass widgets appear** on the overlay — a clock, a timer, a sticky note, a system monitor — whatever you asked for.
4. **Press Escape** and the whole thing vanishes. Zero CPU when hidden. Your desktop is untouched.

It's not a terminal emulator. It's not an app launcher. It's a **daemon** (a background process) that gives your desktop a programmable glass nervous system you can talk to in natural language.

The name is a triple meaning:
- **L**exicon **S**hell **D**aemon — what it literally is
- **LSD** — because it puts a trippy transparent layer over your reality
- It's also just a daemon (`lexicond`) — it runs silently in the background, always listening

---

## Architecture

LSD is a multi-layer system with body-inspired naming:

| Layer | Name | Tech | Role |
|-------|------|------|------|
| **0** | **The Body** | Tauri + Bun + SvelteKit | Transparent fullscreen window, Rust IPC, WebView rendering |
| **0+** | **Organs** | Playwright ghost browser + DOM scraping | Real web apps (WhatsApp, GitHub, etc.) as headless tabs — scraped, not embedded |
| **1** | **The Brain** | Python + FastAPI + uv | Rule-based grammar engine, WebSocket hub, extension loader, organ orchestration |
| **1+** | **The Shell** | Python PTY microservice | Real pseudo-terminal sessions (zsh/bash), full interactive shell over WebSocket |
| **2** | **The Spine** | ZeroMQ (pyzmq) | PUSH/PULL + PUB event bus between all layers |
| **3** | **The Memory** | SurrealDB (embedded) | Persistent document storage — UI state, history, workspaces, scraped data, themes |
| **4** | **External Sensors** | CLI scripts, daemons | System monitors, ad-hoc data pushers via Spine |

### Data Flow

```
Boot                  →  dev.sh starts Brain + Shell + Spine + Tauri client
                      →  Tauri window opens briefly (WebView boots, JS connects)
                      →  Svelte connects to WebSocket (ws://127.0.0.1:8000/ws)
                      →  Brain sends RESTORE_STATE (widgets) + active theme from Memory
                      →  Rust auto-hides the window after 2s (WebView stays alive)
                      →  LSD is now idle — zero CPU, no taskbar icon

User presses Super+`  →  lexicon-toggle PUSHes "lexicon/toggle" to Spine (:5557)
                      →  Spine dispatches to Brain handler
                      →  Brain broadcasts TOGGLE_VISIBILITY over WebSocket
                      →  Svelte calls invoke("toggle_window") → Rust IPC
                      →  Rust shows window + sets fullscreen + focuses
                      →  Saved widgets reappear instantly (already in memory)

User presses Escape   →  Svelte calls invoke("toggle_window") → Rust hides window
                      →  Window vanishes instantly, WebView stays connected

User types "clock"    →  Svelte sends { type: "query", text: "clock" } via WebSocket
                      →  Brain logs command to Memory, runs GrammarEngine
                      →  extensions/clock.py match() hits → action() returns RENDER_WIDGET
                      →  Sent back over WebSocket
                      →  Svelte looks up registry["clock"], renders <ClockWidget>
                      →  Widget appears at (x, y) with glass blur frame

User types "!ls"      →  Svelte detects shell prefix, sends shell_spawn + shell_input
                      →  Brain relays to Shell microservice (ws://127.0.0.1:8765)
                      →  Shell service spawns real PTY zsh session
                      →  Output streams back: Shell → Brain → WebSocket → xterm.js widget
                      →  Full-screen terminal widget with colors, scrollback, resize

User types            →  Svelte sends { type: "apply_theme", name: "cyberpunk" }
  "theme cyberpunk"   →  Brain looks up CSS from Memory (SurrealDB)
                      →  Broadcasts APPLY_THEME { css: "..." } to ALL connected clients
                      →  Svelte injects <style id="lexicon-theme"> into <head>
                      →  Every widget, bar, sidebar re-skins instantly via lx-* classes

User types "organs"   →  OrganManagerWidget spawns on canvas
                      →  Register any URL as an "organ" (e.g. github.com, web.whatsapp.com)
                      →  Brain's OrganManager opens a tab in a Playwright ghost browser
                      →  User pastes outer HTML of a page element → names it → scrapes
                      →  Playwright deep-scrapes all matching elements with field extraction
                      →  Structured data stored in Memory, viewable in DataViewWidget
```

---

## Status

> **Current phase: All core layers functional — Body + Brain + Shell + Spine + Organs + Theming.**

### ✅ Implemented

| Component | Status | Details |
|-----------|--------|---------|
| **Tauri shell (Layer 0)** | ✅ Complete | Transparent, borderless, always-on-top, fullscreen. Boots visible (WebView boots + WebSocket connects), Rust auto-hides after 2s. Toggle via `lexicon-toggle` (ZeroMQ → Spine → Brain → WS → Svelte → Rust IPC). Escape hides. Builds to ~16MB release binary. |
| **Svelte frontend (Layer 0)** | ✅ Complete | SPA with static adapter, frost-glass overlay, Synapse Bar with command history (↑↓), feedback toasts, connection status dot, `lx-*` CSS anchor classes for theming. |
| **Paged workspace (Layer 0)** | ✅ Complete | Vertically scrolling canvas divided into pages by thin divider lines. Sidebar with page numbers for smooth scroll navigation. Auto-expands as content grows. Widgets freely span across dividers. |
| **Widget system (Layer 0)** | ✅ Complete | Dynamic render list driven by WebSocket. Absolute positioning at `(x, y, w, h)`. Glass-blur frames, pop-in animation, per-widget dismiss. Pointer-based dragging via handle strip. Corner resize handle. All positions/sizes persist to Memory. |
| **Widget registry (Layer 0)** | ✅ Complete | `src/lib/widgets/index.js` — maps `widget_type` → Svelte component. 11 widgets: clock, timer, date, note, calculator, sysmon, weather, help, terminal, organmanager, dataview. |
| **Multi-session shell (Layer 0+1)** | ✅ Complete | Full PTY shell via dedicated Shell microservice (:8765). Multiple concurrent sessions — each is a real zsh/bash PTY with colors, env persistence, interactive programs. Rendered in xterm.js TerminalWidgets on the canvas. Ctrl+C, resize, signals all work natively. Synapse Bar routes to active session or spawns new ones (Ctrl+\`, Ctrl+Tab). |
| **Workspaces (Layer 0+3)** | ✅ Complete | Named workspaces in SurrealDB. ✦ logo → workspace menu: create, switch, delete. Each workspace has independent widgets, shell state. 🧹 clear button wipes canvas + DB. Auto-saves on switch, auto-restores on load. |
| **WebSocket protocol (Layer 0↔1)** | ✅ Complete | Auto-reconnect with exponential backoff (2s → 30s). Message types: `RENDER_WIDGET`, `REMOVE_WIDGET`, `CLEAR_WIDGETS`, `CLEAR_SHELL`, `FEEDBACK`, `RESTORE_STATE`, `SHELL_SPAWNED`, `SHELL_OUTPUT`, `SHELL_EXITED`, `SHELL_ERROR`, `WORKSPACE_INFO`, `TOGGLE_VISIBILITY`, `ORGAN_STATUS`, `ORGAN_LIST`, `APPLY_THEME`, `THEME_LIST`, `THEME_INFO`, `WHATSAPP_BATCH`, `WHATSAPP_CHATS`, `WHATSAPP_MESSAGES`. |
| **FastAPI Brain (Layer 1)** | ✅ Complete | WebSocket at `/ws`, health at `/health`, toggle at `POST /toggle`, system stats at `/system`. Organ CRUD: `POST/GET/DELETE /organs`, `/organs/:id/launch`, `/organs/:id/kill`, `/organs/:id/match`, `/organs/:id/scrape`, `/organs/:id/rescrape`, `/organs/:id/data`. Connection manager with broadcast. CORS enabled. Workspace CRUD + theme CRUD over WebSocket. |
| **Grammar engine (Layer 1)** | ✅ Complete | Dynamically loads every `.py` from `extensions/`, runs `match()` → `action()` pipeline. 12 extensions loaded. Fallback feedback for unknown commands. Help entries auto-collected. |
| **Shell microservice (Layer 1+)** | ✅ Complete | Standalone Python PTY server on `:8765`. Auto-detects user's default shell. Real PTY with `TIOCSWINSZ` resize, `SIGHUP`/`SIGINT`/`SIGTSTP` signals. Raw byte streaming. Multiple concurrent sessions. |
| **Organ system (Layer 0+)** | ✅ Complete | **Generic organ framework** — any URL can be an organ. Single headed Playwright Chromium browser (off-screen, persistent cookies). Organs are tabs. **Deep structural scraping**: paste outer HTML → tree parser discovers fields → CSS selector extraction → structured objects per match. 3-stage pipeline: similarity → structural validation → deduplication. OrganManagerWidget for CRUD. DataViewWidget for recursive layout rendering. |
| **WhatsApp organ** | ✅ Complete | `web.whatsapp.com` as a Playwright ghost tab. Brain scrapes DOM (sidebar contacts + messages), stores in Memory, broadcasts over WebSocket. WhatsAppWidget shows chat list, message view, organ status, launch/kill controls. Stays logged in across restarts (persistent browser data). |
| **Theming (Layer 0+3)** | ✅ Complete | Full theme system with CSS injection. 4 built-in themes: `cyberpunk`, `midnight`, `rose-pine`, `ember`. Themes stored in SurrealDB Memory, auto-seeded from `themes/*.css` on boot. Apply via natural language (`"theme cyberpunk"`), WebSocket messages, or Spine channel (`lexicon/theme`). Active theme persists across restarts and broadcasts to all connected clients. Every UI element has `lx-*` anchor classes for granular styling. Reset to default with `"reset theme"`. |
| **SurrealDB Memory (Layer 3)** | ✅ Complete | Embedded file-backed SurrealDB (`surrealkv://`). Persists: UI state (widgets), command history, shell sessions, named workspaces, organ registrations, scrape patterns, scraped data, themes, active theme. All widget/shell data is workspace-scoped. Auto-restores on reconnect. No external server needed. |
| **ZeroMQ Spine (Layer 2)** | ✅ Complete | PUSH/PULL on `:5557` + PUB on `:5556`. Channels: `lexicon/toggle` (show/hide), `lexicon/theme` (apply theme by name). External scripts PUSH commands → Brain dispatches → WebSocket broadcast. HTTP fallback at `POST /toggle`. |
| **Dev tooling** | ✅ Complete | `dev.sh` — menu-driven launcher (build / preview / dev mode). Starts Brain + Shell + Spine + Tauri. One command for everything. `lexicon-toggle` for hotkey binding. |

### Extensions

| Extension | Command Examples | What it does |
|-----------|-----------------|--------------|
| **clock** | `clock`, `time`, `what time is it` | Live-updating `HH:MM:SS` with gradient text |
| **timer** | `timer 5m`, `countdown 1h30m`, `set timer 30s` | Countdown with progress bar, pause/reset controls |
| **date** | `date`, `what day is it`, `today` | Weekday, date, year, day-of-year, week number, year-progress bar |
| **note** | `note buy groceries`, `remind me to call bob` | Sticky notes with click-to-edit |
| **calculator** | `calc 2+2`, `= pi * 2`, `math sqrt(144)` | Safe math eval with trig, log, constants |
| **sysmon** | `system`, `stats`, `cpu` | Live CPU/RAM/disk bars polling from `/proc` |
| **weather** | `weather`, `forecast` | Weather widget (demo mode, ready for API) |
| **help** | `help`, `commands`, `?` | Auto-generated guide from all extensions |
| **clear** | `clear`, `dismiss all`, `close` | Wipe all widgets from canvas |
| **organ** | `organs`, `scrape`, `organ manager` | Opens the Organ Manager widget |
| **view** | `view github`, `dashboard`, `show data` | Data view — renders scraped organ data |
| **theme** | `theme cyberpunk`, `themes`, `reset theme` | Apply, list, or reset visual themes |

### 🔲 Not Yet Implemented

| Component | Layer | Notes |
|-----------|-------|-------|
| **More Organs** | 0+ | Discord, Gmail, etc. — same Playwright tab + scrape pattern. |
| **CLI event tool** | 4 | `lexicon push "meeting in 5min"` from terminal via ZeroMQ PUSH to Spine. |
| **SysMon daemon** | 4 | Push system metrics on schedule via Spine. |

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

# Shell microservice
cd lexicon-shell
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
3. Start the Brain (FastAPI :8000) + Shell microservice (:8765) + ZeroMQ Spine (:5557/:5556)
4. Launch the Tauri client in the background (hidden until toggled)

### Toggle the overlay

Bind `lexicon-toggle` to your preferred hotkey:

| DE | How to bind |
|----|-------------|
| **GNOME** | Settings → Keyboard → Custom Shortcuts → `Super+`` ` → `/path/to/lexicon/lexicon-toggle` |
| **KDE** | System Settings → Shortcuts → Custom Shortcuts → add `lexicon-toggle` |
| **Hyprland** | `bind = $mainMod, grave, exec, /path/to/lexicon/lexicon-toggle` |
| **Sway** | `bindsym $mod+grave exec /path/to/lexicon/lexicon-toggle` |

Or toggle manually:

```bash
# Via ZeroMQ (instant, <5ms round-trip)
./lexicon-toggle

# Via HTTP (works from anywhere)
curl -X POST localhost:8000/toggle
```

Press **Escape** (with empty input) to hide the overlay.

> **How it works:** `lexicon-toggle` PUSHes `"lexicon/toggle"` via ZeroMQ to the Spine (`:5557`). The Brain receives it, broadcasts `TOGGLE_VISIBILITY` over WebSocket to the Svelte frontend, which calls `invoke("toggle_window")` — a Rust IPC command that does the actual `window.show()` / `window.hide()`. This bypasses Wayland permission issues. The entire toggle round-trip is <5ms.

---

## Theming

LSD ships with 4 built-in themes. Type `themes` to list them, `theme <name>` to apply:

| Theme | Vibe |
|-------|------|
| `cyberpunk` | Neon green on deep black, scanline overlay, terminal hacker aesthetic |
| `midnight` | Deep navy blue with soft purple accents, calm and focused |
| `rose-pine` | Warm muted tones — salmon, gold, teal from the Rosé Pine palette |
| `ember` | Amber and orange on dark charcoal, warm and cozy |

```
theme cyberpunk     ← apply a theme
themes              ← list all themes
reset theme         ← revert to default
```

Themes are stored in SurrealDB and persist across restarts. The active theme auto-restores on reconnect and broadcasts to all connected clients. You can also trigger themes externally via the Spine: push `"lexicon/theme cyberpunk"` to `:5557`.

Custom themes: drop a `.css` file in `themes/` — it's auto-seeded on next boot. Target `lx-*` classes (`lx-widget`, `lx-bar`, `lx-input`, `lx-sidebar`, etc.) to style any element.

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

EXTENSION = {
    "name": "timer",
    "match": match,
    "action": action,
    "help": {
        "title": "Timer",
        "icon": "⏱",
        "description": "Set a countdown timer",
        "examples": ["timer 5m", "countdown 30s"],
    },
}
```

### 2. Create the frontend widget

```svelte
<!-- lexicon-frontend/src/lib/widgets/TimerWidget.svelte -->
<script>
  export let props = {};
  export let onDismiss = () => {};
  // ... timer logic
</script>
<div class="timer-widget lx-timer">
  <!-- ... timer UI with lx-* classes for theming -->
</div>
```

### 3. Register it

```javascript
// lexicon-frontend/src/lib/widgets/index.js
import TimerWidget from './TimerWidget.svelte';

const registry = {
  // ...
  timer: TimerWidget,  // ← add here
};
```

Restart the backend (it auto-reloads via uvicorn), rebuild the frontend (`./dev.sh`). Done.

Extensions can also return custom action types (not just `RENDER_WIDGET`) — the Brain's WebSocket handler intercepts them. See `extensions/theme.py` for an example that returns `THEME_APPLY` / `THEME_RESET` / `THEME_LIST_REQUEST`.

---

## Project Structure

```
lexicon/
├── dev.sh                          # Menu-driven launcher (build / preview / dev)
├── lexicon-toggle                  # Toggle script — bind to your DE hotkey
├── lexicon-toggle.sh               # Alternative toggle script
│
├── extensions/                     # Backend extensions (Python, auto-loaded)
│   ├── calculator.py               #   Inline math evaluator
│   ├── clear.py                    #   Clear all widgets
│   ├── clock.py                    #   Clock widget
│   ├── date.py                     #   Date display widget
│   ├── help.py                     #   Help guide (auto-collects from all extensions)
│   ├── note.py                     #   Sticky notes
│   ├── organ.py                    #   Organ Manager widget trigger
│   ├── sysmon.py                   #   System monitor widget
│   ├── theme.py                    #   Theme apply / list / reset
│   ├── timer.py                    #   Countdown timer widget
│   ├── view.py                     #   Data view / dashboard widget
│   └── weather.py                  #   Weather widget (demo)
│
├── themes/                         # Built-in themes (auto-seeded to SurrealDB)
│   ├── cyberpunk.css               #   Neon green hacker aesthetic
│   ├── ember.css                   #   Warm amber on charcoal
│   ├── midnight.css                #   Deep navy with purple accents
│   └── rose-pine.css               #   Warm muted palette
│
├── lexicon-backend/                # Layer 1: The Brain
│   ├── pyproject.toml              #   uv project config
│   ├── run.sh                      #   Start Brain standalone
│   └── src/
│       ├── main.py                 #   FastAPI + WebSocket + organ endpoints + theme handlers
│       ├── engine.py               #   Grammar engine (auto-loads extensions/)
│       ├── memory.py               #   SurrealDB embedded memory (Layer 3)
│       ├── spine.py                #   ZeroMQ PUSH/PULL + PUB event bus (Layer 2)
│       ├── shell.py                #   Shell session manager (relays to Shell microservice)
│       ├── organ_manager.py        #   Playwright ghost browser + organ tabs + deep scraping
│       └── connection_manager.py   #   WebSocket connection tracking + broadcast
│
├── lexicon-shell/                  # Layer 1+: Shell Microservice
│   ├── pyproject.toml              #   uv project config
│   ├── run.sh                      #   Start Shell service standalone
│   └── shell_server.py             #   PTY server on :8765 (real zsh/bash sessions)
│
├── lexicon-frontend/               # Layer 0: The Body
│   ├── package.json                #   Bun / Vite / SvelteKit config
│   ├── src/
│   │   ├── app.html                #   Shell HTML (transparent background)
│   │   ├── routes/+page.svelte     #   Main overlay (canvas + synapse bar + theme injection)
│   │   └── lib/
│   │       ├── ws.js               #   WebSocket client (auto-reconnect)
│   │       └── widgets/
│   │           ├── index.js            # Widget registry (11 widgets)
│   │           ├── ClockWidget.svelte
│   │           ├── TimerWidget.svelte
│   │           ├── DateWidget.svelte
│   │           ├── NoteWidget.svelte
│   │           ├── CalculatorWidget.svelte
│   │           ├── SysMonWidget.svelte
│   │           ├── WeatherWidget.svelte
│   │           ├── HelpWidget.svelte
│   │           ├── TerminalWidget.svelte     # xterm.js PTY terminal
│   │           ├── OrganManagerWidget.svelte  # Organ CRUD + pattern scraper
│   │           ├── DataViewWidget.svelte      # Recursive data layout renderer
│   │           └── WhatsAppWidget.svelte      # WhatsApp chat dashboard
│   └── src-tauri/
│       ├── tauri.conf.json         #   Tauri config (transparent, borderless, always-on-top)
│       ├── capabilities/           #   Shell + IPC permissions
│       └── src/
│           ├── main.rs             #   Rust entry point
│           └── lib.rs              #   Tauri setup + toggle_window IPC
│
├── infra/
│   └── data/                       #   SurrealDB file store (gitignored, auto-created)
│
└── architecture/                   # Architecture diagram (Mermaid)
```

---

## Roadmap

- [x] **SurrealDB Memory** — persist UI state, command history, auto-restore on launch
- [x] **Extensions** — clock, timer, date, weather, notes, calculator, system monitor, help, clear, organ manager, data view, theme
- [x] **Widget dragging + resizing** — pointer-based repositioning, corner resize, persisted
- [x] **Paged workspace** — scrollable multi-page canvas with sidebar navigation
- [x] **Multi-session shell** — real PTY sessions via Shell microservice, xterm.js rendering, multiple terminals
- [x] **ZeroMQ Spine** — PUSH/PULL + PUB event bus, `lexicon-toggle`, `lexicon/theme` channels
- [x] **Named workspaces** — create, switch, delete workspaces with independent state
- [x] **Generic organ system** — any URL as a Playwright ghost browser tab, deep structural HTML scraping, pattern matching, field extraction
- [x] **WhatsApp organ** — persistent ghost tab, DOM scraping, chat dashboard widget
- [x] **Theming** — 4 built-in themes, SurrealDB persistence, `lx-*` CSS anchors, Spine channel, natural language control
- [ ] **More Organs** — Discord, Gmail, etc.
- [ ] **CLI event tool** — `lexicon push "reminder text"` from terminal via Spine
- [ ] **SysMon daemon** — push system metrics on schedule via Spine

---

## License

MIT

---

<p align="center">
  Built by <a href="https://github.com/vardhin">@vardhin</a>
</p>