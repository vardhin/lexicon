import asyncio
import json
import os
import uuid
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from src.engine import GrammarEngine
from src.connection_manager import ConnectionManager
from src.memory import Memory
from src.shell import PersistentShell
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


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    conn_id = str(uuid.uuid4())[:8]
    await manager.connect(ws, conn_id)

    # Each connection gets its own persistent shell
    shell = PersistentShell()

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

        # Restore shell history
        shell_sessions = await memory.get_shell_sessions(limit=30)
        if shell_sessions:
            await ws.send_json({
                "type": "RESTORE_SHELL",
                "sessions": shell_sessions,
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

            elif msg_type == "shell":
                cmd = payload.get("cmd", "").strip()
                shell_id = payload.get("shell_id", str(uuid.uuid4())[:8])
                if cmd:
                    await shell.run_command(ws, shell_id, cmd, memory)

            elif msg_type == "shell_kill":
                await shell.kill_current()

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
                    shell_sessions = await memory.get_shell_sessions(limit=30)
                    if shell_sessions:
                        await ws.send_json({
                            "type": "RESTORE_SHELL",
                            "sessions": shell_sessions,
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
                        shell_sessions = await memory.get_shell_sessions(limit=30)
                        if shell_sessions:
                            await ws.send_json({
                                "type": "RESTORE_SHELL",
                                "sessions": shell_sessions,
                            })
                    workspaces = await memory.list_workspaces()
                    await ws.send_json({
                        "type": "WORKSPACE_INFO",
                        "workspaces": workspaces,
                        "current": await memory.get_current_workspace(),
                    })

    except WebSocketDisconnect:
        manager.disconnect(conn_id)
        await shell.close()
    except Exception as e:
        print(f"❌ {conn_id}: {e}")
        manager.disconnect(conn_id)
        await shell.close()
