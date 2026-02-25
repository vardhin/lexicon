import asyncio
import json
import os
import uuid
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware

from src.engine import GrammarEngine
from src.connection_manager import ConnectionManager
from src.memory import Memory
from src.shell import ShellManager
from src.spine import Spine

manager = ConnectionManager()
engine = GrammarEngine()
memory = Memory()
spine = Spine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🧠 Lexicon Brain starting up...")
    await memory.connect()

    # ── Start the Spine (Layer 2 — ZeroMQ event bus) ──
    await spine.start()

    # Register toggle handler: when any script publishes to lexicon/toggle,
    # broadcast TOGGLE_VISIBILITY to all connected WebSocket clients (the Body).
    async def handle_toggle(channel: str, payload: str):
        await manager.broadcast({"type": "TOGGLE_VISIBILITY"})

    spine.on("lexicon/toggle", handle_toggle)

    # Register WhatsApp message handler from Spine
    async def handle_whatsapp(channel: str, payload: str):
        """Handle WhatsApp messages arriving via ZeroMQ (future: CLI push)."""
        try:
            data = json.loads(payload)
            await _process_whatsapp_message(data)
        except Exception as e:
            print(f"⚠️  Spine WhatsApp handler error: {e}")

    spine.on("lexicon/whatsapp", handle_whatsapp)

    yield
    print("🧠 Lexicon Brain shutting down...")
    await spine.stop()
    await memory.close()
    await manager.disconnect_all()


app = FastAPI(title="Lexicon Brain", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "alive", "connections": manager.active_count}


@app.post("/toggle")
async def toggle_visibility():
    """Toggle the overlay visibility. Can be called via curl or any HTTP client."""
    await manager.broadcast({"type": "TOGGLE_VISIBILITY"})
    return {"status": "toggled"}


@app.get("/system")
async def system_stats():
    """Return live CPU, RAM, disk, and uptime stats from /proc (Linux only)."""
    stats = {"cpu": 0.0, "ram": {"used": 0, "total": 0, "percent": 0}, "disk": {"used": 0, "total": 0, "percent": 0}, "uptime": ""}

    # CPU usage from /proc/stat (snapshot — rough average since boot)
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        idle = int(parts[4])
        total = sum(int(x) for x in parts[1:])
        stats["cpu"] = round((1 - idle / total) * 100, 1) if total > 0 else 0.0
    except Exception:
        pass

    # RAM from /proc/meminfo
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                mem[k.strip()] = int(v.strip().split()[0]) * 1024  # kB -> bytes
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", mem.get("MemFree", 0))
        used = total - avail
        stats["ram"] = {
            "used": used,
            "total": total,
            "percent": round(used / total * 100, 1) if total > 0 else 0,
        }
    except Exception:
        pass

    # Disk from os.statvfs
    try:
        st = os.statvfs("/")
        total = st.f_frsize * st.f_blocks
        free = st.f_frsize * st.f_bavail
        used = total - free
        stats["disk"] = {
            "used": used,
            "total": total,
            "percent": round(used / total * 100, 1) if total > 0 else 0,
        }
    except Exception:
        pass

    # Uptime from /proc/uptime
    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
        d = secs // 86400
        h = (secs % 86400) // 3600
        m = (secs % 3600) // 60
        parts = []
        if d > 0:
            parts.append(f"{d}d")
        if h > 0:
            parts.append(f"{h}h")
        parts.append(f"{m}m")
        stats["uptime"] = " ".join(parts)
    except Exception:
        pass

    return stats


# ── WhatsApp Organ endpoints ──────────────────────────

# Track WhatsApp organ status
_whatsapp_status = {"status": "disconnected", "timestamp": None}


async def _process_whatsapp_message(data: dict):
    """Shared logic: store a WhatsApp message and broadcast to all clients."""
    contact = data.get("contact", "Unknown")
    chat = data.get("chat", contact)
    text = data.get("text", "")
    timestamp = data.get("timestamp", datetime.utcnow().isoformat())
    message_id = data.get("message_id", f"msg-{uuid.uuid4().hex[:8]}")
    unread_count = data.get("unread_count", 0)

    # Store in SurrealDB — creates contact node if needed
    await memory.store_whatsapp_message(
        contact=contact,
        chat=chat,
        text=text,
        timestamp=timestamp,
        message_id=message_id,
        unread_count=unread_count,
    )

    # Broadcast to all connected frontends
    await manager.broadcast({
        "type": "WHATSAPP_MESSAGE",
        "contact": contact,
        "chat": chat,
        "text": text,
        "timestamp": timestamp,
        "message_id": message_id,
        "unread_count": unread_count,
    })


