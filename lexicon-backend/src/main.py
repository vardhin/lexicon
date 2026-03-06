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
from src.organ_manager import OrganManager
from src.entity_resolver import EntityResolver

manager = ConnectionManager()
engine = GrammarEngine()
memory = Memory()
spine = Spine()
organs = OrganManager()
resolver = EntityResolver(memory)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🧠 Lexicon Brain starting up...")
    await memory.connect()

    # ── Start the Spine (Layer 2 — ZeroMQ event bus) ──
    await spine.start()

    # ── Start the Organ Manager (Playwright ghost browser) ──
    await organs.start()

    # Register toggle handler: when any script publishes to lexicon/toggle,
    # broadcast TOGGLE_VISIBILITY to all connected WebSocket clients (the Body).
    async def handle_toggle(channel: str, payload: str):
        await manager.broadcast({"type": "TOGGLE_VISIBILITY"})

    spine.on("lexicon/toggle", handle_toggle)

    # Register theme handler: when any script publishes to lexicon/theme,
    # look up the theme CSS and broadcast APPLY_THEME to all clients.
    async def handle_theme(channel: str, payload: str):
        theme_name = payload.strip()
        if not theme_name:
            return
        theme = await memory.get_theme(theme_name)
        if theme:
            await memory.set_active_theme(theme_name)
            await manager.broadcast({
                "type": "APPLY_THEME",
                "name": theme_name,
                "css": theme.get("css", ""),
            })
        else:
            await manager.broadcast({
                "type": "FEEDBACK",
                "message": f"Theme '{theme_name}' not found",
            })

    spine.on("lexicon/theme", handle_theme)

    yield
    print("🧠 Lexicon Brain shutting down...")
    await organs.stop()
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


# ── Organ Management endpoints (Playwright-powered) ──────────

@app.get("/organs")
async def list_all_organs():
    """List all registered organs with their runtime status."""
    registered = await memory.list_organs()
    open_tabs = await organs.get_open_organs()
    open_ids = {o["organ_id"] for o in open_tabs}

    for o in registered:
        oid = o.get("organ_id", "")
        o["running"] = oid in open_ids
        if oid in open_ids:
            tab = next((t for t in open_tabs if t["organ_id"] == oid), {})
            o["status"] = tab.get("status", "connected")
            o["title"] = tab.get("title", "")
        else:
            o["status"] = "closed"
    return {"organs": registered, "browser_running": organs.is_running}


@app.post("/organs")
async def create_organ(request: Request):
    """Register a new organ. Body: { organ_id, url, name? }"""
    data = await request.json()
    organ_id = data.get("organ_id", "").strip()
    url = data.get("url", "").strip()
    name = data.get("name", "").strip() or organ_id
    if not organ_id or not url:
        return {"status": "error", "detail": "organ_id and url are required"}
    import re
    organ_id = re.sub(r'[^a-zA-Z0-9_-]', '-', organ_id).lower().strip('-')
    if not organ_id:
        return {"status": "error", "detail": "invalid organ_id"}
    await memory.create_organ(organ_id, url, name)
    return {"status": "ok", "organ_id": organ_id}


@app.delete("/organs/{organ_id}")
async def delete_organ(organ_id: str):
    """Delete an organ. Closes its tab if open."""
    await organs.close_organ(organ_id)
    await memory.delete_organ(organ_id)
    return {"status": "ok"}


@app.post("/organs/{organ_id}/launch")
async def launch_organ(organ_id: str):
    """Open an organ's URL as a tab in the ghost browser."""
    organ = await memory.get_organ(organ_id)
    if not organ:
        return {"status": "error", "detail": "organ not found"}
    result = await organs.open_organ(organ_id, organ.get("url", ""))
    return result


@app.post("/organs/{organ_id}/kill")
async def kill_organ(organ_id: str):
    """Close an organ's tab."""
    result = await organs.close_organ(organ_id)
    return result


