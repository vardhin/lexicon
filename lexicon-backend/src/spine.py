"""
Spine — ZeroMQ event bus for Lexicon (Layer 2).

The Spine is the nervous system that decouples the Brain (FastAPI)
from external inputs. Any process can push messages to the bus,
and the Brain listens and dispatches.

Architecture:
  - PULL socket binds to tcp://127.0.0.1:5557 (Brain pulls commands from here)
  - PUB  socket binds to tcp://127.0.0.1:5556 (Brain publishes events outward)
  - External scripts PUSH to 5557 (connect, send, done — instant, no slow-joiner)

Channels:
  - lexicon/toggle     — toggle overlay visibility
  - lexicon/push       — push arbitrary events into the system (future)
  - lexicon/theme      — push CSS morph commands (future)
"""

import asyncio
import zmq
import zmq.asyncio


# The port external scripts PUSH to (Brain PULLs)
SPINE_PULL_PORT = 5557
# The port Brain PUBs on (future: for sensors to SUBscribe)
SPINE_PUB_PORT = 5556

SPINE_PULL_ADDR = f"tcp://127.0.0.1:{SPINE_PULL_PORT}"
SPINE_PUB_ADDR = f"tcp://127.0.0.1:{SPINE_PUB_PORT}"


class Spine:
    """ZeroMQ event bus — Layer 2 of the Lexicon architecture."""

    def __init__(self):
        self._ctx = zmq.asyncio.Context()
        self._pull: zmq.asyncio.Socket | None = None
        self._pub: zmq.asyncio.Socket | None = None
        self._task: asyncio.Task | None = None
        self._handlers: dict[str, list] = {}

    async def start(self):
        """Bind PULL + PUB sockets and begin listening."""
        # PULL socket — receives commands from external scripts (PUSH)
        # PUSH/PULL is reliable: no slow-joiner, no message loss
        self._pull = self._ctx.socket(zmq.PULL)
        self._pull.bind(SPINE_PULL_ADDR)

        # PUB socket — Brain can publish events outward (for future sensors)
        self._pub = self._ctx.socket(zmq.PUB)
        self._pub.bind(SPINE_PUB_ADDR)

        # Start the listener loop
        self._task = asyncio.create_task(self._listen_loop())
        print(f"🦴 Spine started (PULL:{SPINE_PULL_PORT} PUB:{SPINE_PUB_PORT})")

    async def stop(self):
        """Clean shutdown."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._pull:
            self._pull.close()
        if self._pub:
            self._pub.close()
        self._ctx.term()
        print("🦴 Spine stopped")

    def on(self, channel: str, handler):
        """Register an async handler for a channel.

        handler signature: async def handler(channel: str, payload: str)
        """
        self._handlers.setdefault(channel, []).append(handler)

    async def publish(self, channel: str, payload: str = ""):
        """Publish a message on a channel (Brain → outward)."""
        if self._pub:
            msg = f"{channel} {payload}".strip()
            await self._pub.send_string(msg)

    async def _listen_loop(self):
        """Main loop — receive messages and dispatch to handlers."""
        while True:
            try:
                raw = await self._pull.recv_string()
                # Format: "channel payload" or just "channel"
                parts = raw.split(" ", 1)
                channel = parts[0]
                payload = parts[1] if len(parts) > 1 else ""

                handlers = self._handlers.get(channel, [])
                for handler in handlers:
                    try:
                        await handler(channel, payload)
                    except Exception as e:
                        print(f"🦴 handler error on {channel}: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"🦴 Spine recv error: {e}")
                await asyncio.sleep(0.1)
