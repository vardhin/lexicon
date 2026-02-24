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

manager = ConnectionManager()
engine = GrammarEngine()
memory = Memory()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🧠 Lexicon Brain starting up...")
    await memory.connect()
    yield
    print("🧠 Lexicon Brain shutting down...")
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

    try:
        await ws.send_json({"type": "connected", "connection_id": conn_id})

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

    except WebSocketDisconnect:
        manager.disconnect(conn_id)
    except Exception as e:
        print(f"❌ {conn_id}: {e}")
        manager.disconnect(conn_id)