@app.post("/whatsapp/message")
async def whatsapp_message(request: Request):
    """Receive a single WhatsApp message from the injected DOM monitor."""
    data = await request.json()
    await _process_whatsapp_message(data)
    return {"status": "ok"}


@app.post("/whatsapp/batch")
async def whatsapp_batch(request: Request):
    """Receive a BATCH of WhatsApp messages in one request.

    The monitor JS collects messages for ~500ms then flushes them all at once.
    We store them all, then broadcast a single WHATSAPP_BATCH event to frontends
    instead of N individual WHATSAPP_MESSAGE events. This prevents stuttering.
    """
    batch = await request.json()
    if not isinstance(batch, list):
        return {"status": "error", "detail": "expected array"}

    stored = []
    for data in batch:
        contact = data.get("contact", "Unknown")
        chat = data.get("chat", contact)
        text = data.get("text", "")
        timestamp = data.get("timestamp", datetime.utcnow().isoformat())
        message_id = data.get("message_id", f"msg-{uuid.uuid4().hex[:8]}")
        unread_count = data.get("unread_count", 0)

        # Store each message
        await memory.store_whatsapp_message(
            contact=contact,
            chat=chat,
            text=text,
            timestamp=timestamp,
            message_id=message_id,
            unread_count=unread_count,
        )

        stored.append({
            "contact": contact,
            "chat": chat,
            "text": text,
            "timestamp": timestamp,
            "message_id": message_id,
            "unread_count": unread_count,
        })

    # Single broadcast for the whole batch
    if stored:
        await manager.broadcast({
            "type": "WHATSAPP_BATCH",
            "messages": stored,
            "count": len(stored),
        })

    return {"status": "ok", "count": len(stored)}


@app.post("/whatsapp/status")
async def whatsapp_status_update(request: Request):
    """Receive status updates from the WhatsApp organ."""
    global _whatsapp_status
    data = await request.json()
    _whatsapp_status = {
        "status": data.get("status", "unknown"),
        "timestamp": data.get("timestamp", datetime.utcnow().isoformat()),
    }
    # Broadcast status to frontends
    await manager.broadcast({
        "type": "WHATSAPP_STATUS",
        "status": _whatsapp_status["status"],
        "timestamp": _whatsapp_status["timestamp"],
    })
    return {"status": "ok"}


@app.get("/whatsapp/status")
async def whatsapp_get_status():
    """Get current WhatsApp organ connection status."""
    return _whatsapp_status


@app.post("/whatsapp/hide")
async def whatsapp_hide():
    """Hide the WhatsApp organ overlay. Called from injected JS via HTTP."""
    await manager.broadcast({"type": "WHATSAPP_HIDE"})
    return {"status": "hidden"}


# ── WhatsApp DOM debug ──

_whatsapp_debug: dict = {"snapshot": None, "scan_report": None, "selector_cache": {}}


@app.post("/whatsapp/debug")
async def whatsapp_debug_post(request: Request):
    """Receive a DOM debug snapshot from the WhatsApp monitor JS."""
    data = await request.json()
    _whatsapp_debug["snapshot"] = data.get("snapshot")
    _whatsapp_debug["scan_report"] = data.get("scan_report")
    return {"status": "ok"}


@app.get("/whatsapp/debug")
async def whatsapp_debug_get():
    """Get the latest DOM debug snapshot."""
    return {
        "snapshot": _whatsapp_debug.get("snapshot"),
        "scan_report": _whatsapp_debug.get("scan_report"),
    }


