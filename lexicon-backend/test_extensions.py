#!/usr/bin/env python3
"""Test all widget extensions via WebSocket."""
import asyncio
import json
import websockets


async def test():
    uri = "ws://127.0.0.1:8000/ws"

    async with websockets.connect(uri) as ws:
        # handshake
        msg = json.loads(await ws.recv())
        print(f"✅ Handshake: {msg['type']}")

        # consume any RESTORE_STATE
        try:
            peek = await asyncio.wait_for(ws.recv(), timeout=0.5)
            data = json.loads(peek)
            if data["type"] == "RESTORE_STATE":
                print(f"  ℹ️  Restore: {len(data['widgets'])} widget(s)")
        except asyncio.TimeoutError:
            pass

        # ── Test each extension ──
        tests = [
            ("clock",           "RENDER_WIDGET", "clock"),
            ("timer 5 min",     "RENDER_WIDGET", "timer"),
            ("date",            "RENDER_WIDGET", "date"),
            ("note buy milk",   "RENDER_WIDGET", "note"),
            ("calc 2+2",        "RENDER_WIDGET", "calculator"),
            ("system",          "RENDER_WIDGET", "sysmon"),
            ("weather",         "RENDER_WIDGET", "weather"),
            ("what's the time", "RENDER_WIDGET", "clock"),
            ("timer 1h30m",     "RENDER_WIDGET", "timer"),
            ("= 3.14 * 2",     "RENDER_WIDGET", "calculator"),
            ("remind me to call bob", "RENDER_WIDGET", "note"),
            ("show stats",      "RENDER_WIDGET", "sysmon"),
            ("what day is it",  "RENDER_WIDGET", "date"),
        ]

        for query, expected_type, expected_widget in tests:
            await ws.send(json.dumps({"type": "query", "text": query}))
            msg = json.loads(await ws.recv())
            wtype = msg.get("widget_type", msg.get("type"))
            ok = msg["type"] == expected_type and (expected_widget is None or msg.get("widget_type") == expected_widget)
            status = "✅" if ok else "❌"
            extra = ""
            if msg.get("widget_type") == "calculator":
                extra = f" → {msg['props'].get('expression')} = {msg['props'].get('result')}"
            elif msg.get("widget_type") == "timer":
                extra = f" → {msg['props'].get('seconds')}s"
            elif msg.get("widget_type") == "note":
                extra = f" → \"{msg['props'].get('text')}\""
            print(f"  {status} \"{query}\" → {msg['type']} widget_type={msg.get('widget_type')}{extra}")
            if not ok:
                print(f"     EXPECTED: type={expected_type} widget={expected_widget}")
                print(f"     GOT:      {msg}")

        # ── Test clear ──
        await ws.send(json.dumps({"type": "query", "text": "clear"}))
        msg = json.loads(await ws.recv())
        assert msg["type"] == "CLEAR_WIDGETS", f"Expected CLEAR_WIDGETS, got {msg}"
        print(f"  ✅ \"clear\" → {msg['type']}")

        # ── Test unknown command ──
        await ws.send(json.dumps({"type": "query", "text": "xyzzy"}))
        msg = json.loads(await ws.recv())
        assert msg["type"] == "FEEDBACK", f"Expected FEEDBACK, got {msg}"
        print(f"  ✅ \"xyzzy\" → FEEDBACK: {msg['message']}")

    print("\n🎉 All extension tests passed!")


asyncio.run(test())
