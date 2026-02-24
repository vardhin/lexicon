#!/usr/bin/env python3
"""Test the full Memory flow: save state, disconnect, reconnect, get restore."""
import asyncio
import json
import websockets


async def test():
    uri = "ws://127.0.0.1:8000/ws"

    # ── Session 1: open a clock, then save state and disconnect ──
    print("── Session 1: open clock, save state ──")
    async with websockets.connect(uri) as ws1:
        # handshake
        msg = json.loads(await ws1.recv())
        print(f"  ✅ Handshake: {msg['type']}")

        # might get RESTORE_STATE if there's old data — consume it
        try:
            peek = await asyncio.wait_for(ws1.recv(), timeout=0.5)
            peek_data = json.loads(peek)
            if peek_data["type"] == "RESTORE_STATE":
                print(f"  ℹ️  Old state found: {len(peek_data['widgets'])} widget(s)")
        except asyncio.TimeoutError:
            print("  ℹ️  No old state")

        # ask for clock
        await ws1.send(json.dumps({"type": "query", "text": "clock"}))
        msg = json.loads(await ws1.recv())
        print(f"  ✅ Got: {msg['type']} widget_type={msg.get('widget_type')}")
        assert msg["type"] == "RENDER_WIDGET"
        assert msg["widget_type"] == "clock"

        # simulate frontend saving state before close
        saved_widget = {
            "id": msg["widget_id"],
            "type": msg["widget_type"],
            "x": msg["x"],
            "y": msg["y"],
            "w": msg["w"],
            "h": msg["h"],
            "props": msg["props"],
        }
        await ws1.send(json.dumps({"type": "save_state", "widgets": [saved_widget]}))
        await asyncio.sleep(0.3)  # let it persist
        print(f"  ✅ Saved state: 1 widget")

    print("  🔌 Session 1 closed\n")

    # ── Session 2: reconnect, should get RESTORE_STATE with the clock ──
    print("── Session 2: reconnect, expect restore ──")
    async with websockets.connect(uri) as ws2:
        # handshake
        msg = json.loads(await ws2.recv())
        print(f"  ✅ Handshake: {msg['type']}")

        # should immediately get RESTORE_STATE
        msg = json.loads(await ws2.recv())
        print(f"  ✅ Got: {msg['type']}")
        assert msg["type"] == "RESTORE_STATE"
        assert len(msg["widgets"]) == 1

        w = msg["widgets"][0]
        print(f"  ✅ Restored widget: type={w['type']} at ({w['x']},{w['y']}) {w['w']}x{w['h']}")
        assert w["type"] == "clock"
        assert w["x"] == 50
        assert w["y"] == 50

    print("  🔌 Session 2 closed\n")

    # ── Session 3: clear state, reconnect, should be empty ──
    print("── Session 3: clear, verify empty ──")
    async with websockets.connect(uri) as ws3:
        msg = json.loads(await ws3.recv())  # handshake
        msg = json.loads(await ws3.recv())  # restore
        print(f"  ℹ️  Got restore with {len(msg.get('widgets', []))} widget(s)")

        # save empty state
        await ws3.send(json.dumps({"type": "save_state", "widgets": []}))
        await asyncio.sleep(0.3)
        print(f"  ✅ Saved empty state")

    async with websockets.connect(uri) as ws4:
        msg = json.loads(await ws4.recv())  # handshake
        # should NOT get RESTORE_STATE (empty list = no restore)
        try:
            msg = await asyncio.wait_for(ws4.recv(), timeout=0.5)
            data = json.loads(msg)
            if data["type"] == "RESTORE_STATE":
                assert len(data["widgets"]) == 0
                print(f"  ✅ Restore sent with 0 widgets (correct)")
            else:
                print(f"  ✅ No restore sent (correct)")
        except asyncio.TimeoutError:
            print(f"  ✅ No restore sent (correct)")

    print("\n🎉 All memory tests passed!")


asyncio.run(test())