@app.get("/organs/{organ_id}/status")
async def organ_status_get(organ_id: str):
    """Get current organ status."""
    return organs.get_organ_status(organ_id)


@app.get("/organs/{organ_id}/html")
async def organ_html_get(organ_id: str):
    """Get full page HTML of an organ."""
    return await organs.get_html(organ_id)


# ── Pattern-based scraping ─────────────────────────────────────

@app.post("/organs/{organ_id}/match")
async def organ_match_pattern(organ_id: str, request: Request):
    """Match an outer HTML pattern against the organ's live DOM.

    Body: { "outer_html": "<a class='Link--primary ...' ...>text</a>" }

    Fingerprints the snippet (tag, classes, key attributes) and finds all
    structurally similar elements in the page via similarity scoring.

    Returns: {
        "fingerprint": { tag, classes, attrs },
        "count": N,
        "matches": [ { text, outerHtml, tag, classes, score }, ... ],
    }
    """
    data = await request.json()
    outer_html = data.get("outer_html", "").strip()
    if not outer_html:
        return {"error": "outer_html is required", "count": 0, "matches": []}
    return await organs.match_pattern(organ_id, outer_html)


@app.post("/organs/{organ_id}/scrape")
async def organ_scrape_pattern(organ_id: str, request: Request):
    """Scrape: paste an outer HTML pattern, name it, and store all matching
    elements as structured data in Memory under that class name.

    Body: {
        "class_name": "feed_card",
        "outer_html": "<div class='rounded-2 py-1'>...</div>",
    }

    Flow:
      1. Deep-parse the outer_html to discover inner fields (links, text,
         images, timestamps, etc.)
      2. Fingerprint the root element for similarity matching
      3. Find all similar container elements in the organ's live DOM
      4. Extract structured data from each match using discovered fields
      5. Store structured objects in Memory under organ_id + class_name
      6. Return the matches + discovered field schema

    Returns: {
        "class_name": "feed_card",
        "count": 8,
        "fields": [{ "label": "user", "extract": "text", "example": "alice" }, ...],
        "values": [{ "user": "alice", "repo": "myproject", ... }, ...],
        "fingerprint": { tag, classes, attrs },
    }
    """
    data = await request.json()
    class_name = data.get("class_name", "").strip().lower().replace(" ", "_")
    outer_html = data.get("outer_html", "").strip()
    if not class_name or not outer_html:
        return {"error": "class_name and outer_html are required"}

    # Deep match the pattern (structural analysis + field extraction)
    result = await organs.match_pattern(organ_id, outer_html)
    if result.get("error"):
        return result

    # Extract structured values from matches
    values = []
    for m in result.get("matches", []):
        # Remove internal scoring keys, keep the data
        item = {k: v for k, v in m.items() if not k.startswith('__') and v}
        if item:
            values.append(item)
        else:
            # Fallback: if no structured fields, use flat text
            t = (m.get("__text") or "").strip()
            if t:
                values.append(t)

    # Store the pattern definition in Memory (so it persists and can be re-scraped)
    fields = result.get("fields", [])
    await memory.save_scrape_pattern(organ_id, class_name, outer_html,
                                      result.get("fingerprint", {}), fields)

    # Store the scraped values in Memory (now can be objects OR strings)
    await memory.store_scraped_data(organ_id, class_name, values)

    # Auto-resolve entities from the scraped data
    entity_stats = await resolver.resolve(organ_id, class_name, values)

    return {
        "class_name": class_name,
        "count": len(values),
        "fields": result.get("fields", []),
        "values": values,
        "fingerprint": result.get("fingerprint", {}),
        "entity_resolution": entity_stats,
    }


