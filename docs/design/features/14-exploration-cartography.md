# Exploration/Cartography Aspect

## What This Brings to the World

A map transforms a confusing grid of rooms into a world the player can mentally inhabit. Without cartography, players move north-south-east-west through rooms described by text, and after twenty moves they have no idea where they are relative to where they started. The game world exists only in the current room description -- everything else is memory, and memory fades. With a map, the player can see the forest they crossed three hours ago, the mountain range to the north they have not explored yet, and the settlement where they left their spare equipment. The world gains spatial permanence. It stops being a series of disconnected rooms and becomes a place.

Waypoints add intentionality to navigation. Instead of "go north, go north, go east, go east, go north" the player can say "navigate settlement" and receive step-by-step directions. This is a quality-of-life feature that separates a frustrating experience from an enjoyable one, especially as the world grows. A player with 200 explored rooms and no waypoint system has to manually retrace their steps or keep handwritten notes. A player with waypoints has a personal fast-reference system built into the game.

For this architecture, Cartography is one of the cleanest fits of any design. The aspect is almost entirely self-contained: it reads from the Land aspect (coordinates, biome, landmark) and writes only to its own data. No other aspect needs to read Cartography data. No cross-entity writes. No shared mutable state. The only architectural concern is the auto-recording feature -- writing to the Cartography aspect on every room entry adds a write to the most frequent player action in the game. Moving is the thing players do most, and adding an aspect write to every move doubles the write cost of navigation. That said, the write is to the player's own aspect record, so there is no contention between players. This is a system that adds genuine value with minimal architectural risk.

## Critical Analysis

**Map data grows linearly with exploration and the aspect record will get large.** Each visited location entry contains: location_uuid (36 bytes), x/y/z coordinates (3 ints, ~12 bytes), biome string (~15 bytes), landmark_name (~20 bytes average if present), and visited_at timestamp (8 bytes). That is roughly 90-100 bytes per room. A dedicated explorer who visits 1000 rooms accumulates ~100KB of map data in a single aspect record. DynamoDB's 400KB item size limit means the theoretical maximum is roughly 4000 rooms. This is large but survivable for most players. However, if the world has 10,000+ rooms (which the worldgen system can produce), completionist players will eventually hit the limit. The mitigation is to compress the data (store coordinate tuples instead of dicts, drop optional fields) or to shard the map data across multiple aspect records -- but the codebase has no pattern for sharded aspect data.

**Auto-recording on every room entry adds 1 aspect write per move.** The `move` command in Land currently writes 1 entity record (location change). With Cartography auto-recording, each move also reads the Cartography aspect (1 read), adds the new location to `visited_locations`, and calls `_save()` (1 write). This doubles the DynamoDB write cost of the most common player action. On a 1 WCU table, a player who moves every 2 seconds (aggressive exploration) consumes 1.5 WCU just from Cartography writes (0.5 from entity location change + 1 from aspect save -- but the entity write and aspect write go to different tables so they do not compete). The aspect write goes to LOCATION_TABLE, which is shared with all aspect data. If 10 players are exploring simultaneously, that is 5 Cartography writes per second to LOCATION_TABLE, which will throttle at the 1 WCU provisioned capacity.

**Navigate BFS must load Land aspects for path tracing.** The `navigate` command finds the shortest path between the player's current location and a waypoint by running BFS on the player's `visited_locations` graph. But visited_locations only stores that a room exists and its coordinates -- it does not store the room's exits. To determine which rooms connect to which, the BFS must either: (a) load each room's Land aspect to read its exits (1 DynamoDB read per room), or (b) maintain a separate adjacency graph in the Cartography data. Option (a) is correct but expensive: a path through 50 rooms requires 50 Land aspect reads. Option (b) is fast but doubles the Cartography data size (storing exits alongside coordinates) and can become stale if room exits change. The design below uses option (b) -- storing a simplified adjacency list alongside visited locations -- because the read cost of option (a) is prohibitive on a 1 RCU table.

**Map rendering in Lambda has compute cost but no DynamoDB cost.** Converting visited coordinates to an ASCII grid is pure computation: iterate visited_locations, map coordinates to a 2D array, assign biome symbols, render as a string. This runs entirely in Lambda memory with no DynamoDB reads. For a map of 500 rooms, the rendering is a few milliseconds of CPU time. The Lambda execution cost is negligible ($0.0000002 per 100ms at 128MB). Map rendering is the rare command that costs almost nothing.

**share_map creates item entities (2 writes) and using a map scroll creates writes per shared location.** The `share_map` command creates a "map scroll" item entity (1 entity write + 1 Inventory aspect write). When the recipient uses the scroll, each new location from the scroll is added to their Cartography data. If the scroll contains 100 locations the recipient has not visited, that is 1 Cartography aspect write (the entire visited_locations dict is written at once via put_item, not per-location). So the cost is bounded: 2 writes to create the scroll, 1 write to consume it. This is reasonable.

