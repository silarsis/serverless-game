"""Quick demo script to login and play the game via WebSocket."""

import asyncio
import json
import subprocess
import sys

SEP = "=" * 55


async def recv_all(ws, timeout=2):
    """Receive all messages until timeout."""
    import websockets

    msgs = []
    try:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            msgs.append(json.loads(raw))
    except asyncio.TimeoutError:
        pass
    return msgs


def show_msg(m):
    """Pretty-print a game message."""
    t = m.get("type", "")
    if t == "system":
        print(f"[System] {m['message']}")
    elif t == "look":
        print(m["description"])
        print(f"Coords: {m['coordinates']}  Exits: {', '.join(m['exits'])}")
        if m.get("contents"):
            print(f"Here: {m['contents']}")
    elif t == "move":
        print(f"You move {m['direction']}.")
        print(m.get("description", ""))
        print(f"Coords: {m['coordinates']}  Exits: {', '.join(m['exits'])}")
    elif t == "help":
        for c in m["commands"]:
            print(f"  {c['name']:<18}{c['summary']}")
    elif t == "error":
        print(f"[Error] {m.get('message', '')}")
    elif "error" in m:
        print(f"[Error] {m['error']}")
    else:
        print(json.dumps(m, indent=2))


async def main():
    """Login and play."""
    import websockets

    # Login via curl (works reliably on Windows with Docker)
    result = subprocess.run(
        [
            "curl",
            "-s",
            "-X",
            "POST",
            "http://localhost:8000/api/auth/login",
            "-H",
            "Content-Type: application/json",
            "-d",
            '{"token":"dev"}',
        ],
        capture_output=True,
        text=True,
    )
    login = json.loads(result.stdout)
    jwt = login["jwt"]
    eid = login["entity"]["uuid"]
    print(f"Logged in as: {login['user']['name']}")
    print(f"Entity: {eid[:8]}...")
    print()

    uri = f"ws://localhost:8000/ws?token={jwt}"
    async with websockets.connect(uri) as ws:
        # Greeting
        g = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(SEP)
        show_msg(g)
        print(SEP)

        # Possess
        await ws.send(json.dumps({"command": "possess", "data": {"entity_uuid": eid}}))
        print()
        for m in await recv_all(ws):
            show_msg(m)

        # Commands to run
        commands = [
            ("look", {}),
            ("move", {"direction": "north"}),
            ("look", {}),
            ("move", {"direction": "south"}),
            ("move", {"direction": "east"}),
            ("look", {}),
            ("move", {"direction": "west"}),
            ("help", {}),
        ]

        for cmd, data in commands:
            label = cmd
            if "direction" in data:
                label += " " + data["direction"]
            print()
            print(SEP)
            print(f"> {label}")
            print(SEP)
            await ws.send(json.dumps({"command": cmd, "data": data}))
            for m in await recv_all(ws):
                show_msg(m)


if __name__ == "__main__":
    asyncio.run(main())