@app.post("/organs/{organ_id}/rescrape")
async def organ_rescrape(organ_id: str, request: Request):
    """Re-scrape all saved patterns for an organ (or a specific one).

    Body: { "class_name": "contact" }  (optional — omit to rescrape all)

    Returns: { "results": { "contact": { count, values }, ... } }
    """
    data = await request.json()
    target_class = data.get("class_name", "").strip()

    patterns = await memory.get_scrape_patterns(organ_id)
    if not patterns:
        return {"results": {}}

    results = {}
    for pattern in patterns:
        cname = pattern.get("class_name", "")
        if target_class and cname != target_class:
            continue
        ohtml = pattern.get("outer_html", "")
        if not ohtml:
            continue

        match_result = await organs.match_pattern(organ_id, ohtml)
        values = []
        for m in match_result.get("matches", []):
            item = {k: v for k, v in m.items() if not k.startswith('__') and v}
            if item:
                values.append(item)
            else:
                t = (m.get("__text") or "").strip()
                if t:
                    values.append(t)

        await memory.store_scraped_data(organ_id, cname, values)
        # Resolve entities from rescrape
        entity_stats = await resolver.resolve(organ_id, cname, values)
        results[cname] = {"count": len(values), "values": values,
                          "entity_resolution": entity_stats}

    return {"results": results}


@app.get("/organs/{organ_id}/patterns")
async def organ_get_patterns(organ_id: str):
    """Get all saved scrape patterns for an organ."""
    patterns = await memory.get_scrape_patterns(organ_id)
    return {"patterns": patterns}


@app.delete("/organs/{organ_id}/patterns/{class_name}")
async def organ_delete_pattern(organ_id: str, class_name: str):
    """Delete a scrape pattern and its stored data."""
    await memory.delete_scrape_pattern(organ_id, class_name)
    return {"status": "ok"}


@app.get("/organs/{organ_id}/data")
async def organ_get_scraped_data(organ_id: str, class_name: str = None):
    """Get scraped data for an organ, optionally filtered by class_name."""
    data = await memory.get_scraped_data(organ_id, class_name)
    return {"data": data}


@app.get("/organs-data/all")
async def all_organs_data():
    """Get scraped data from ALL organs — used by the dashboard view."""
    organs = await memory.list_organs()
    result = []
    for organ in organs:
        oid = organ.get("organ_id", "")
        if not oid:
            continue
        data = await memory.get_scraped_data(oid)
        for item in data:
            item["organ_id"] = oid
            item["organ_name"] = organ.get("name") or oid
            result.append(item)
    return {"data": result}


# ── Entity Resolution endpoints ──────────────────────────────

@app.get("/entities")
async def list_entities():
    """List all resolved entity nodes (person nodes)."""
    entities = await memory.list_entities()
    stats = await memory.get_entity_stats()
    buffered = await memory.list_buffered_signals()
    stats["buffered_signals"] = len(buffered)
    return {"entities": entities, "stats": stats}


@app.get("/entities/{entity_id}")
async def get_entity(entity_id: str):
    """Get a single entity with all its data and sources."""
    entity = await memory.get_entity(entity_id)
    if not entity:
        return {"error": "entity not found"}
    return {"entity": entity}


@app.get("/entities/search/{query}")
async def search_entities(query: str):
    """Search entities by name, alias, username, or token."""
    results = await memory.search_entities(query)
    return {"results": results, "count": len(results)}


@app.post("/entities/resolve")
async def resolve_all_entities():
    """Re-resolve ALL scraped data across ALL organs from scratch.
    Clears existing entities and rebuilds the knowledge graph."""
    stats = await resolver.resolve_all_sources()
    return {"status": "ok", "stats": stats}


