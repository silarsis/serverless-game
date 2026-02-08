# Procedural Dungeon Instances

## Overview

Procedural dungeons are multi-room dungeon crawls triggered by entering cave or ruin landmarks in the world. The system generates a connected cluster of rooms with increasing difficulty, featuring locked doors, traps, enemies, treasure, and a boss room. Dungeon state is instanced per-player -- each player gets their own generated dungeon that resets after completion or abandonment. The system leverages the existing worldgen infrastructure (DungeonGenerator) and entity/aspect model to create dungeon rooms as regular entities.

## Design Principles

**Dungeons are just rooms.** Dungeon rooms are entities with Land aspects, connected by exits like any other location. Players use the same `move` command to navigate. The only difference is that dungeon rooms are created dynamically and cleaned up after use.

**Instance per player.** Each player gets their own dungeon instance. This prevents griefing (another player killing your boss), enables difficulty scaling, and simplifies state management. The instance is identified by a combination of player UUID + dungeon template ID.

**Procedural but seeded.** Given the same seed, the same dungeon layout is generated. The seed combines the player UUID, dungeon template, and an attempt counter. This allows reproducibility for debugging while ensuring variety between players and attempts.

**Cleanup after completion.** Once a dungeon is completed (boss killed, treasure claimed) or abandoned (player exits without completing), the dungeon entities are destroyed after a cooldown. This prevents entity table bloat from accumulated dungeon instances.

**Each aspect owns its data.** The Dungeon aspect stores instance state (room graph, enemy positions, door states, completion flag). Individual dungeon rooms are entities with Land aspects. Dungeon enemies are entities with NPC/Combat aspects. All follow the standard model.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

### On the player entity:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| active_dungeon | str | "" | UUID of active dungeon instance entity |
| dungeons_completed | list | [] | List of completed dungeon template IDs |
| dungeon_cooldowns | dict | {} | Map of template_id -> timestamp when re-entry is allowed |

### Dungeon Instance Entity

A dungeon instance is itself an entity with a Dungeon aspect:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Instance entity UUID (primary key) |
| template_id | str | "" | Which dungeon template was used |
| player_uuid | str | "" | UUID of the player this instance belongs to |
| seed | int | 0 | Generation seed |
| rooms | list | [] | List of room entity UUIDs in order |
| room_graph | dict | {} | Map of room_uuid -> {exits, contents, room_type} |
| entrance_uuid | str | "" | UUID of the first room |
| boss_room_uuid | str | "" | UUID of the boss room |
| is_complete | bool | False | Whether the dungeon has been completed |
| difficulty | int | 1 | Scaling factor for enemy stats |
| created_at | int | 0 | Timestamp for cleanup scheduling |

### Dungeon Template Registry

```python
DUNGEON_TEMPLATES = {
    "goblin_cave": {
        "name": "Goblin Cave",
        "description": "A network of caves infested with goblins.",
        "entry_biomes": ["cave"],
        "room_count": {"min": 5, "max": 8},
        "enemy_types": [
            {"name": "goblin", "behavior": "hostile", "hp": 15, "attack": 4, "defense": 1},
            {"name": "goblin archer", "behavior": "hostile", "hp": 10, "attack": 6, "defense": 0},
        ],
        "boss": {
            "name": "Goblin Chief",
            "behavior": "hostile",
            "hp": 50,
            "attack": 10,
            "defense": 5,
            "loot": [
                {"name": "goblin chief's crown", "tags": ["head", "armor"], "defense_bonus": 2}
            ],
        },
        "trap_types": ["pit", "dart"],
        "loot_table": [
            {"name": "gold coins", "tags": ["currency"], "weight": 1},
            {"name": "crude dagger", "tags": ["weapon", "held_main"], "attack_bonus": 1},
        ],
        "difficulty_range": [1, 5],
        "cooldown_seconds": 3600,  # 1 hour before re-entry
    },
    "ancient_ruins": {
        "name": "Ancient Ruins",
        "description": "Crumbling stone halls echoing with forgotten magic.",
        "entry_biomes": ["mountain_peak", "misty_highlands"],
        "room_count": {"min": 8, "max": 12},
        "enemy_types": [
            {"name": "stone golem", "behavior": "hostile", "hp": 30, "attack": 8, "defense": 8},
            {"name": "shadow wisp", "behavior": "hostile", "hp": 12, "attack": 10, "defense": 0},
        ],
        "boss": {
            "name": "Ancient Guardian",
            "behavior": "hostile",
            "hp": 80,
            "attack": 15,
            "defense": 10,
            "loot": [
                {"name": "guardian's shield", "tags": ["held_off", "armor"], "defense_bonus": 5},
                {"name": "ancient spell scroll", "tags": ["spell_scroll"], "teaches_spell": "lightning_bolt"},
            ],
        },
        "trap_types": ["magic_rune", "collapsing_floor"],
        "loot_table": [
            {"name": "ancient coin", "tags": ["currency"], "weight": 1},
            {"name": "enchanted ring", "tags": ["accessory"], "magic_bonus": 2},
        ],
        "difficulty_range": [3, 8],
        "cooldown_seconds": 7200,  # 2 hours
    },
}
```

