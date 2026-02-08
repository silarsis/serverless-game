"""Quick demo script to login and play the game via WebSocket.

Runs the game client inside the Docker container to avoid Windows
WebSocket networking issues. Uses aiohttp (available in the container)
instead of the websockets library.

Usage:
    python scripts/play_demo.py              # Basic demo
    python scripts/play_demo.py --explore    # Extended exploration
"""

import json
import subprocess
import sys
import textwrap

SEP = "=" * 55

# Game client code that runs INSIDE the Docker container
GAME_CLIENT = textwrap.dedent(r'''
import asyncio
import json
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "demo"
SEP = "=" * 55

def show(m):
    t = m.get("type", "")
    if t == "system":
        print(f"[System] {m['message']}")
    elif t == "look":
        print(m.get("description", "")[:300])
        print(f"Coords: {m.get('coordinates')}  Exits: {', '.join(m.get('exits', []))}")
        biome = m.get("biome", "")
        if biome:
            print(f"Biome: {biome}")
        contents = m.get("contents", [])
        if contents:
            print(f"Here: {len(contents)} entities")
    elif t == "move":
        print(f"You move {m.get('direction', '?')}.")
        print(m.get("description", "")[:300])
        print(f"Coords: {m.get('coordinates')}  Exits: {', '.join(m.get('exits', []))}")
    elif t == "help":
        for c in m.get("commands", []):
            print(f"  {c['name']:<18}{c['summary']}")
    elif t == "examine":
        print(f"  {m.get('name', '?')}: {m.get('description', '')[:200]}")
        props = m.get("properties", {})
        if props:
            print(f"  Properties: {json.dumps(props)[:200]}")
    elif t in ("take_confirm", "drop_confirm"):
        print(f"  {m.get('message', '')}")
    elif t == "say_confirm":
        print(f"  {m.get('message', '')}")
    elif t == "say":
        print(f"  {m.get('speaker', '?')} says: {m.get('message', '')}")
    elif t == "inventory":
        items = m.get("items", [])
        print(f"  Inventory: {len(items)} items")
        for it in items:
            if isinstance(it, dict):
                print(f"    - {it.get('name', it.get('uuid', str(it)))}")
            else:
                print(f"    - {it}")
    elif t == "arrive":
        print(f"  * {m.get('actor', '?')} arrives.")
    elif t == "depart":
        print(f"  * {m.get('actor', '?')} departs.")
    elif t == "error":
        print(f"  [Error] {m.get('message', '')}")
    elif "error" in m:
        print(f"  [Error] {m['error']}")
    else:
        print(f"  [{t}] {json.dumps(m)[:250]}")

async def drain(ws, timeout=1):
    msgs = []
    while True:
        try:
            m = await asyncio.wait_for(ws.receive_json(), timeout=timeout)
            msgs.append(m)
            show(m)
        except asyncio.TimeoutError:
            break
    return msgs

async def send_cmd(ws, cmd, data=None, label=None):
    if data is None:
        data = {}
    if label is None:
        label = cmd
        if "direction" in data:
            label += " " + data["direction"]
        elif "message" in data:
            label += " " + data["message"]
    print()
    print(SEP)
    print(f"> {label}")
    print(SEP)
    await ws.send_json({"command": cmd, "data": data})
    await asyncio.sleep(0.3)
    return await drain(ws)

async def main():
    import aiohttp

    async with aiohttp.ClientSession() as session:
        # Login
        async with session.post(
            "http://localhost:8000/api/auth/login",
            json={"token": "dev"}
        ) as r:
            login = await r.json()

        jwt = login["jwt"]
        eid = login["entity"]["uuid"]
        print(f"Logged in as: {login['user']['name']}")
        print(f"Entity: {eid[:8]}...")
        print()

        async with session.ws_connect(
            f"http://localhost:8000/ws?token={jwt}"
        ) as ws:
            # Greeting
            msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
            print(SEP)
            show(msg)
            print(SEP)

            # Possess
            await ws.send_json({"command": "possess", "data": {"entity_uuid": eid}})
            await asyncio.sleep(1)
            print()
            await drain(ws)

            if MODE == "explore":
                # Extended exploration
                visited = set()
                await send_cmd(ws, "look")
                visited.add((0, 0, 0))

                # Explore outward from origin
                directions_sequence = [
                    "north", "north", "east", "east",
                    "south", "south", "south", "south",
                    "west", "west", "west", "west",
                    "north", "north", "north", "north",
                    "east", "south",
                ]
                for d in directions_sequence:
                    msgs = await send_cmd(ws, "move", {"direction": d})
                    for m in msgs:
                        if m.get("type") == "move":
                            coords = tuple(m.get("coordinates", []))
                            if coords and coords not in visited:
                                visited.add(coords)
                                # Examine contents of new rooms
                                look_msgs = await send_cmd(ws, "look")
                                for lm in look_msgs:
                                    if lm.get("type") == "look":
                                        for item_uuid in lm.get("contents", [])[:3]:
                                            if item_uuid != eid:
                                                await send_cmd(
                                                    ws, "examine",
                                                    {"item_uuid": item_uuid},
                                                    f"examine {item_uuid[:8]}..."
                                                )

                await send_cmd(ws, "inventory")
                await send_cmd(ws, "say", {"message": "Done exploring!"})
                print(f"\nVisited {len(visited)} unique rooms.")

            else:
                # Basic demo
                commands = [
                    ("look", {}),
                    ("move", {"direction": "north"}),
                    ("look", {}),
                    ("move", {"direction": "south"}),
                    ("move", {"direction": "east"}),
                    ("look", {}),
                    ("move", {"direction": "west"}),
                    ("say", {"message": "Hello world!"}),
                    ("inventory", {}),
                    ("help", {}),
                ]
                for cmd, data in commands:
                    await send_cmd(ws, cmd, data)

asyncio.run(main())
''').strip()


def main():
    """Run the game demo inside the Docker container."""
    mode = "explore" if "--explore" in sys.argv else "demo"

    # Check if Docker container is running
    result = subprocess.run(
        ["docker", "ps", "--filter", "name=serverless-game-server",
         "--format", "{{.Status}}"],
        capture_output=True, text=True,
    )
    if "Up" not in result.stdout:
        print("Game server container is not running.")
        print("Start it with: docker-compose up -d")
        print("Then re-run this script.")
        sys.exit(1)

    print(f"Running {mode} session inside game-server container...")
    print()

    # Run the game client inside the container
    proc = subprocess.run(
        ["docker", "exec", "serverless-game-server",
         "python", "-c", GAME_CLIENT, mode],
        text=True,
    )
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
