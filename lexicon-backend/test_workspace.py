#!/usr/bin/env python3
"""Test workspace operations — create, switch, clear, delete."""
import asyncio
import json
import websockets


async def recv_until(ws, msg_type, timeout=3):
    """Receive messages until we find the given type."""
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        if msg["type"] == msg_type:
            return msg


async def drain(ws, timeout=0.3):
    """Drain any pending messages."""
    msgs = []
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            msgs.append(json.loads(raw))
        except asyncio.TimeoutError:
            break
    return msgs


async def test():
    uri = "ws://127.0.0.1:8000/ws"

    async with websockets.connect(uri) as ws:
        msg = json.loads(await ws.recv())
        assert msg["type"] == "connected"
        print("✅ Handshake")

        # Should get WORKSPACE_INFO on connect
        info = await recv_until(ws, "WORKSPACE_INFO")
        assert "default" in info["workspaces"]
        assert info["current"] == "default"
        print(f"✅ Initial workspace: '{info['current']}', list: {info['workspaces']}")

        # Drain any RESTORE_STATE / RESTORE_SHELL
        await drain(ws)

        # ── Test 1: Add a widget, then clear workspace ──
        await ws.send(json.dumps({"type": "query", "text": "clock"}))
        render = await recv_until(ws, "RENDER_WIDGET")
        assert render["widget_type"] == "clock"
        print("✅ Added clock widget")

        await ws.send(json.dumps({"type": "clear_workspace"}))
        clear_w = await recv_until(ws, "CLEAR_WIDGETS")
        assert clear_w["type"] == "CLEAR_WIDGETS"
        clear_s = await recv_until(ws, "CLEAR_SHELL")
        assert clear_s["type"] == "CLEAR_SHELL"
        print("✅ Clear workspace → got CLEAR_WIDGETS + CLEAR_SHELL")

        # ── Test 2: Create a new workspace ──
        await ws.send(json.dumps({
            "type": "create_workspace",
            "name": "test-ws",
            "current_widgets": [],
        }))
        # Should get CLEAR_WIDGETS, CLEAR_SHELL, WORKSPACE_INFO
        clear_w = await recv_until(ws, "CLEAR_WIDGETS")
        clear_s = await recv_until(ws, "CLEAR_SHELL")
        info = await recv_until(ws, "WORKSPACE_INFO")
        assert "test-ws" in info["workspaces"]
        assert info["current"] == "test-ws"
        print(f"✅ Created workspace 'test-ws', current: '{info['current']}', list: {info['workspaces']}")

        # ── Test 3: Add a widget in test-ws ──
        await ws.send(json.dumps({"type": "query", "text": "date"}))
        render = await recv_until(ws, "RENDER_WIDGET")
        assert render["widget_type"] == "date"
        # Save it
        await ws.send(json.dumps({
            "type": "save_state",
            "widgets": [{"id": render["widget_id"], "type": "date", "x": 50, "y": 50, "w": 300, "h": 200, "props": {}}],
        }))
        print("✅ Added date widget in test-ws")

        # ── Test 4: Switch back to default ──
        await ws.send(json.dumps({
            "type": "switch_workspace",
            "name": "default",
            "current_widgets": [{"id": render["widget_id"], "type": "date", "x": 50, "y": 50, "w": 300, "h": 200, "props": {}}],
        }))
        clear_w = await recv_until(ws, "CLEAR_WIDGETS")
        clear_s = await recv_until(ws, "CLEAR_SHELL")
        info = await recv_until(ws, "WORKSPACE_INFO")
        assert info["current"] == "default"
        print(f"✅ Switched to 'default', current: '{info['current']}'")

        # Drain restore messages
        msgs = await drain(ws, timeout=0.5)
        types = [m["type"] for m in msgs]
        print(f"  ℹ️  Restore messages: {types}")

        # ── Test 5: Switch back to test-ws, should get date widget ──
        await ws.send(json.dumps({
            "type": "switch_workspace",
            "name": "test-ws",
            "current_widgets": [],
        }))
        clear_w = await recv_until(ws, "CLEAR_WIDGETS")
        clear_s = await recv_until(ws, "CLEAR_SHELL")
        msgs = await drain(ws, timeout=0.5)
        types = [m["type"] for m in msgs]
        found_restore = any(m["type"] == "RESTORE_STATE" for m in msgs)
        info_msgs = [m for m in msgs if m["type"] == "WORKSPACE_INFO"]
        assert len(info_msgs) > 0
        assert info_msgs[0]["current"] == "test-ws"
        print(f"✅ Switched to 'test-ws', restore messages: {types}")
        if found_restore:
            restore = [m for m in msgs if m["type"] == "RESTORE_STATE"][0]
            widget_types = [w["type"] for w in restore.get("widgets", [])]
            print(f"  ✅ Restored widgets: {widget_types}")

        # ── Test 6: Delete test-ws ──
        await ws.send(json.dumps({"type": "delete_workspace", "name": "test-ws"}))
        # Should switch to default and get workspace info
        msgs = await drain(ws, timeout=1)
        types = [m["type"] for m in msgs]
        info_msgs = [m for m in msgs if m["type"] == "WORKSPACE_INFO"]
        assert len(info_msgs) > 0
        assert "test-ws" not in info_msgs[-1]["workspaces"]
        assert info_msgs[-1]["current"] == "default"
        print(f"✅ Deleted 'test-ws', workspaces: {info_msgs[-1]['workspaces']}")

        # ── Test 7: List workspaces ──
        await ws.send(json.dumps({"type": "list_workspaces"}))
        info = await recv_until(ws, "WORKSPACE_INFO")
        assert "default" in info["workspaces"]
        assert "test-ws" not in info["workspaces"]
        print(f"✅ List workspaces: {info['workspaces']}")

    print("\n🎉 All workspace tests passed!")


asyncio.run(test())