### Room Types

| Type | Description | Contents |
|------|-------------|----------|
| `entrance` | Entry point with exit back to overworld | No enemies, safe |
| `corridor` | Connecting passage | 0-1 enemies, possible trap |
| `chamber` | Larger room | 1-3 enemies, possible loot |
| `trap_room` | Room with a hazard | Trap entity, 0-1 enemies |
| `treasure_room` | Contains a treasure chest | 0-1 enemies, guaranteed loot |
| `locked_room` | Requires key to enter | Key drops from enemies |
| `boss_room` | Final room with boss enemy | Boss entity, boss loot |

## Commands

### Dungeon Entry (automatic via Land.move)

When a player moves to a location with an entry biome matching a dungeon template, they receive a prompt:

```python
# In Land.move() or look(), check for dungeon entries:
def _check_dungeon_entry(self, location_uuid: str, biome: str) -> dict:
    for template_id, template in DUNGEON_TEMPLATES.items():
        if biome in template["entry_biomes"]:
            return {
                "type": "dungeon_available",
                "template_id": template_id,
                "name": template["name"],
                "description": template["description"],
                "message": f"You see the entrance to {template['name']}. Enter? Use 'enter_dungeon {template_id}'."
            }
    return None
```

### `enter_dungeon <template_id>`

```python
@player_command
def enter_dungeon(self, template_id: str) -> dict:
    """Enter a procedural dungeon instance."""
```

**Validation:**
1. Template must exist
2. Player's current biome must match template's entry_biomes
3. Player must not already be in a dungeon (active_dungeon must be empty)
4. Cooldown must have expired for this template

**Behavior:**
1. Generate dungeon instance from template + seed
2. Create all room entities with Land aspects
3. Create all enemy entities with NPC + Combat aspects
4. Create trap and loot entities
5. Wire exits between rooms
6. Move player to entrance room
7. Set player's `active_dungeon` to instance UUID

**Return format:**
```python
{
    "type": "dungeon_enter",
    "dungeon_name": "Goblin Cave",
    "room_count": 6,
    "difficulty": 2,
    "message": "You descend into the Goblin Cave. The air is damp and the walls glisten with moisture."
}
```

### `leave_dungeon`

```python
@player_command
def leave_dungeon(self) -> dict:
    """Exit the current dungeon (teleports back to entrance overworld location)."""
```

**Behavior:**
1. Move player back to the overworld location where they entered
2. Schedule dungeon cleanup after 5 minutes (in case player re-enters)
3. Clear player's `active_dungeon`
4. Dungeon is considered abandoned (not completed)

### `dungeon_status`

```python
@player_command
def dungeon_status(self) -> dict:
    """Show progress in the current dungeon."""
```