**Low risk: this system is purely additive.** Cartography never modifies other entities' data. It reads Land aspects (coordinates, biome, exits) and writes only to its own aspect record on the player's entity. The worst failure mode is stale map data (a room's biome changed since the player visited), which is cosmetic, not functional. There are no race conditions between players because each player's map is independent. There are no cascading failures because no other system depends on Cartography data (yet). This is the safest aspect to implement from a data integrity standpoint.

**Excellent architectural fit: read-from-Land, write-to-own-aspect only.** The dependency direction is strictly one-way: Cartography depends on Land, nothing depends on Cartography. This means Cartography can be added without modifying any existing aspect code (except a small hook in Land.move or the entity location setter to trigger recording). It can be removed without breaking anything. It can be deployed independently. This is the gold standard for aspect design in this architecture.

**Provides AI agents with navigation data they currently lack.** Currently, AI agents exploring the world have no memory of where they have been. Each move event gives them the new room's exits and description, but they have no map, no sense of spatial relationships, and no ability to return to a previously visited location without manually retracing steps. Cartography gives AI agents `map` (spatial overview), `landmarks` (points of interest), `waypoint` (named locations), and `navigate` (pathfinding). This is the single most impactful quality-of-life improvement for AI agent behavior.

**Discovery XP has no leveling system -- what does exploration level unlock?** The design awards `discovery_xp` for visiting new biomes and landmarks, but there is no exploration level, no unlocks, and no rewards. XP without a corresponding level-up mechanic is a counter that increases but does nothing. Options: tie discovery_xp to a Cartography skill level that unlocks features (larger map view radius, more waypoint slots, map sharing), or simply track it as a stat for leaderboards and achievements. The design below tracks it as a stat with a note to define rewards later.

## Overview

The Cartography aspect tracks a player's exploration of the world as a personal map. As the player moves through rooms, each visited location is automatically recorded with its coordinates, biome, and any landmark present. Players can view their map as an ASCII grid, set waypoints at important locations, get pathfinding directions between locations, and share their map data with other players via map scroll items. The system also awards discovery XP for visiting new biomes and landmarks.

## Design Principles

**The map is personal.** Each player has their own `visited_locations` dict. There is no shared world map. Two players in the same room have different maps because they have explored different areas. This fits the aspect model perfectly -- each entity owns its own Cartography data.

**Auto-record, never lose data.** Every room a player enters is recorded automatically. The player never has to explicitly map a room. This ensures the map is always complete for everywhere the player has been. Data is append-only -- visiting a room adds it, nothing removes it (except `forget_waypoint` which removes a named reference, not the location data).

**Fog of war is the default.** The `map` command only shows visited locations. Unvisited areas are blank. There is no omniscient world map. Discovery is the entire point -- the map rewards exploration.

**Each aspect owns its data.** Cartography stores visited_locations, waypoints, and discovery_xp. Room data (coordinates, biome, exits) is read from Land aspects at visit time and cached in the Cartography record. The entity table stores shared identity fields.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| visited_locations | dict | {} | Map of location_uuid -> location data |
| waypoints | dict | {} | Map of waypoint_name -> location_uuid |
| discovery_xp | int | 0 | XP earned from exploration |
| discovered_biomes | list | [] | List of unique biomes visited |
| discovered_landmarks | list | [] | List of unique landmarks found |

### Visited Location Entry

Each entry in `visited_locations`:

```python
{
    "location-uuid-here": {
        "x": 5,
        "y": 3,
        "z": 0,
        "biome": "forest",
        "landmark": "",               # Empty if no landmark
        "visited_at": 1700000000,      # Unix timestamp of first visit
        "exits": ["north", "south", "east"],  # Cached exit directions
    }
}
```

### Biome Symbols for Map Rendering

```python
BIOME_SYMBOLS = {
    "plains": ".",
    "forest": "T",
    "dense_forest": "T",
    "mountain_peak": "^",
    "misty_highlands": "^",
    "mountain_base": "n",
    "desert": "~",
    "swamp": "%",
    "cave": "o",
    "lake": "~",
    "river": "~",
    "coast": ",",
    "settlement": "#",
    "dungeon": "D",
    "unknown": "?",
}

LANDMARK_SYMBOL = "*"  # Overrides biome symbol if landmark present
PLAYER_SYMBOL = "@"    # Current player position
WAYPOINT_SYMBOL = "!"  # Waypoint marker
```

### Discovery XP Awards

```python
DISCOVERY_XP = {
    "new_room": 1,          # First visit to any room
    "new_biome": 25,        # First time visiting a new biome type
    "new_landmark": 50,     # Discovering a landmark
}
```

## Commands

### `map`

```python
@player_command
def map(self) -> dict:
    """Display explored area as an ASCII grid centered on current position."""
```

**Validation:** None -- always succeeds (even with empty map).

**Behavior:**
```python
@player_command
def map(self) -> dict:
    """Display explored area as an ASCII grid centered on current position."""
    visited = self.data.get("visited_locations", {})
    waypoints = self.data.get("waypoints", {})
    waypoint_locations = set(waypoints.values())

    if not visited:
        return {
            "type": "map",
            "grid": "You haven't explored anywhere yet.",
            "legend": {},
        }

    # Get current position
    current_loc = self.entity.location
    current_entry = visited.get(current_loc, {})
    cx = current_entry.get("x", 0)
    cy = current_entry.get("y", 0)
    cz = current_entry.get("z", 0)

    # Filter to current z-level
    same_level = {
        uuid: data for uuid, data in visited.items()
        if data.get("z", 0) == cz
    }

    if not same_level:
        return {
            "type": "map",
            "grid": "No explored rooms on this level.",
            "legend": {},
        }

    # Compute bounds
    xs = [d["x"] for d in same_level.values()]
    ys = [d["y"] for d in same_level.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # Add padding
    pad = 1
    min_x -= pad
    max_x += pad
    min_y -= pad
    max_y += pad

    # Build grid (y increases northward, so render top-to-bottom = high y first)
    width = max_x - min_x + 1
    height = max_y - min_y + 1
    grid = [[" " for _ in range(width)] for _ in range(height)]

    for uuid, data in same_level.items():
        gx = data["x"] - min_x
        gy = max_y - data["y"]  # Flip y for display

        if uuid == current_loc:
            grid[gy][gx] = PLAYER_SYMBOL
        elif uuid in waypoint_locations:
            grid[gy][gx] = WAYPOINT_SYMBOL
        elif data.get("landmark"):
            grid[gy][gx] = LANDMARK_SYMBOL
        else:
            biome = data.get("biome", "unknown")
            grid[gy][gx] = BIOME_SYMBOLS.get(biome, "?")

    # Render to string
    grid_str = "\n".join("".join(row) for row in grid)

    return {
        "type": "map",
        "grid": grid_str,
        "center": [cx, cy, cz],
        "bounds": {"min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y},
        "rooms_explored": len(visited),
        "legend": {
            "@": "You",
            "!": "Waypoint",
            "*": "Landmark",
            ".": "Plains",
            "T": "Forest",
            "^": "Mountain",
            "~": "Water/Desert",
            "#": "Settlement",
            "o": "Cave",
        },
    }
```

**DynamoDB cost:** 0 reads, 0 writes. All data is already loaded in the aspect record. Pure computation.

**Return format:**
```python
{
    "type": "map",
    "grid": "  T T .  \n T @ . . \n  . # .  \n  . . .  ",
    "center": [5, 3, 0],
    "bounds": {"min_x": 3, "max_x": 7, "min_y": 1, "max_y": 5},
    "rooms_explored": 42,
    "legend": {"@": "You", ".": "Plains", "T": "Forest", "#": "Settlement"}
}
```

### `landmarks`

```python
@player_command
def landmarks(self) -> dict:
    """List all discovered landmarks with their locations."""
```

**Behavior:**
```python
@player_command
def landmarks(self) -> dict:
    """List all discovered landmarks with their locations."""
    visited = self.data.get("visited_locations", {})
    landmark_list = []

    for uuid, data in visited.items():
        if data.get("landmark"):
            landmark_list.append({
                "name": data["landmark"],
                "location_uuid": uuid,
                "coordinates": [data.get("x", 0), data.get("y", 0), data.get("z", 0)],
                "biome": data.get("biome", "unknown"),
            })

    return {
        "type": "landmarks",
        "landmarks": landmark_list,
        "count": len(landmark_list),
        "message": f"You have discovered {len(landmark_list)} landmark(s)."
    }
```

**DynamoDB cost:** 0 reads, 0 writes. Scans in-memory aspect data only.

**Return format:**
```python
{
    "type": "landmarks",
    "landmarks": [
        {
            "name": "The Whispering Stones",
            "location_uuid": "room-uuid",
            "coordinates": [3, 7, 0],
            "biome": "mountain_peak"
        },
        {
            "name": "Thornwall Settlement",
            "location_uuid": "room-uuid-2",
            "coordinates": [5, 3, 0],
            "biome": "settlement"
        }
    ],
    "count": 2,
    "message": "You have discovered 2 landmark(s)."
}
```

### `waypoint <name>`

```python
@player_command
def waypoint(self, name: str) -> dict:
    """Mark the current location as a named waypoint."""
```

**Validation:**
1. Name must not be empty
2. Name must not already exist (or will overwrite with warning)
3. Current location must be in visited_locations

**Behavior:**
```python
@player_command
def waypoint(self, name: str) -> dict:
    """Mark the current location as a named waypoint."""
    if not name:
        return {"type": "error", "message": "Provide a name for the waypoint."}

    name = name.lower().strip()
    current_loc = self.entity.location

    if not current_loc:
        return {"type": "error", "message": "You are nowhere."}

    visited = self.data.get("visited_locations", {})
    if current_loc not in visited:
        # Auto-record current location first
        self._record_location(current_loc)

    waypoints = self.data.get("waypoints", {})

    overwriting = name in waypoints
    waypoints[name] = current_loc
    self.data["waypoints"] = waypoints
    self._save()

    loc_data = visited.get(current_loc, {})
    coords = [loc_data.get("x", 0), loc_data.get("y", 0), loc_data.get("z", 0)]

    msg = f"Waypoint '{name}' set at {coords}."
    if overwriting:
        msg = f"Waypoint '{name}' updated to {coords}."

    return {
        "type": "waypoint_set",
        "name": name,
        "location_uuid": current_loc,
        "coordinates": coords,
        "message": msg,
    }
```

**DynamoDB cost:** 0 reads (data already loaded), 1 write (save aspect).

**Return format:**
```python
{
    "type": "waypoint_set",
    "name": "home",
    "location_uuid": "room-uuid",
    "coordinates": [5, 3, 0],
    "message": "Waypoint 'home' set at [5, 3, 0]."
}
```

### `navigate <waypoint_name>`

```python
@player_command
def navigate(self, waypoint_name: str) -> dict:
    """Get step-by-step directions to a waypoint using explored paths."""
```

**Validation:**
1. Waypoint must exist
2. Current location must be in visited_locations
3. A path must exist through visited locations

**Behavior:**
```python
@player_command
def navigate(self, waypoint_name: str) -> dict:
    """Get step-by-step directions to a waypoint using explored paths."""
    waypoint_name = waypoint_name.lower().strip()
    waypoints = self.data.get("waypoints", {})

    if waypoint_name not in waypoints:
        return {"type": "error", "message": f"Unknown waypoint: '{waypoint_name}'."}

    target_uuid = waypoints[waypoint_name]
    current_loc = self.entity.location

    if current_loc == target_uuid:
        return {"type": "navigate", "message": "You are already at that waypoint.", "steps": []}

    visited = self.data.get("visited_locations", {})

    if current_loc not in visited:
        return {"type": "error", "message": "Your current location is not on your map."}

    if target_uuid not in visited:
        return {"type": "error", "message": "The waypoint location is not on your map."}

    # BFS on visited locations using cached exits
    path = self._bfs_path(current_loc, target_uuid, visited)

    if path is None:
        return {
            "type": "error",
            "message": f"No known path to '{waypoint_name}'. You may need to explore more.",
        }

    # Convert path (list of UUIDs) to step-by-step directions
    steps = self._path_to_directions(path, visited)

    return {
        "type": "navigate",
        "waypoint": waypoint_name,
        "steps": steps,
        "distance": len(steps),
        "message": f"Directions to '{waypoint_name}' ({len(steps)} steps): {' -> '.join(s['direction'] for s in steps)}",
    }

def _bfs_path(self, start_uuid: str, end_uuid: str, visited: dict) -> list:
    """BFS over visited locations using cached adjacency to find shortest path."""
    from collections import deque

    # Build adjacency from cached exits
    # Each visited location has "exits": ["north", "south", ...]
    # We need to map direction -> neighbor UUID
    # We can do this by checking: for each exit direction of room A,
    # compute the expected coordinates, then find if we have a visited room there.

    coord_to_uuid = {}
    for uuid, data in visited.items():
        key = (data.get("x", 0), data.get("y", 0), data.get("z", 0))
        coord_to_uuid[key] = uuid

    direction_offsets = {
        "north": (0, 1, 0),
        "south": (0, -1, 0),
        "east": (1, 0, 0),
        "west": (-1, 0, 0),
        "up": (0, 0, 1),
        "down": (0, 0, -1),
    }

    queue = deque()
    queue.append((start_uuid, [start_uuid]))
    seen = {start_uuid}

    while queue:
        current, path = queue.popleft()
        current_data = visited.get(current, {})
        cx = current_data.get("x", 0)
        cy = current_data.get("y", 0)
        cz = current_data.get("z", 0)

        for exit_dir in current_data.get("exits", []):
            offset = direction_offsets.get(exit_dir)
            if not offset:
                continue
            neighbor_coords = (cx + offset[0], cy + offset[1], cz + offset[2])
            neighbor_uuid = coord_to_uuid.get(neighbor_coords)

            if neighbor_uuid and neighbor_uuid not in seen:
                new_path = path + [neighbor_uuid]
                if neighbor_uuid == end_uuid:
                    return new_path
                seen.add(neighbor_uuid)
                queue.append((neighbor_uuid, new_path))

    return None  # No path found

def _path_to_directions(self, path: list, visited: dict) -> list:
    """Convert a list of location UUIDs to step-by-step direction instructions."""
    steps = []
    direction_offsets = {
        (0, 1, 0): "north",
        (0, -1, 0): "south",
        (1, 0, 0): "east",
        (-1, 0, 0): "west",
        (0, 0, 1): "up",
        (0, 0, -1): "down",
    }

    for i in range(len(path) - 1):
        from_data = visited[path[i]]
        to_data = visited[path[i + 1]]
        dx = to_data.get("x", 0) - from_data.get("x", 0)
        dy = to_data.get("y", 0) - from_data.get("y", 0)
        dz = to_data.get("z", 0) - from_data.get("z", 0)
        direction = direction_offsets.get((dx, dy, dz), "unknown")

        steps.append({
            "step": i + 1,
            "direction": direction,
            "destination_uuid": path[i + 1],
            "biome": to_data.get("biome", "unknown"),
            "landmark": to_data.get("landmark", ""),
        })

    return steps
```

**DynamoDB cost:** 0 reads, 0 writes. BFS runs entirely on in-memory cached data. This is why we store exits in visited_locations -- to avoid loading Land aspects during pathfinding.

**Return format:**
```python
{
    "type": "navigate",
    "waypoint": "settlement",
    "steps": [
        {"step": 1, "direction": "north", "destination_uuid": "uuid-1", "biome": "forest", "landmark": ""},
        {"step": 2, "direction": "north", "destination_uuid": "uuid-2", "biome": "plains", "landmark": ""},
        {"step": 3, "direction": "east", "destination_uuid": "uuid-3", "biome": "settlement", "landmark": "Thornwall"}
    ],
    "distance": 3,
    "message": "Directions to 'settlement' (3 steps): north -> north -> east"
}
```

### `forget_waypoint <name>`

```python
@player_command
def forget_waypoint(self, name: str) -> dict:
    """Remove a named waypoint."""
```

**Behavior:**
```python
@player_command
def forget_waypoint(self, name: str) -> dict:
    """Remove a named waypoint."""
    name = name.lower().strip()
    waypoints = self.data.get("waypoints", {})

    if name not in waypoints:
        return {"type": "error", "message": f"No waypoint named '{name}'."}

    del waypoints[name]
    self.data["waypoints"] = waypoints
    self._save()

    return {
        "type": "waypoint_removed",
        "name": name,
        "message": f"Waypoint '{name}' forgotten.",
    }
```

**DynamoDB cost:** 0 reads, 1 write.

**Return format:**
```python
{
    "type": "waypoint_removed",
    "name": "old_camp",
    "message": "Waypoint 'old_camp' forgotten."
}
```

### `share_map <player_uuid>`

```python
@player_command
def share_map(self, player_uuid: str) -> dict:
    """Create a map scroll item containing your exploration data for another player."""
```

**Validation:**
1. Target player must exist and be at the same location
2. Player must have visited at least 1 location

**Behavior:**
```python
@player_command
def share_map(self, player_uuid: str) -> dict:
    """Create a map scroll item containing your exploration data for another player."""
    visited = self.data.get("visited_locations", {})
    if not visited:
        return {"type": "error", "message": "You have no map data to share."}

    try:
        target_entity = Entity(uuid=player_uuid)
    except KeyError:
        return {"type": "error", "message": "That player doesn't exist."}

    if target_entity.location != self.entity.location:
        return {"type": "error", "message": "That player isn't here."}

    # Create a map scroll item entity
    inv = self.entity.aspect("Inventory")
    scroll_data = {
        "source_player": self.entity.name,
        "location_count": len(visited),
        "map_data": visited,  # Full map data serialized on the item
    }

    result = inv.create_item(
        name=f"map scroll from {self.entity.name}",
        description=f"A scroll containing map data for {len(visited)} locations, drawn by {self.entity.name}.",
        tags=["map_scroll", "consumable"],
        weight=0,
        scroll_data=scroll_data,
    )

    # Place the scroll at the current location for the recipient to take
    scroll_uuid = result.get("item_uuid", "")
    if scroll_uuid:
        scroll_entity = Entity(uuid=scroll_uuid)
        scroll_entity.location = self.entity.location

    return {
        "type": "share_map_confirm",
        "scroll_uuid": scroll_uuid,
        "locations_shared": len(visited),
        "recipient": target_entity.name,
        "message": f"You create a map scroll with {len(visited)} locations and place it on the ground.",
    }
```

**DynamoDB cost:** 1 read (target entity) + 2 writes (create scroll entity + Inventory aspect) + 1 write (set scroll location) = 1 read, 3 writes.

**Return format:**
```python
{
    "type": "share_map_confirm",
    "scroll_uuid": "scroll-uuid",
    "locations_shared": 42,
    "recipient": "OtherPlayer",
    "message": "You create a map scroll with 42 locations and place it on the ground."
}
```

### Using a Map Scroll (internal callable)

```python
@callable
def use_map_scroll(self, scroll_uuid: str) -> dict:
    """Consume a map scroll to add its locations to your map."""
    try:
        scroll_entity = Entity(uuid=scroll_uuid)
    except KeyError:
        return {"type": "error", "message": "That scroll doesn't exist."}

    if scroll_entity.location != self.entity.uuid:
        return {"type": "error", "message": "You don't have that scroll."}

    scroll_inv = scroll_entity.aspect("Inventory")
    scroll_data = scroll_inv.data.get("scroll_data", {})
    map_data = scroll_data.get("map_data", {})

    if not map_data:
        return {"type": "error", "message": "The scroll is blank."}

    # Merge scroll locations into player's visited_locations
    visited = self.data.get("visited_locations", {})
    new_count = 0

    for loc_uuid, loc_data in map_data.items():
        if loc_uuid not in visited:
            visited[loc_uuid] = loc_data
            new_count += 1
            # Award discovery XP for new biomes/landmarks
            self._check_discovery_rewards(loc_data)

    self.data["visited_locations"] = visited
    self._save()

    # Destroy the scroll
    scroll_entity.destroy()

    source = scroll_data.get("source_player", "unknown")
    return {
        "type": "map_scroll_used",
        "new_locations": new_count,
        "source": source,
        "message": f"You study the scroll and add {new_count} new locations to your map. The scroll crumbles to dust.",
    }
```

## Cross-Aspect Interactions

### Cartography + Land (auto-recording on movement)

The core integration point. When a player moves to a new room, the Cartography aspect records the location. This requires a hook in the movement flow:

```python
# Option 1: Hook in Land.move() after successful movement
# In Land.move(), after self.entity.location = dest_uuid:
def move(self, direction: str) -> dict:
    # ... existing movement code ...
    if self.entity:
        self.entity.location = dest_uuid

    # Trigger Cartography recording
    try:
        carto = self.entity.aspect("Cartography")
        carto._record_location(dest_uuid)
    except (ValueError, KeyError):
        pass  # No Cartography aspect, skip

    # ... rest of move logic ...

# Option 2: Callable triggered via SNS after movement
# Land.move() calls:
# Call(tid, self.entity.uuid, self.entity.uuid, "Cartography", "record_location",
#      location_uuid=dest_uuid).now()
# This is async but avoids modifying Land.move() directly.
```

The recording function:

```python
def _record_location(self, location_uuid: str):
    """Record a location in the player's visited map."""
    visited = self.data.get("visited_locations", {})

    if location_uuid in visited:
        return  # Already visited, skip

    # Load the room's Land aspect for coordinates and metadata
    try:
        room = Land(uuid=location_uuid)
    except KeyError:
        return

    import time
    entry = {
        "x": room.coordinates[0],
        "y": room.coordinates[1],
        "z": room.coordinates[2],
        "biome": room.data.get("biome", "unknown"),
        "landmark": room.data.get("landmark", ""),
        "visited_at": int(time.time()),
        "exits": list(room.exits.keys()),  # Cache exits for pathfinding
    }

    visited[location_uuid] = entry
    self.data["visited_locations"] = visited

    # Check for discovery rewards
    self._check_discovery_rewards(entry)

    self._save()

def _check_discovery_rewards(self, loc_data: dict):
    """Award XP for new biome or landmark discovery."""
    biome = loc_data.get("biome", "")
    landmark = loc_data.get("landmark", "")

    xp_gained = DISCOVERY_XP["new_room"]

    discovered_biomes = self.data.get("discovered_biomes", [])
    if biome and biome not in discovered_biomes:
        discovered_biomes.append(biome)
        self.data["discovered_biomes"] = discovered_biomes
        xp_gained += DISCOVERY_XP["new_biome"]

    discovered_landmarks = self.data.get("discovered_landmarks", [])
    if landmark and landmark not in discovered_landmarks:
        discovered_landmarks.append(landmark)
        self.data["discovered_landmarks"] = discovered_landmarks
        xp_gained += DISCOVERY_XP["new_landmark"]

    self.data["discovery_xp"] = self.data.get("discovery_xp", 0) + xp_gained

    # Notify player of discoveries
    if xp_gained > DISCOVERY_XP["new_room"]:
        self.entity.push_event({
            "type": "discovery",
            "xp_gained": xp_gained,
            "biome": biome,
            "landmark": landmark,
            "total_xp": self.data["discovery_xp"],
            "message": f"New discovery! +{xp_gained} exploration XP.",
        })
```

### Cartography + Inventory (map scrolls)

Map scrolls are Inventory items. The Cartography aspect creates them via `Inventory.create_item()` and destroys them via `Entity.destroy()`:

```python
# Creating a scroll (in share_map):
inv = self.entity.aspect("Inventory")
result = inv.create_item(
    name=f"map scroll from {self.entity.name}",
    description=f"A scroll containing map data for {len(visited)} locations.",
    tags=["map_scroll", "consumable"],
    weight=0,
    scroll_data={"source_player": self.entity.name, "map_data": visited},
)

# Using a scroll (in use_map_scroll):
scroll_entity.destroy()  # Consumes the scroll after reading
```

### Cartography + NPC (NPC cartographers)

NPCs with "cartographer" behavior could sell pre-made map scrolls covering specific regions:

```python
# Future integration -- NPC dialogue action:
# "buy_regional_map" action creates a map scroll with locations from a specific biome
# This uses the existing dialogue action system (09-dialogue-trees.md)

# Example dialogue tree entry:
{
    "label": "I'd like a map of the mountain region.",
    "next": "_end",
    "action": {
        "type": "give_item",
        "name": "mountain region map",
        "description": "A detailed map of the mountain passes.",
        "properties": {
            "tags": ["map_scroll", "consumable"],
            "scroll_data": {"map_data": {}, "region": "mountain"},  # Populated at runtime
        }
    }
}
```

### Cartography + Faction (territory awareness)

Cartography data can be cross-referenced with faction territories to warn players about hostile regions:

```python
# Future enhancement -- in the map command or a separate "territories" command:
# For each visited location, check the biome against faction home_biomes
# Display faction territory boundaries on the map
# This requires reading the Faction registry (no DynamoDB reads, it's a module-level dict)

def _annotate_territories(self, visited: dict) -> dict:
    """Add faction territory info to visited locations (read-only, from registry)."""
    from .faction import FACTIONS
    biome_to_faction = {}
    for fid, fdef in FACTIONS.items():
        for biome in fdef.get("home_biomes", []):
            biome_to_faction[biome] = fid

    annotations = {}
    for uuid, data in visited.items():
        biome = data.get("biome", "")
        if biome in biome_to_faction:
            annotations[uuid] = biome_to_faction[biome]
    return annotations
```

### Cartography + Quest (exploration quests)

Quest objectives can reference Cartography data:

```python
# Quest objective type: "visit_location"
{
    "id": "find_ancient_ruins",
    "type": "visit_location",
    "description": "Discover the ancient ruins in the mountains.",
    "target_landmark": "Ancient Ruins",
}

# In Quest objective checking:
# Check if player's Cartography.discovered_landmarks contains "Ancient Ruins"
try:
    carto = player.aspect("Cartography")
    if "Ancient Ruins" in carto.data.get("discovered_landmarks", []):
        objective_complete = True
except (ValueError, KeyError):
    pass
```

## Event Flow

### Auto-Recording on Movement

```
Player sends: {"command": "move", "data": {"direction": "north"}}
  -> Entity.receive_command(command="move", direction="north")
    -> Land.move(direction="north")
      -> Validate exit exists
      -> Set entity.location = dest_uuid (1 entity write, broadcasts depart/arrive)
      -> Load Cartography aspect (1 read from LOCATION_TABLE)
      -> Cartography._record_location(dest_uuid)
        -> Check if already visited (in-memory check)
        -> If new: Load dest Land aspect (1 read from LAND_TABLE)
        -> Extract coordinates, biome, landmark, exits
        -> Add to visited_locations dict
        -> Check discovery rewards (biome/landmark XP)
        -> Save Cartography aspect (1 write to LOCATION_TABLE)
        -> If discovery: push_event(discovery notification)
      -> Generate room if needed (existing worldgen flow)
      -> Return move result
```

### Map Rendering

```
Player sends: {"command": "map"}
  -> Cartography.map()
    -> Read visited_locations from aspect data (already loaded, 0 reads)
    -> Filter to current z-level
    -> Compute coordinate bounds
    -> Build 2D grid with biome symbols
    -> Mark player position, waypoints, landmarks
    -> Render grid to string
    -> Return map result (0 DynamoDB operations)
```

### Navigate to Waypoint

```
Player sends: {"command": "navigate", "data": {"waypoint_name": "settlement"}}
  -> Cartography.navigate(waypoint_name="settlement")
    -> Look up waypoint UUID (in-memory)
    -> BFS on visited_locations adjacency (in-memory, 0 reads)
      -> Build coord->uuid lookup from visited_locations
      -> For each room's cached exits, compute neighbor coordinates
      -> Find neighbor in coord->uuid lookup
      -> Standard BFS until target found
    -> Convert path UUIDs to direction instructions
    -> Return step-by-step directions (0 DynamoDB operations)
```

### Share Map

```
Player A sends: {"command": "share_map", "data": {"player_uuid": "player-b-uuid"}}
  -> Cartography.share_map(player_uuid="player-b-uuid")
    -> Validate Player B exists and is at same location (1 read)
    -> Create map scroll item entity (2 writes: entity + Inventory aspect)
    -> Set scroll location to current room (1 write)
    -> Return confirmation

Player B sends: {"command": "take", "data": {"item_uuid": "scroll-uuid"}}
  -> Inventory.take(item_uuid="scroll-uuid")
    -> Standard take flow (moves scroll to B's inventory)

Player B sends: {"command": "use_map_scroll", "data": {"scroll_uuid": "scroll-uuid"}}
  -> Cartography.use_map_scroll(scroll_uuid="scroll-uuid")
    -> Load scroll entity + Inventory aspect (2 reads)
    -> Read map_data from scroll properties
    -> Merge new locations into B's visited_locations
    -> Award discovery XP for new biomes/landmarks
    -> Save Cartography aspect (1 write)
    -> Destroy scroll (2 deletes: entity + aspect)
    -> Return result
```

## NPC Integration

### NPC exploration tracking

NPCs do not need Cartography aspects. They navigate by following exits (wander behavior) or patrol routes (predefined UUID lists). NPCs do not need maps because they do not make navigation decisions based on world knowledge -- their behavior is local (react to current room) or scripted (follow patrol route).

### Cartographer NPCs

A specialized NPC type could sell regional maps or offer to mark the player's map with locations:

```python
# Cartographer NPC -- sells map scrolls for specific regions
# Created during world generation at settlements
cartographer_entity = Entity()
cartographer_entity.data["name"] = "Theron the Cartographer"
cartographer_entity.data["location"] = settlement_room_uuid
cartographer_entity.data["aspects"] = ["NPC", "Inventory"]
cartographer_entity.data["primary_aspect"] = "NPC"
cartographer_entity._save()

npc = cartographer_entity.aspect("NPC")
npc.data["behavior"] = "merchant"
npc.data["is_npc"] = True
npc.data["trade_inventory"] = ["forest region map", "mountain region map"]
npc.data["buy_tags"] = []  # Doesn't buy anything
npc._save()
```

### NPC pathfinding

Currently NPCs do not pathfind. Wanderers move randomly, patrols follow preset routes. If NPC pathfinding is ever needed (e.g., an NPC guide that leads the player somewhere), the BFS algorithm from Cartography's `navigate` command could be extracted to a utility function. However, NPCs would need their own map data or access to a global room graph, which does not exist. This is a future consideration, not an initial implementation requirement.

## AI Agent Considerations

### Spatial awareness

Cartography provides the single most impactful improvement for AI agent behavior. Currently, AI agents receive room descriptions and exit lists on each move, but have no persistent spatial model. With Cartography:

1. **`map` command** gives the agent a spatial overview of explored territory. The ASCII grid and coordinate data allow the agent to reason about geography ("the settlement is northeast of me, I should go east then north").

2. **`landmarks` command** provides a list of notable locations the agent has discovered. Combined with quest objectives ("find the ancient ruins"), the agent can check whether it has already discovered the target.

3. **`waypoint` command** lets the agent mark locations for future reference. An agent completing a quest can set waypoints for the quest giver, resource locations, and safe rest areas.

4. **`navigate` command** is the critical capability. Instead of random exploration or manually remembered paths, the agent can request directions to any waypoint. The step-by-step directions ("north, north, east") are directly executable as `move` commands.

### Exploration strategy

An AI agent with Cartography can implement systematic exploration:

```
1. On each move, check the map response for unexplored edges
2. Prefer moving toward unexplored areas (exits not yet in visited_locations)
3. Set waypoints at useful locations (merchants, quest NPCs, resource areas)
4. When a quest requires visiting a specific landmark, check landmarks first
5. If landmark not yet discovered, explore systematically in the target biome
6. Use navigate to return to waypoints efficiently
```

### Map data as context

The `map` command's ASCII grid can be included in the AI agent's context window to provide spatial reasoning. A 50x50 character grid conveys more spatial information than a list of room descriptions. The agent can visually identify clusters (settlements), paths (corridors between biomes), and unexplored frontiers (blank areas adjacent to explored territory).

### Multi-agent map sharing

If multiple AI agents (or AI agents and human players) explore different regions and use `share_map`, they can collectively build comprehensive world maps faster than any single agent. An AI agent at a settlement could seek out other players, share maps, and gain knowledge of distant regions without traveling there.

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/cartography.py` | Cartography aspect class with map rendering and pathfinding |
| `backend/aspects/tests/test_cartography.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/serverless.yml` | Add `cartography` Lambda with SNS filter for `Cartography` aspect |
| `backend/aspects/land.py` | Add Cartography recording hook in `move()` after location change |

### Implementation order

1. Create `cartography.py` with Cartography class and data model
2. Implement `_record_location()` with biome/landmark discovery tracking
3. Implement `map` command with ASCII grid rendering
4. Implement `landmarks` command (simple filter on visited_locations)
5. Implement `waypoint` and `forget_waypoint` commands
6. Implement `navigate` command with BFS pathfinding on cached adjacency
7. Implement `share_map` and `use_map_scroll` for map sharing
8. Add recording hook in `Land.move()` (one-line try/except addition)
9. Add Lambda + SNS filter to serverless.yml
10. Write tests (recording, map rendering, BFS pathfinding, waypoints, map scroll creation/consumption, discovery XP)

## Open Questions

1. **Should the map persist across death?** If a player dies and respawns at origin, do they keep their map data? Losing the map on death is punishing and discourages exploration. Keeping it is unrealistic but better for gameplay. Recommendation: keep map data on death -- it is knowledge, not a physical item.

2. **Map data size management.** At what point should map data be compressed or pruned? Options: (a) store only coordinates and biome as a compact tuple instead of a full dict per room, reducing per-entry size by ~40%; (b) archive regions the player has not visited in N hours to a separate DynamoDB item; (c) accept the 400KB limit and cap exploration at ~4000 rooms. Start with option (a) if data size becomes a concern.

3. **Should navigation work across z-levels?** The current BFS filters to the same z-level for map rendering but pathfinding should work across levels (stairs, caves). The BFS implementation above handles z-level changes through the `up`/`down` exits -- no z-level filtering is applied during navigation. Confirm this is the desired behavior.

4. **Auto-waypoint for landmarks?** Should discovering a landmark automatically create a waypoint with the landmark name? This is convenient but clutters the waypoint list. Alternative: landmarks are a separate namespace from waypoints, and `navigate` accepts either. This is the cleaner design but requires `navigate` to check both dicts.

5. **Should the map show other players' positions?** The current design is strictly personal -- you see your own position but not other players. Showing party members on the map would require reading their entity locations (N reads per map render) and adds a social dimension. Defer until a party system exists.

6. **Discovery XP rewards.** The design tracks discovery_xp but defines no rewards. Options: (a) exploration levels that unlock more waypoint slots and larger map view radius; (b) XP feeds into a general character level shared with combat; (c) purely cosmetic (explorer titles, map decorations). Decide when the leveling system is more defined.

7. **Map scroll data size.** A map scroll for a player with 1000 explored rooms contains ~100KB of data stored on the scroll item's Inventory aspect. This is within the 400KB DynamoDB item limit but is a large item property. If map scrolls become common, consider storing only location UUIDs on the scroll (not full data) and having the recipient look up room data from Land aspects at use time -- at the cost of O(N) reads on scroll consumption.
