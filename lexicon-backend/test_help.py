#!/usr/bin/env python3
"""Test the help widget — should return all extension help entries."""
import asyncio
import json
import websockets


async def test():
    uri = "ws://127.0.0.1:8000/ws"

    async with websockets.connect(uri) as ws:
        # handshake
        msg = json.loads(await ws.recv())
        assert msg["type"] == "connected"
        print(f"✅ Handshake")

        # consume any RESTORE_STATE
        try:
            peek = await asyncio.wait_for(ws.recv(), timeout=0.5)
            data = json.loads(peek)
            if data["type"] == "RESTORE_STATE":
                print(f"  ℹ️  Restore: {len(data['widgets'])} widget(s)")
        except asyncio.TimeoutError:
            pass

        # ── Test "help" ──
        await ws.send(json.dumps({"type": "query", "text": "help"}))
        msg = json.loads(await ws.recv())
        assert msg["type"] == "RENDER_WIDGET", f"Expected RENDER_WIDGET, got {msg['type']}"
        assert msg["widget_type"] == "help", f"Expected help, got {msg['widget_type']}"
        entries = msg["props"].get("entries", [])
        print(f"✅ Help widget rendered with {len(entries)} entries:")
        for e in entries:
            examples_str = ", ".join(e["examples"])
            print(f"   {e['icon']} {e['title']:16s} — {e['description']}")
            print(f"     examples: {examples_str}")
        
        assert len(entries) >= 9, f"Expected at least 9 entries (got {len(entries)})"
        
        # Verify all known extensions are present
        titles = [e["title"] for e in entries]
        for expected in ["Clock", "Timer", "Date", "Note", "Calculator", "System Monitor", "Weather", "Clear", "Help"]:
            assert expected in titles, f"Missing help entry for '{expected}'"
            print(f"  ✅ Found: {expected}")

        # ── Test "?" alias ──
        await ws.send(json.dumps({"type": "query", "text": "?"}))
        msg = json.loads(await ws.recv())
        assert msg["widget_type"] == "help"
        print(f"✅ '?' alias works")

        # ── Test "commands" alias ──
        await ws.send(json.dumps({"type": "query", "text": "commands"}))
        msg = json.loads(await ws.recv())
        assert msg["widget_type"] == "help"
        print(f"✅ 'commands' alias works")

    print("\n🎉 Help widget tests passed!")


asyncio.run(test())