**Return format:**
```python
{
    "type": "dungeon_status",
    "dungeon_name": "Goblin Cave",
    "rooms_explored": 4,
    "rooms_total": 6,
    "enemies_defeated": 5,
    "boss_defeated": False,
    "keys_found": 1,
    "message": "4 of 6 rooms explored. The boss lurks somewhere deeper."
}
```

## Dungeon Generation Algorithm

```python
def _generate_dungeon(self, template: dict, seed: int, difficulty: int) -> dict:
    """Generate a dungeon layout from a template and seed."""
    rng = random.Random(seed)
    room_count = rng.randint(template["room_count"]["min"], template["room_count"]["max"])

    # Generate room layout as a linear chain with branches
    rooms = []
    room_types = self._assign_room_types(room_count, rng)

    for i, room_type in enumerate(room_types):
        room = Entity()
        room.data["aspects"] = ["Land"]
        room.data["primary_aspect"] = "Land"
        room.data["name"] = self._room_name(room_type, template, rng)
        room._save()

        room_land = room.aspect("Land")
        room_land.data["biome"] = "dungeon"
        room_land.data["description"] = self._room_description(room_type, template, rng)
        room_land.data["dungeon_room_type"] = room_type
        room_land._save()

        rooms.append({
            "uuid": room.uuid,
            "type": room_type,
            "enemies": [],
            "loot": [],
            "trap": None,
        })

    # Wire exits (linear chain with occasional branches)
    self._wire_exits(rooms, rng)

    # Place enemies
    self._place_enemies(rooms, template, difficulty, rng)

    # Place traps
    self._place_traps(rooms, template, rng)

    # Place loot
    self._place_loot(rooms, template, rng)

    # Place boss in boss room
    self._place_boss(rooms, template, difficulty, rng)

    # Place keys for locked doors
    self._place_keys(rooms, rng)

    return rooms
```

### Room Type Assignment

```python
def _assign_room_types(self, count: int, rng) -> list:
    types = ["entrance"]  # Always start with entrance

    # Middle rooms are mix of corridors, chambers, trap rooms, treasure rooms
    middle_pool = ["corridor", "corridor", "chamber", "chamber", "chamber", "trap_room", "treasure_room"]
    for i in range(count - 2):
        types.append(rng.choice(middle_pool))

    # Insert one locked room if enough rooms
    if count >= 6:
        insert_pos = rng.randint(3, count - 2)
        types.insert(insert_pos, "locked_room")

    types.append("boss_room")  # Always end with boss room
    return types[:count]  # Trim to exact count
```

### Exit Wiring

```python
def _wire_exits(self, rooms: list, rng):
    """Create exits between rooms. Linear chain with optional branches."""
    for i in range(len(rooms) - 1):
        # Forward connection
        room_a = Land(uuid=rooms[i]["uuid"])
        room_b = Land(uuid=rooms[i+1]["uuid"])

        a_exits = room_a.data.get("exits", {})
        b_exits = room_b.data.get("exits", {})

        if rooms[i+1]["type"] == "locked_room":
            a_exits["locked door"] = rooms[i+1]["uuid"]  # Requires key
        else:
            a_exits["deeper"] = rooms[i+1]["uuid"]

        b_exits["back"] = rooms[i]["uuid"]

        room_a.data["exits"] = a_exits
        room_b.data["exits"] = b_exits
        room_a._save()
        room_b._save()

    # Entrance has exit to overworld
    entrance_land = Land(uuid=rooms[0]["uuid"])
    entrance_exits = entrance_land.data.get("exits", {})
    entrance_exits["exit"] = "OVERWORLD_ENTRY"  # Replaced with actual location on entry
    entrance_land.data["exits"] = entrance_exits
    entrance_land._save()
```

## Cross-Aspect Interactions

### Dungeon + Land (room navigation)

Dungeon rooms are standard Land entities. Players navigate with `move deeper`, `move back`, `move exit`. Locked doors check if the player has a key item.

