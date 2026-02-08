# Building/Construction Aspect

## Overview

The Building aspect allows entities to place persistent structures in the game world. Structures are new entities with exits, creating rooms inside buildings that other entities can enter. Construction requires materials from the Crafting system. Land plots near landmarks can be claimed for building. Built structures become part of the world -- other players can visit, interact with, and (with permission) modify them. This enables player shops, fortifications, homes, and portals.

## Design Principles

**Structures are entities.** A built house is an entity with a Land aspect (it has exits connecting it to the world grid) and a Building aspect (it has a builder, permissions, and structural data). This fits the existing model -- no new storage concepts needed.

**Construction is non-instant.** Building takes multiple steps: claim a plot, gather materials, place a foundation, then complete construction. This creates progression and makes buildings feel earned. The delayed event system (`Call.after()`) schedules build completion.

**Land integration.** Structures connect to the existing room grid by adding exits to adjacent Land entities. A house at coordinates (3,5,0) adds an "enter house" exit to the (3,5,0) room and creates interior rooms with exits back out.

**Each aspect owns its data.** Building stores the blueprint, builder UUID, permissions, and construction progress. Land stores exits and location properties. Inventory stores material requirements. No cross-table writes.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

### On the structure entity:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Structure entity UUID (primary key) |
| builder_uuid | str | "" | UUID of the entity that built this |
| structure_type | str | "" | Blueprint type (house, wall, shop, etc.) |
| construction_progress | int | 0 | 0-100 build progress |
| is_complete | bool | False | Whether construction is finished |
| permissions | dict | {} | Who can modify/destroy this structure |
| rooms | list | [] | UUIDs of interior room entities |

### On the builder entity:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| claimed_plots | list | [] | List of location UUIDs the entity has claimed |
| structures_built | list | [] | List of structure entity UUIDs |

### Blueprint Registry

```python
BLUEPRINTS = {
    "campfire": {
        "name": "Campfire",
        "description": "A simple campfire for light and warmth.",
        "materials": {"wood": 3},
        "rooms": 0,
        "build_ticks": 1,
        "effects": {"light": True, "warmth": True},
        "requires_claim": False,
    },
    "shelter": {
        "name": "Shelter",
        "description": "A basic lean-to shelter.",
        "materials": {"wood": 5, "cloth": 2},
        "rooms": 1,
        "build_ticks": 3,
        "requires_claim": True,
    },
    "house": {
        "name": "House",
        "description": "A sturdy wooden house with one room.",
        "materials": {"wood": 15, "stone": 10},
        "rooms": 2,
        "build_ticks": 10,
        "requires_claim": True,
    },
    "shop": {
        "name": "Shop",
        "description": "A small merchant shop.",
        "materials": {"wood": 10, "stone": 5, "metal": 3},
        "rooms": 1,
        "build_ticks": 8,
        "requires_claim": True,
        "features": ["trade_counter"],
    },
    "watchtower": {
        "name": "Watchtower",
        "description": "A tall watchtower for surveying the surroundings.",
        "materials": {"stone": 20, "wood": 10, "metal": 5},
        "rooms": 2,
        "build_ticks": 15,
        "requires_claim": True,
        "features": ["extended_vision"],
    },
}
```

## Commands

### `claim`

```python
@player_command
def claim(self) -> dict:
    """Claim the current location as a building plot."""
```

**Validation:**
1. Location must be a Land entity (not interior of another building)
2. Location must not already be claimed by another entity
3. Entity must not exceed max claims (default: 3)
4. Location must be near a landmark (within 3 tiles) -- prevents building in the middle of nowhere

**Behavior:**
1. Mark location entity with `claimed_by: entity_uuid`
2. Add location UUID to entity's `claimed_plots`
3. Broadcast claim event

**Return format:**
```python
{
    "type": "claim_confirm",
    "location": "location-uuid",
    "message": "You claim this plot of land for building."
}
```

### `build <blueprint_id>`

