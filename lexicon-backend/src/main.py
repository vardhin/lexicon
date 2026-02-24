import json
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
