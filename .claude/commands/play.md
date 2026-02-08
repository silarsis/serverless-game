# /play — Local Game Runner: Start, Connect, Play

Start the game server in Docker, connect via WebSocket, and play the MUD interactively as an AI agent.

## Arguments
- `$ARGUMENTS` — Optional: a goal or play style (e.g., "explore the world", "map everything", "find items", "just look around"). If empty, do a general exploration session.

## Workflow

### 1. Ensure Docker Environment is Running

a. Check if the game containers are already running:
   ```
   docker-compose ps
   ```
b. If not running, start them:
   ```
   docker-compose up -d
   ```
c. Wait for health check to pass:
   ```
   curl -s http://localhost:8000/health
   ```
   - If health check fails, wait 10 seconds and retry (max 6 attempts)
   - If still failing, check `docker logs serverless-game-server` and `docker logs serverless-game-localstack` for errors

### 2. Connect and Play

Run the game session **inside the game-server container** to avoid Windows WebSocket networking issues:
```
docker exec serverless-game-server python -c "<game_client_code>"
```

The game client code should:

a. **Login** — POST to `http://localhost:8000/api/auth/login` with `{"token": "dev"}`
   - Extract `jwt` and `entity.uuid` from response

b. **Connect WebSocket** — Use `aiohttp.ClientSession` to connect to `ws://localhost:8000/ws?token={jwt}`
   - Read the greeting message
   - Send `possess` command with the entity UUID
   - Drain initial messages (auto-look result)

c. **Play interactively** — Send commands and read responses:
   - Available commands: `look`, `move <direction>`, `examine <item_uuid>`, `take <item_uuid>`, `drop <item_uuid>`, `inventory`, `say <message>`, `whisper <target_uuid> <message>`, `emote <action>`, `suggest <text>`, `suggestions`, `vote <suggestion_uuid>`, `help`
   - Move directions: `north`, `south`, `east`, `west`, `up`, `down`
   - The `look` response contains: `description`, `coordinates`, `exits` (list of directions), `contents` (list of entity UUIDs), `biome`
   - The `move` response contains: `direction`, `description`, `coordinates`, `exits`, `biome` — new rooms are procedurally generated on first visit
   - The `examine` response contains: `name`, `description`, `properties`
   - Contents UUIDs include terrain entities (can't pick up) and items — try `examine` first to identify them, then `take` if appropriate

d. **Command format** — All commands are JSON:
   ```json
   {"command": "look", "data": {}}
   {"command": "move", "data": {"direction": "north"}}
   {"command": "examine", "data": {"item_uuid": "<uuid>"}}
   {"command": "say", "data": {"message": "Hello!"}}
   ```

e. **Response handling** — Each response has a `type` field:
   - `look` — Room description with coordinates, exits, contents, biome
   - `move` — Movement result with new room info
   - `examine` — Item details
   - `take_confirm` / `drop_confirm` — Pickup/drop confirmation
   - `inventory` — List of carried items
   - `say_confirm` / `say` — Chat messages
   - `help` — List of available commands
   - `error` — Error message (e.g., "There is no exit to the east.")
   - `system` — System messages
   - `arrive` / `depart` — Other entities entering/leaving the room

### 3. Play Strategy Based on Goal

Based on `$ARGUMENTS`:

- **"explore" / empty** — Systematically move in all available directions, look at each room, examine contents. Track visited coordinates to build a mental map. Try to visit at least 10-15 rooms.
- **"map"** — Explore methodically and build an ASCII map of the world. Record coordinates, biomes, exits, and landmarks.
- **"find items"** — Explore rooms, examine all contents, try to take any items that aren't terrain. Build an inventory.
- **"interact"** — Focus on saying things, examining everything, testing all commands.
- **"stress test"** — Rapid movement in all directions, exercising all commands, checking for errors.
- **Custom goal** — Interpret the user's intent and play accordingly.

### 4. Report Results

After the play session, report:
- Rooms visited (coordinates, biomes, notable features)
- Items found or collected
- Any errors encountered
- Map of explored area (ASCII if possible)
- Any observations about the game world

## Important Rules
- Always run the game client inside the Docker container using `docker exec serverless-game-server python -c "..."` to avoid WebSocket issues
- Use `aiohttp` for WebSocket connections (it's already installed in the container), NOT the `websockets` library
- Always `await asyncio.sleep(0.3)` between commands to let the server process
- Drain all messages with a 1-second timeout after each command
- The player entity UUID is deterministic (uuid5 of "player-dev-user-001") so it persists across sessions
- Terrain entities (grass, rocks, logs, etc.) cannot be picked up — `take` will return "You can't pick that up."
- New rooms are generated procedurally when you move to unexplored coordinates
- If you encounter another player (another agent!), try to interact with `say` or `whisper`