```python
@player_command
def build(self, blueprint_id: str) -> dict:
    """Begin constructing a structure at the current (claimed) location."""
```

**Validation:**
1. Must be at a claimed plot owned by this entity
2. Blueprint must exist in registry
3. Must have all required materials in inventory
4. No structure already under construction at this location

**Behavior:**
1. Consume materials from inventory
2. Create structure entity with Building and Land aspects
3. Set `construction_progress = 0`
4. Schedule build ticks via `Call.after()`
5. On each tick: increment progress by (100 / build_ticks)
6. On completion:
   - Create interior room entities
   - Add exits connecting exterior <-> interior
   - Mark structure as complete
   - Broadcast completion event

**Return format:**
```python
{
    "type": "build_started",
    "blueprint": "house",
    "progress": 0,
    "ticks_remaining": 10,
    "message": "You begin constructing a house. This will take some time."
}
```

### `demolish`

```python
@player_command
def demolish(self) -> dict:
    """Demolish a structure at the current location (must be the builder)."""
```

**Validation:** Entity must be the builder or have admin permissions.

**Behavior:**
1. Remove exits from adjacent Land entities
2. Destroy interior room entities
3. Destroy structure entity
4. Unclaim the plot
5. Optionally return some materials (50% recovery)

### `structures`

```python
@player_command
def structures(self) -> dict:
    """List structures you've built."""
```

**Return format:**
```python
{
    "type": "structures",
    "structures": [
        {
            "uuid": "struct-uuid",
            "type": "house",
            "location": "loc-uuid",
            "complete": True,
            "name": "Kevin's House"
        }
    ],
    "claims": 2,
    "max_claims": 3
}
```

## Cross-Aspect Interactions

### Building + Land (room connections)

When a structure completes, exits are created:

```python
def _complete_structure(self, structure_entity, blueprint):
    # Create interior rooms
    room_count = blueprint["rooms"]
    interior_rooms = []
    for i in range(room_count):
        room = Entity()
        room.data["aspects"] = ["Land"]
        room.data["primary_aspect"] = "Land"
        room.data["name"] = f"{blueprint['name']} - Room {i+1}"
        room._save()

        room_land = room.aspect("Land")
        room_land.data["biome"] = "interior"
        room_land.data["description"] = f"Inside {blueprint['name']}."
        room_land._save()

        interior_rooms.append(room.uuid)

    # Connect exterior to first interior room
    exterior_land = Land(uuid=self.entity.location)
    exterior_exits = exterior_land.data.get("exits", {})
    exterior_exits[f"enter {blueprint['name'].lower()}"] = interior_rooms[0]
    exterior_land.data["exits"] = exterior_exits
    exterior_land._save()

    # Connect interior back to exterior
    first_room_land = Land(uuid=interior_rooms[0])
    first_room_exits = first_room_land.data.get("exits", {})
    first_room_exits["exit"] = self.entity.location
    first_room_land.data["exits"] = first_room_exits
    first_room_land._save()

    # Chain interior rooms
    for i in range(len(interior_rooms) - 1):
        room_a = Land(uuid=interior_rooms[i])
        room_b = Land(uuid=interior_rooms[i+1])
        a_exits = room_a.data.get("exits", {})
        b_exits = room_b.data.get("exits", {})
        a_exits["deeper"] = interior_rooms[i+1]
        b_exits["back"] = interior_rooms[i]
        room_a.data["exits"] = a_exits
        room_b.data["exits"] = b_exits
        room_a._save()
        room_b._save()
```

### Building + Inventory (material consumption)

Materials are consumed during `build`:

```python
# Find and consume materials
for material_tag, count_needed in blueprint["materials"].items():
    consumed = 0
    for item_uuid in self.entity.contents:
        if consumed >= count_needed:
            break
        item = Entity(uuid=item_uuid)
        item_inv = item.aspect("Inventory")
        if material_tag in item_inv.data.get("tags", []):
            item.destroy()
            consumed += 1
```

### Building + Crafting (construction recipes)