```python
# In Land.move(), check for locked doors:
if exit_label == "locked door":
    # Check player inventory for key
    has_key = False
    for item_uuid in self.entity.contents:
        try:
            item = Entity(uuid=item_uuid)
            item_inv = item.aspect("Inventory")
            if "dungeon_key" in item_inv.data.get("tags", []):
                has_key = True
                item.destroy()  # Consume key
                break
        except (KeyError, ValueError):
            continue
    if not has_key:
        return {"type": "error", "message": "The door is locked. You need a key."}
```

### Dungeon + Combat (dungeon enemies)

Dungeon enemies are entities with NPC and Combat aspects:

```python
def _place_enemies(self, rooms, template, difficulty, rng):
    for room in rooms:
        if room["type"] in ("corridor", "chamber", "trap_room"):
            enemy_count = rng.randint(0, 2) if room["type"] == "corridor" else rng.randint(1, 3)
            for _ in range(enemy_count):
                enemy_def = rng.choice(template["enemy_types"])
                enemy = Entity()
                enemy.data["aspects"] = ["NPC", "Combat"]
                enemy.data["primary_aspect"] = "NPC"
                enemy.data["location"] = room["uuid"]
                enemy.data["name"] = enemy_def["name"]
                enemy._save()

                # Set combat stats scaled by difficulty
                combat = enemy.aspect("Combat")
                combat.data["hp"] = int(enemy_def["hp"] * (1 + difficulty * 0.2))
                combat.data["max_hp"] = combat.data["hp"]
                combat.data["attack"] = int(enemy_def["attack"] * (1 + difficulty * 0.15))
                combat.data["defense"] = int(enemy_def["defense"] * (1 + difficulty * 0.1))
                combat._save()

                npc = enemy.aspect("NPC")
                npc.data["behavior"] = "hostile"
                npc.data["is_npc"] = True
                npc._save()

                room["enemies"].append(enemy.uuid)
```

### Dungeon + Inventory (loot and keys)

Treasure rooms and enemy drops create items:

```python
def _place_loot(self, rooms, template, rng):
    for room in rooms:
        if room["type"] == "treasure_room":
            loot_def = rng.choice(template["loot_table"])
            # Create loot item at this room's location
            item = Entity()
            item.data["aspects"] = ["Inventory"]
            item.data["primary_aspect"] = "Inventory"
            item.data["name"] = loot_def["name"]
            item.data["location"] = room["uuid"]
            item._save()

            item_inv = item.aspect("Inventory")
            item_inv.data["is_item"] = True
            item_inv.data["tags"] = loot_def.get("tags", [])
            item_inv.data.update({k: v for k, v in loot_def.items() if k not in ("name", "tags")})
            item_inv._save()
```

### Dungeon + Quest (dungeon quests)

Quest objectives can target dungeon completion:

```python
{
    "id": "complete_goblin_cave",
    "type": "complete_dungeon",
    "description": "Clear the Goblin Cave.",
    "target_template": "goblin_cave"
}
```

### Dungeon + Magic (dungeon-specific effects)

Dungeon biome "dungeon" has its own spell affinity modifiers:
- Shadow spells: 1.5x (darkness)
- Light spells: 0.7x (underground)
- Earth spells: 1.3x (stone walls)

## Event Flow

### Dungeon Entry

```
Player sends: {"command": "enter_dungeon", "data": {"template_id": "goblin_cave"}}
  -> Dungeon.enter_dungeon(template_id="goblin_cave")
    -> Validate entry conditions
    -> Generate seed from player_uuid + template + attempt_count
    -> Call _generate_dungeon() to create rooms, enemies, loot
    -> Create dungeon instance entity
    -> Move player to entrance room
    -> Set player.active_dungeon
    -> push_event(dungeon_enter)
    -> Schedule cleanup timer (4 hours max instance lifetime)
```

### Dungeon Completion

```
Player kills boss in boss_room
  -> Combat._on_death(boss) triggers
  -> Boss drops loot
  -> Dungeon._on_boss_killed()
    -> Mark dungeon as complete
    -> Add template_id to player.dungeons_completed
    -> Set cooldown timestamp
    -> push_event(dungeon_complete with summary)
    -> Show exit portal (add "portal" exit in boss room leading to overworld)
```