@app.post("/entities/resolve/{organ_id}")
async def resolve_organ_entities(organ_id: str):
    """Resolve entities from a specific organ's scraped data."""
    data = await memory.get_scraped_data(organ_id)
    total_stats = {"created": 0, "merged": 0, "skipped": 0,
                   "buffered": 0, "promoted": 0}
    for dataset in data:
        cname = dataset.get("class_name", "")
        values = dataset.get("values", [])
        if not values:
            continue
        stats = await resolver.resolve(organ_id, cname, values)
        total_stats["created"] += stats["created"]
        total_stats["merged"] += stats["merged"]
        total_stats["skipped"] += stats["skipped"]
        total_stats["buffered"] += stats.get("buffered", 0)
        total_stats["promoted"] += stats.get("promoted", 0)
    return {"status": "ok", "stats": total_stats}


@app.delete("/entities/{entity_id}")
async def delete_entity(entity_id: str):
    """Delete an entity node."""
    await memory.delete_entity(entity_id)
    return {"status": "ok"}


@app.delete("/entities")
async def clear_all_entities():
    """Delete all entity nodes."""
    await memory.clear_entities()
    return {"status": "ok"}


@app.get("/entities/stats/summary")
async def entity_stats():
    """Get entity graph statistics."""
    stats = await memory.get_entity_stats()
    entities = await memory.list_entities()
    # Add source distribution
    source_counts = {}
    for e in entities:
        for src in e.get("sources", []):
            oid = src.get("organ_id", "unknown")
            source_counts[oid] = source_counts.get(oid, 0) + 1
    stats["source_distribution"] = source_counts
    stats["total_aliases"] = sum(
        len(e.get("aliases", [])) for e in entities
    )
    stats["total_usernames"] = sum(
        len(e.get("usernames", [])) for e in entities
    )
    return stats


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

        # Send organ list on connect
        registered_organs = await memory.list_organs()
        await ws.send_json({
            "type": "ORGAN_LIST",
            "organs": registered_organs,
        })

        # Restore active theme on connect
        active_theme_name = await memory.get_active_theme()
        if active_theme_name:
            theme = await memory.get_theme(active_theme_name)
            if theme:
                await ws.send_json({
                    "type": "APPLY_THEME",
                    "name": active_theme_name,
                    "css": theme.get("css", ""),
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

                        # ── Theme actions from the theme extension ──
                        if action.get("type") == "THEME_APPLY":
                            theme_name = action.get("name", "")
                            theme = await memory.get_theme(theme_name)
                            if theme:
                                await memory.set_active_theme(theme_name)
                                await manager.broadcast({
                                    "type": "APPLY_THEME",
                                    "name": theme_name,
                                    "css": theme.get("css", ""),
                                })
                            else:
                                await ws.send_json({
                                    "type": "FEEDBACK",
                                    "message": f"Theme '{theme_name}' not found. Type 'themes' to list available.",
                                })
                            continue

                        if action.get("type") == "THEME_RESET":
                            await memory.set_active_theme(None)
                            await manager.broadcast({
                                "type": "APPLY_THEME",
                                "name": "",
                                "css": "",
                            })
                            await ws.send_json({
                                "type": "FEEDBACK",
                                "message": "Theme reset to default",
                            })
                            continue

                        if action.get("type") == "THEME_LIST_REQUEST":
                            themes = await memory.list_themes()
                            active = await memory.get_active_theme()
                            await ws.send_json({
                                "type": "THEME_LIST",
                                "themes": themes,
                                "active": active,
                            })
                            continue

                        # ── Entity management actions ──

                        if action.get("type") == "ENTITY_CLEAR":
                            await memory.clear_entities()
                            await ws.send_json({
                                "type": "FEEDBACK",
                                "message": "🗑️ All people cleared",
                            })
                            continue

                        if action.get("type") == "ENTITY_DELETE":
                            eid = action.get("entity_id", "")
                            ent = await memory.get_entity(eid)
                            if ent:
                                name = ent.get("canonical_name", eid)
                                await memory.delete_entity(eid)
                                await ws.send_json({
                                    "type": "FEEDBACK",
                                    "message": f"🗑️ Deleted {name}",
                                })
                            else:
                                await ws.send_json({
                                    "type": "FEEDBACK",
                                    "message": f"Entity '{eid}' not found",
                                })
                            continue

                        if action.get("type") == "ENTITY_DELETE_BY_NAME":
                            query = action.get("query", "")
                            results = await memory.search_entities(query)
                            if results:
                                # Delete the best match (first result)
                                ent = results[0]
                                eid = ent.get("entity_id", "")
                                name = ent.get("canonical_name", query)
                                await memory.delete_entity(eid)
                                await ws.send_json({
                                    "type": "FEEDBACK",
                                    "message": f"🗑️ Deleted {name}"
                                    + (f" ({len(results)-1} others matched)"
                                       if len(results) > 1 else ""),
                                })
                            else:
                                await ws.send_json({
                                    "type": "FEEDBACK",
                                    "message": f"No person matching '{query}' found",
                                })
                            continue

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

            # ── Theme operations ──

            elif msg_type == "list_themes":
                themes = await memory.list_themes()
                active = await memory.get_active_theme()
                await ws.send_json({
                    "type": "THEME_LIST",
                    "themes": themes,
                    "active": active,
                })

            elif msg_type == "create_theme":
                name = payload.get("name", "").strip()
                css = payload.get("css", "").strip()
                description = payload.get("description", "").strip()
                if name and css:
                    await memory.create_theme(name, css, description)
                    await ws.send_json({
                        "type": "FEEDBACK",
                        "message": f"Theme '{name}' saved",
                    })
                    # Send updated theme list
                    themes = await memory.list_themes()
                    active = await memory.get_active_theme()
                    await ws.send_json({
                        "type": "THEME_LIST",
                        "themes": themes,
                        "active": active,
                    })
                else:
                    await ws.send_json({
                        "type": "FEEDBACK",
                        "message": "Theme name and CSS are required",
                    })

            elif msg_type == "apply_theme":
                name = payload.get("name", "").strip()
                if name:
                    theme = await memory.get_theme(name)
                    if theme:
                        await memory.set_active_theme(name)
                        # Broadcast to ALL clients so every connected Body updates
                        await manager.broadcast({
                            "type": "APPLY_THEME",
                            "name": name,
                            "css": theme.get("css", ""),
                        })
                    else:
                        await ws.send_json({
                            "type": "FEEDBACK",
                            "message": f"Theme '{name}' not found",
                        })

            elif msg_type == "reset_theme":
                await memory.set_active_theme(None)
                await manager.broadcast({
                    "type": "APPLY_THEME",
                    "name": "",
                    "css": "",
                })

            elif msg_type == "delete_theme":
                name = payload.get("name", "").strip()
                if name:
                    active = await memory.get_active_theme()
                    await memory.delete_theme(name)
                    # If the deleted theme was active, reset
                    if active == name:
                        await memory.set_active_theme(None)
                        await manager.broadcast({
                            "type": "APPLY_THEME",
                            "name": "",
                            "css": "",
                        })
                    await ws.send_json({
                        "type": "FEEDBACK",
                        "message": f"Theme '{name}' deleted",
                    })
                    themes = await memory.list_themes()
                    active_now = await memory.get_active_theme()
                    await ws.send_json({
                        "type": "THEME_LIST",
                        "themes": themes,
                        "active": active_now,
                    })

            elif msg_type == "get_theme":
                name = payload.get("name", "").strip()
                if name:
                    theme = await memory.get_theme(name)
                    if theme:
                        await ws.send_json({
                            "type": "THEME_INFO",
                            "theme": theme,
                        })
                    else:
                        await ws.send_json({
                            "type": "FEEDBACK",
                            "message": f"Theme '{name}' not found",
                        })

    except WebSocketDisconnect:
        manager.disconnect(conn_id)
        await shell.close_all()
    except Exception as e:
        print(f"❌ {conn_id}: {e}")
        manager.disconnect(conn_id)
        await shell.close_all()
