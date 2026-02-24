#!/usr/bin/env python3
"""Quick test for the Lexicon Brain WebSocket."""
import asyncio
import json
import websockets

async def test():
    uri = "ws://127.0.0.1:8000/ws"
    async with websockets.connect(uri) as ws:
        # Should receive handshake
        msg = await ws.recv()
        data = json.loads(msg)
        print(f"✅ Handshake: {data}")
        assert data["type"] == "connected"

        # Test clock trigger
        await ws.send(json.dumps({"type": "query", "text": "what's the time"}))
        msg = await ws.recv()
        data = json.loads(msg)
        print(f"✅ Clock: type={data['widget_type']} x={data['x']} y={data['y']} w={data['w']} h={data['h']}")
        assert data["type"] == "RENDER_WIDGET"
        assert data["widget_type"] == "clock"
        assert isinstance(data["x"], int)

        # Test clear
        await ws.send(json.dumps({"type": "query", "text": "clear"}))
        msg = await ws.recv()
        data = json.loads(msg)
        print(f"✅ Clear: {data['type']}")
        assert data["type"] == "CLEAR_WIDGETS"

        # Test unknown (feedback)
        await ws.send(json.dumps({"type": "query", "text": "blahblah"}))
        msg = await ws.recv()
        data = json.loads(msg)
        print(f"✅ Feedback: {data['message']}")
        assert data["type"] == "FEEDBACK"

    print("\n🎉 All tests passed!")

asyncio.run(test())