@app.post("/whatsapp/debug/query")
async def whatsapp_debug_query(request: Request):
    """Send a CSS selector query to the WhatsApp organ. The organ evaluates it
    against its live DOM and sends the result back via POST /whatsapp/debug/query/result."""
    data = await request.json()
    selector = data.get("selector", "")
    # Store the pending query — the monitor JS polls for it
    _whatsapp_debug["pending_query"] = selector
    _whatsapp_debug["query_results"] = None

    # Wait briefly for results (the monitor checks every second)
    import asyncio
    for _ in range(15):  # 1.5s max wait
        await asyncio.sleep(0.1)
        if _whatsapp_debug.get("query_results") is not None:
            results = _whatsapp_debug["query_results"]
            _whatsapp_debug["query_results"] = None
            return results

    return {"count": 0, "results": [], "error": "timeout"}


@app.get("/whatsapp/debug/pending")
async def whatsapp_debug_pending():
    """Get any pending CSS selector query for the monitor to evaluate."""
    q = _whatsapp_debug.get("pending_query")
    if q:
        _whatsapp_debug["pending_query"] = None
        return {"selector": q}
    return {"selector": None}


@app.post("/whatsapp/debug/query/result")
async def whatsapp_debug_query_result(request: Request):
    """Receive CSS selector query results from the monitor JS."""
    data = await request.json()
    _whatsapp_debug["query_results"] = data
    return {"status": "ok"}


@app.get("/whatsapp/contacts")
async def whatsapp_contacts():
    """Get all known WhatsApp contacts."""
    contacts = await memory.get_whatsapp_contacts()
    return {"contacts": contacts}


@app.get("/whatsapp/messages")
async def whatsapp_messages(contact: str = None, limit: int = 50):
    """Get recent WhatsApp messages, optionally filtered by contact."""
    messages = await memory.get_whatsapp_messages(contact=contact, limit=limit)
    return {"messages": messages}