Building blueprints are effectively large-scale crafting recipes. Future: the Crafting aspect could unlock advanced blueprints when crafting skill is high enough.

### Building + Faction (territory)

Structures in faction territory could require faction standing:
- Friendly standing required to build in faction territory
- Hostile faction members cannot enter player structures (locked doors)

### Building + NPC (player shops)

Structures with `features: ["trade_counter"]` enable player-run shops:
- Owner places items on the trade counter (specific interior entity)
- Visiting players can buy items
- Revenue goes to owner's inventory

## Event Flow

### Build Sequence

```
Player sends: {"command": "build", "data": {"blueprint_id": "house"}}
  -> Building.build(blueprint_id="house")
    -> Validate claim, materials, blueprint
    -> Consume materials from inventory
    -> Create structure entity (incomplete)
    -> Schedule first build tick: Call(...).after(seconds=30)
    -> Return build_started event

Build tick fires (every 30 seconds):
  -> Building._build_tick()
    -> Increment construction_progress
    -> push_event(build_progress) to builder
    -> If progress >= 100:
      -> _complete_structure()
      -> Create interior rooms, add exits
      -> push_event(build_complete) to builder
      -> broadcast_to_location(structure_complete) to location
```

### Demolish Sequence

```
Player sends: {"command": "demolish"}
  -> Building.demolish()
    -> Validate builder/admin
    -> Remove exits from adjacent rooms
    -> Destroy interior room entities
    -> Destroy structure entity
    -> Unclaim plot
    -> Return 50% materials via Inventory.create_item()
    -> push_event(demolish_confirm)
```

## NPC Integration

### NPC-built structures

The world generator can pre-place structures at landmarks:
- Guard towers at settlement borders
- Merchant shops at town centers
- Hermit cabins in remote areas

These are structurally identical to player buildings but have `builder_uuid` set to a system entity UUID.

### NPC shop interaction

Players enter a merchant's shop structure and interact with the merchant NPC inside. The shop's trade_counter feature enables browse/buy commands.

### NPC construction workers

Future: NPC "builder" behavior that constructs structures on behalf of the faction. Players could commission NPCs to build for them.

## AI Agent Considerations

### Building strategy

AI agents can plan construction:
1. Call `structures` to see current buildings and claim availability
2. Navigate to a strategic location (near resources, defended terrain)
3. `claim` the plot
4. Use `recipes` and `gather` to collect materials
5. `build` the desired structure
6. Wait for completion (monitor build_progress events)

### Structure usage

AI agents can use structures strategically:
- Build shelters for safe rest stops
- Build shops for trade automation
- Build watchtowers for extended vision
- Navigate to own buildings for safety during hostile encounters

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/building.py` | Building aspect class with blueprint registry |
| `backend/aspects/tests/test_building.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/serverless.yml` | Add `building` Lambda with SNS filter for `Building` aspect |
| `backend/aspects/land.py` | Support dynamic exit addition/removal |

### Implementation order

1. Define blueprint registry with 3-5 starter structures
2. Create `building.py` with Building class, claim, build, demolish, structures commands
3. Implement build tick progression via delayed events
4. Implement room creation and exit wiring on completion
5. Add demolish with material recovery
6. Write tests (claim, build, complete, exit creation, demolish)

## Open Questions

1. **Plot proximity requirement.** "Near a landmark" is vague. Define as within N tiles? What counts as a landmark? The worldgen system knows which locations are landmarks -- use that data.

2. **Building limits per player.** Default 3 claims prevents spam but may be too restrictive. Should it scale with level or faction standing?

3. **Structure decay.** Should unvisited buildings decay over time? Adds realism but punishes casual players. Consider: structures in faction territory are maintained by NPCs, others decay.

4. **Permissions model.** Who can enter, modify, or demolish a structure? Start simple (builder only), expand later (door locks, keys, friend lists).

5. **Interior room descriptions.** Should interior rooms use the LLM description generator? Interior biome "interior" needs appropriate descriptors. Or use static descriptions from the blueprint.