### Dungeon Cleanup

```
Scheduled cleanup fires (after completion + 5 min, or abandonment + 5 min, or 4 hour timeout)
  -> Dungeon._cleanup_instance()
    -> For each room in rooms:
      -> Destroy all entities at that location (enemies, loot)
      -> Destroy room entity
    -> Destroy dungeon instance entity
    -> Clear player.active_dungeon if still set
```

## NPC Integration

### Dungeon enemies are NPCs

All dungeon enemies are standard NPC entities with hostile behavior. They attack players on sight using the existing NPC tick system. This means:
- Enemies patrol within their room
- Enemies greet (attack) players who enter
- Enemy deaths follow standard combat rules

### Boss NPCs

Bosses are enhanced NPCs with special properties:
- Higher stats scaled by difficulty
- Guaranteed loot drops (defined in template)
- Unique names for narrative impact
- Possible special attacks (future: boss-specific abilities)

### NPC dungeon guides

NPCs near dungeon entrances can warn players about what lies within, providing difficulty hints via dialogue:

```python
# Guard NPC near cave entrance:
{
    "text": "That cave is full of goblins. I'd recommend being at least level 3 before entering.",
    "condition": {"type": "near_dungeon", "template_id": "goblin_cave"}
}
```

## AI Agent Considerations

### Dungeon planning

AI agents can evaluate dungeon readiness:
1. Check `status` for health/combat stats
2. Check `inventory` for healing items
3. Check `spells` for available magic
4. Compare against dungeon difficulty (from `dungeon_available` event)
5. Enter only when adequately prepared

### Navigation strategy

Inside a dungeon, AI agents should:
1. Explore rooms systematically (always go "deeper" first)
2. Clear enemies before proceeding
3. Collect keys from enemy drops
4. Use "back" to retreat if health is low
5. Track explored/unexplored rooms from movement events

### Loot evaluation

After clearing a dungeon, AI agents should:
1. `take` all loot items
2. `examine` items to check stats
3. `equip` upgrades
4. `leave_dungeon` when done

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/dungeon.py` | Dungeon aspect with generation, entry, cleanup |
| `backend/aspects/tests/test_dungeon.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/serverless.yml` | Add `dungeon` Lambda with SNS filter for `Dungeon` aspect |
| `backend/aspects/land.py` | Add dungeon entry detection in `look()` |
| `backend/aspects/combat.py` | Trigger dungeon boss completion on boss death |

### Implementation order

1. Define dungeon template registry with 2 templates
2. Create `dungeon.py` with generation algorithm (rooms, exits, enemies, loot)
3. Implement `enter_dungeon` with full instance creation
4. Implement `leave_dungeon` and cleanup scheduling
5. Add boss death detection and completion flow
6. Add locked door mechanics to Land.move()
7. Write tests (generation determinism, entry, navigation, boss kill, cleanup, cooldown)

## Open Questions

1. **Instance lifetime.** How long should an abandoned dungeon exist? 4 hours is arbitrary. Longer = more DynamoDB storage; shorter = potential data loss if player disconnects.

2. **Difficulty scaling.** Current formula: `stat * (1 + difficulty * 0.2)`. Should difficulty auto-scale based on player level? Or be fixed per template?

3. **Dungeon persistence.** Current design: dungeons are destroyed after completion. Should completed dungeons leave a "cleared" state that blocks re-entry until cooldown? Or should they simply be gone?

4. **Group dungeons.** Can multiple players share an instance? The current per-player design avoids this complexity. Group dungeons would need shared instance state, difficulty scaling for group size, and loot distribution rules.

5. **Dungeon entities and table bloat.** A 6-room dungeon with 10 enemies creates ~16 entities. If many players are running dungeons simultaneously, this could create significant DynamoDB write load. Monitor and optimize -- batch writes, or generate rooms on-demand as the player explores rather than all at once.

6. **Traps.** How do traps work mechanically? When a player enters a trap room, does damage apply automatically? Or is there a skill check / save mechanic? Start simple: automatic damage on entry, announce the trap in the room description.