@app.get("/whatsapp/chats")
async def whatsapp_chats(limit: int = 20):
    """Get a summary of recent chats (latest message per contact)."""
    chats = await memory.get_whatsapp_chats_summary(limit=limit)
    return {"chats": chats}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    conn_id = str(uuid.uuid4())[:8]
    await manager.connect(ws, conn_id)

    # Each connection gets its own shell manager (multiple sessions)
    shell = ShellManager()

    try:
        await ws.send_json({"type": "connected", "connection_id": conn_id})

        # Send workspace info
        workspaces = await memory.list_workspaces()
        current_ws = await memory.get_current_workspace()
        await ws.send_json({
            "type": "WORKSPACE_INFO",
            "workspaces": workspaces,
            "current": current_ws,
        })

        # Restore previous UI state
        saved_widgets = await memory.load_state()
        if saved_widgets:
            await ws.send_json({
                "type": "RESTORE_STATE",
                "widgets": saved_widgets,
            })

        while True:
            raw = await ws.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"type": "query", "text": raw}

            msg_type = payload.get("type", "query")

            if msg_type == "query":
                text = payload.get("text", "").strip()
                if text:
                    await memory.log_command(text)
                    for action in engine.process(text):
                        # Inject help entries for the help widget
                        if (
                            action.get("type") == "RENDER_WIDGET"
                            and action.get("widget_type") == "help"
                        ):
                            action.setdefault("props", {})["entries"] = engine.get_help_entries()
                        await ws.send_json(action)

            elif msg_type == "save_state":
                widgets = payload.get("widgets", [])
                await memory.save_state(widgets)

            elif msg_type == "dismiss_widget":
                await ws.send_json({
                    "type": "REMOVE_WIDGET",
                    "widget_id": payload.get("widget_id"),
                })

            elif msg_type == "dismiss_all":
                await ws.send_json({"type": "CLEAR_WIDGETS"})

            # ── Shell (PTY via Shell Microservice — multi-session) ──

            elif msg_type == "shell_spawn":
                session_id = payload.get("session_id", "default")
                cols = payload.get("cols", 120)
                rows = payload.get("rows", 30)
                await shell.spawn(session_id, ws, cols, rows)

            elif msg_type == "shell_input":
                session_id = payload.get("session_id", "default")
                data = payload.get("data", "")
                if data:
                    await shell.send_input(session_id, data)

            elif msg_type == "shell_resize":
                session_id = payload.get("session_id", "default")
                cols = payload.get("cols", 120)
                rows = payload.get("rows", 30)
                await shell.resize(session_id, cols, rows)

            elif msg_type == "shell_signal":
                session_id = payload.get("session_id", "default")
                sig = payload.get("sig", "INT")
                await shell.send_signal(session_id, sig)

            elif msg_type == "shell_kill":
                session_id = payload.get("session_id", "default")
                await shell.kill(session_id)

            # ── Workspace operations ──

            elif msg_type == "clear_workspace":
                await memory.clear_state()
                await ws.send_json({"type": "CLEAR_WIDGETS"})
                await ws.send_json({"type": "CLEAR_SHELL"})

            elif msg_type == "list_workspaces":
                workspaces = await memory.list_workspaces()
                current_ws = await memory.get_current_workspace()
                await ws.send_json({
                    "type": "WORKSPACE_INFO",
                    "workspaces": workspaces,
                    "current": current_ws,
                })

            elif msg_type == "create_workspace":
                name = payload.get("name", "").strip()
                if name:
                    await memory.save_state(
                        [{"id": w["id"], "type": w["type"], "x": w["x"], "y": w["y"],
                          "w": w["w"], "h": w["h"], "props": w.get("props", {})}
                         for w in payload.get("current_widgets", [])]
                    ) if payload.get("current_widgets") else None
                    await memory.create_workspace(name)
                    # Load the new (empty) workspace
                    await ws.send_json({"type": "CLEAR_WIDGETS"})
                    await ws.send_json({"type": "CLEAR_SHELL"})
                    workspaces = await memory.list_workspaces()
                    await ws.send_json({
                        "type": "WORKSPACE_INFO",
                        "workspaces": workspaces,
                        "current": name,
                    })

            elif msg_type == "switch_workspace":
                name = payload.get("name", "").strip()
                if name:
                    # Save current workspace state first
                    if payload.get("current_widgets") is not None:
                        await memory.save_state(payload["current_widgets"])
                    await memory.switch_workspace(name)
                    # Send clear, then restore the new workspace
                    await ws.send_json({"type": "CLEAR_WIDGETS"})
                    await ws.send_json({"type": "CLEAR_SHELL"})
                    saved_widgets = await memory.load_state()
                    if saved_widgets:
                        await ws.send_json({
                            "type": "RESTORE_STATE",
                            "widgets": saved_widgets,
                        })
                    workspaces = await memory.list_workspaces()
                    await ws.send_json({
                        "type": "WORKSPACE_INFO",
                        "workspaces": workspaces,
                        "current": name,
                    })

            elif msg_type == "delete_workspace":
                name = payload.get("name", "").strip()
                if name and name != "default":
                    current = await memory.get_current_workspace()
                    await memory.delete_workspace(name)
                    if current == name:
                        # Switched back to default — restore it
                        await ws.send_json({"type": "CLEAR_WIDGETS"})
                        await ws.send_json({"type": "CLEAR_SHELL"})
                        saved_widgets = await memory.load_state()
                        if saved_widgets:
                            await ws.send_json({
                                "type": "RESTORE_STATE",
                                "widgets": saved_widgets,
                            })
                    workspaces = await memory.list_workspaces()
                    await ws.send_json({
                        "type": "WORKSPACE_INFO",
                        "workspaces": workspaces,
                        "current": await memory.get_current_workspace(),
                    })

            # ── WhatsApp operations ──

            elif msg_type == "whatsapp_get_chats":
                limit = payload.get("limit", 20)
                chats = await memory.get_whatsapp_chats_summary(limit=limit)
                contacts = await memory.get_whatsapp_contacts()
                await ws.send_json({
                    "type": "WHATSAPP_CHATS",
                    "chats": chats,
                    "contacts": contacts,
                    "organ_status": _whatsapp_status.get("status", "disconnected"),
                })

            elif msg_type == "whatsapp_get_messages":
                contact = payload.get("contact")
                limit = payload.get("limit", 50)
                messages = await memory.get_whatsapp_messages(contact=contact, limit=limit)
                await ws.send_json({
                    "type": "WHATSAPP_MESSAGES",
                    "contact": contact,
                    "messages": messages,
                })

    except WebSocketDisconnect:
        manager.disconnect(conn_id)
        await shell.close_all()
    except Exception as e:
        print(f"❌ {conn_id}: {e}")
        manager.disconnect(conn_id)
        await shell.close_all()
