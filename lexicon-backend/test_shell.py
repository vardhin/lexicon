#!/usr/bin/env python3
"""Test shell execution — real zsh env, persistence, and restore."""
import asyncio
import json
import websockets


async def test():
    uri = "ws://127.0.0.1:8000/ws"

    async with websockets.connect(uri) as ws:
        msg = json.loads(await ws.recv())
        assert msg["type"] == "connected"
        print(f"✅ Handshake")

        # consume RESTORE_STATE and RESTORE_SHELL
        for _ in range(3):
            try:
                peek = await asyncio.wait_for(ws.recv(), timeout=0.5)
                data = json.loads(peek)
                if data["type"] == "RESTORE_STATE":
                    print(f"  ℹ️  Restore widgets: {len(data.get('widgets', []))}")
                elif data["type"] == "RESTORE_SHELL":
                    print(f"  ℹ️  Restore shell: {len(data.get('sessions', []))} sessions")
            except asyncio.TimeoutError:
                break

        # ── Test 1: echo ──
        async def run_shell(cmd, shell_id):
            await ws.send(json.dumps({"type": "shell", "cmd": cmd, "shell_id": shell_id}))
            lines = []
            exit_code = None
            while True:
                resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                if resp["type"] == "SHELL_OUTPUT" and resp["shell_id"] == shell_id:
                    lines.append(resp["text"])
                elif resp["type"] == "SHELL_DONE" and resp["shell_id"] == shell_id:
                    exit_code = resp["exit_code"]
                    break
            return "".join(lines).strip(), exit_code

        out, code = await run_shell("echo hello world", "t1")
        assert out == "hello world" and code == 0
        print(f"✅ echo → '{out}' (exit {code})")

        # ── Test 2: zsh env — check PATH has cargo ──
        out, code = await run_shell("echo $PATH", "t2")
        assert ".cargo/bin" in out, f"Expected cargo in PATH, got: {out[:200]}"
        print(f"✅ zsh PATH includes .cargo/bin")

        # ── Test 3: zsh env — bun available ──
        out, code = await run_shell("which bun", "t3")
        assert "bun" in out and code == 0
        print(f"✅ 'which bun' → {out.strip()}")

        # ── Test 4: zsh env — cargo available ──
        out, code = await run_shell("which cargo", "t4")
        assert "cargo" in out and code == 0
        print(f"✅ 'which cargo' → {out.strip()}")

        # ── Test 5: git works (full env) ──
        out, code = await run_shell("git --version", "t5")
        assert "git version" in out and code == 0
        print(f"✅ git → {out.strip()}")

        # ── Test 6: failed command ──
        out, code = await run_shell("false", "t6")
        assert code != 0
        print(f"✅ 'false' → exit {code}")

        # ── Test 7: ls our own extensions ──
        out, code = await run_shell(
            "ls /home/vardhin/Documents/git/lexicon/extensions/*.py | wc -l", "t7"
        )
        count = int(out.strip())
        assert count >= 9, f"Expected >= 9 extensions, got {count}"
        print(f"✅ extensions count: {count}")

    print("\n── Session 2: test shell history restore ──")
    async with websockets.connect(uri) as ws:
        msg = json.loads(await ws.recv())
        assert msg["type"] == "connected"

        restored_shell = False
        for _ in range(3):
            try:
                peek = await asyncio.wait_for(ws.recv(), timeout=0.5)
                data = json.loads(peek)
                if data["type"] == "RESTORE_SHELL":
                    sessions = data.get("sessions", [])
                    restored_shell = True
                    print(f"✅ Restore shell: {len(sessions)} sessions")
                    # Check that our test commands are in there
                    cmds = [s["cmd"] for s in sessions]
                    assert "echo hello world" in cmds, f"Missing 'echo hello world' in restored cmds"
                    assert "which bun" in cmds, f"Missing 'which bun' in restored cmds"
                    print(f"✅ Found 'echo hello world' and 'which bun' in restored history")
                    # Check that output was stored
                    echo_session = [s for s in sessions if s["cmd"] == "echo hello world"]
                    assert len(echo_session) > 0
                    assert "hello world" in echo_session[0]["output"]
                    print(f"✅ Stored output for 'echo hello world': '{echo_session[0]['output'].strip()}'")
            except asyncio.TimeoutError:
                break

        assert restored_shell, "Expected RESTORE_SHELL but didn't get it"

    print("\n🎉 All shell tests passed!")


asyncio.run(test())
