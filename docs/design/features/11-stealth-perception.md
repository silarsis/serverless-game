# Stealth and Perception Aspect

## What This Brings to the World

Stealth introduces asymmetric information to a world that currently operates on perfect knowledge. Right now, `look` shows every entity at a location -- every player, every NPC, every item. There is no way to observe without being observed, no way to approach without being announced, no way to gain tactical advantage through positioning. Stealth breaks this symmetry. A hidden entity is at the same location as everyone else but exists outside their awareness. This creates a new category of gameplay: reconnaissance, ambush, evasion, and the tension of knowing that what you see might not be all that is there.

The biome-stealth interaction is the strongest design element. Forests are natural cover; deserts offer nowhere to hide. This means the worldgen system -- which already assigns biomes to every room -- retroactively gains tactical significance. A player planning an ambush will seek forested terrain. A player being hunted will avoid open plains. Geography becomes strategy, and that makes the procedurally generated world feel more purposeful than it did before. Combined with the day/night cycle (hiding is easier at night, obviously), stealth creates a web of interactions across existing systems that makes the whole game feel more cohesive.

The danger of this design is that it modifies `look`, which is the single most-called command in the game. Every `look` invocation must now load every entity at the location, check each one for a Stealth aspect, compare stealth scores against the observer's perception, and filter the results. This transforms `look` from an O(N) operation (N entity reads) into an O(N*2) operation (N entity reads + N aspect reads for stealth checks). In a room with 15 entities, that is 15 additional DynamoDB reads per `look`. Since `look` fires on every room entry, every manual look, and every AI agent observation cycle, this is the single most impactful per-call cost increase of any design in this series. The feature is worth having -- stealth is fundamental to the genre -- but it will be the second thing (after combat) to expose the 1 RCU provisioning limit.

## Critical Analysis

**Every look() call must now check stealth state of each entity at the location.** The current `look` implementation queries the `contents` GSI to get entity UUIDs at the location, then returns them as a list. With stealth, each entity UUID must be checked: load entity (1 read), check if it has Stealth aspect, and if so load the Stealth aspect data (1 read) to compare stealth score against the observer's perception. For a room with 10 entities where 3 are hidden, that is 10 entity reads + 3 aspect reads = 13 reads minimum, up from the current 1 GSI query. With the existing Weather read, Equipment reads during combat, and now stealth checks on look, the per-command DynamoDB read count is creeping toward unsustainable levels at 1 RCU provisioning. At 100 concurrent players each looking once per 5 seconds, that is 260 reads/second against a 1 RCU table.

**Race condition: entity hides while another entity is mid-look.** Player A starts a `look` command. The Lambda loads the contents list and begins iterating entities. While iterating, Player B (at the same location) executes `hide`. Player B's Lambda writes `is_hidden: True` to their Stealth aspect. Player A's Lambda has already loaded Player B's entity but has not yet checked their stealth state. Depending on timing, Player A's Lambda may read the stale (non-hidden) state or the fresh (hidden) state. This is a TOCTOU (time-of-check-time-of-use) race. The practical impact is low -- the player either sees or doesn't see the hiding entity for one `look` call -- but it means stealth is not perfectly consistent within a single observation.

**NPC perception checks on every tick add reads per NPC per tick.** Guard NPCs with automatic search behavior must load the contents of their location (1 GSI query), then for each entity, check if it has a Stealth aspect and compare scores (up to N entity reads + N aspect reads). A guard NPC in a room with 8 entities performs 1 + 8 + 8 = 17 DynamoDB reads per tick. With 50 guard NPCs ticking every 30 seconds, that is 50 * 17 / 30 = 28.3 reads per second just for NPC perception, on top of all other read operations. This is bounded by the number of guard NPCs and their location population, but it scales linearly with both.

**Hidden entities still receive broadcast events -- information leak.** When Player A attacks Player B at a location, `broadcast_to_location` sends the combat event to all entities at that location, including hidden entities. A hidden player sees the combat play out even though the combatants should not know the hidden player is there. This is correct from a gameplay perspective (hiding does not make you deaf), but it means hidden players receive information about the room's state without revealing themselves. More problematically, the broadcast reveals that the hidden player's entity is at that location to any system that inspects the broadcast recipient list. The WebSocket push itself is fine -- the hidden player's client receives events -- but any future logging or audit system that records "entities that received this event" would leak hidden entity presence.

**Stealth stacking with fog_cloud spell creates degenerate invisibility.** The fog_cloud spell from the Magic design reduces visibility for all entities at a location. If a hidden entity is in a fog cloud, do observers check stealth against perception with the fog penalty applied? If fog reduces perception by some amount and stealth is already high from forest biome bonus and equipment, the combined modifiers could make detection nearly impossible. The design needs to either cap the total stealth modifier or explicitly define how fog_cloud interacts with the stealth system. Without this, a shadow mage in a forest at night with fog_cloud active could have an effective stealth score that exceeds any possible perception check.

**Sneak movement bypasses the arrival broadcast -- but departure is trickier.** When an entity sneaks to a new location, the design suppresses the arrival broadcast at the destination. But what about the departure broadcast at the origin? If the entity was hidden at the origin (they were sneaking around), no departure broadcast is needed because nobody knew they were there. But if they were visible and then used `sneak` to move, observers at the origin should notice someone leaving -- or should they? The `sneak` command needs to handle both cases: hidden-to-hidden (no broadcasts at either end) and visible-to-hidden (departure broadcast at origin, no arrival at destination). The current Entity.location setter always broadcasts departure and arrival, so `sneak` must bypass it entirely and handle location updates manually.

**Ambush damage bonus creates a burst damage meta.** A +50% damage bonus from attacking out of stealth is significant. Combined with equipment bonuses, biome bonuses to attack, and elemental spell bonuses, a well-prepared stealth attacker could one-shot most entities. This creates a "glass cannon from stealth" playstyle that is fun for the attacker but miserable for the target, who takes massive damage with no warning. The bonus should either be capped (e.g., ambush damage cannot exceed target's max_hp * 0.5) or the reveal-on-attack mechanic should give the target a brief window to react before the bonus applies.

**Low infrastructure cost but high integration surface.** Stealth requires no new DynamoDB table, no new CloudWatch rules, and no new infrastructure pattern. But it modifies `Land.look()` (the most-called command), `Entity.broadcast_to_location()` (the core event distribution method), `Combat.attack()` (for ambush bonus), and `NPC.tick()` (for guard perception). Every one of these is a heavily-used code path. A bug in the stealth check logic could break the most fundamental player experience (seeing what is in a room). The blast radius of a stealth bug is larger than almost any other feature because it touches the observation layer that every other feature depends on.

## Overview

The Stealth and Perception aspect adds hidden state to entities. Entities can hide (becoming invisible to observers with lower perception), sneak between locations (moving without triggering arrival broadcasts), search for hidden entities (active perception check), and ambush from stealth (bonus damage on first attack). Stealth is a numeric score (0-100) compared against observers' perception scores. Biome modifiers make terrain tactically significant: forests grant stealth bonuses, deserts impose penalties. The system integrates with Combat (ambush bonus), Land (biome modifiers, look filtering), NPC (guard auto-search), Equipment (stealth/perception gear bonuses), and Weather (night/fog modifiers).

## Design Principles

**Stealth is numeric, not boolean.** An entity does not simply "hide" or "not hide." It has a stealth score computed from base skill, biome modifiers, equipment, and time-of-day. Observers have a perception score computed from base skill, equipment, and conditions. Detection is the comparison: if perception >= stealth, the entity is visible. This creates gradations -- a high-perception guard detects a mediocre rogue, but a master rogue slips past.

**Biome is strategy.** The same stealth attempt produces different scores in different terrain. Forests are cover, deserts are exposure. This makes the worldgen map a tactical resource. Players learn to plan routes through favorable terrain, and the procedural world gains strategic depth it did not have before.

**Each aspect owns its data.** Stealth scores, hidden state, and perception values live in the Stealth aspect's record in LOCATION_TABLE. Biome data lives on Land. Equipment bonuses live on Equipment. The Stealth aspect reads these cross-aspect values explicitly when computing effective scores.

**Observation is the gatekeeper.** Stealth modifies what information players receive, not what actions they can take. A hidden entity is still at the location and can still be affected by area spells, traps, and environmental effects. Stealth controls visibility, not invulnerability.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| is_hidden | bool | False | Whether the entity is currently hidden |
| stealth_skill | int | 10 | Base stealth skill (0-100) |
| perception_skill | int | 10 | Base perception skill (0-100) |
| current_stealth_score | int | 0 | Computed stealth score when last hidden (includes modifiers) |
| stealth_xp | int | 0 | XP earned from stealth actions |
| stealth_level | int | 1 | Stealth proficiency level |
| times_hidden | int | 0 | Successful hide attempts (for XP) |
| times_detected | int | 0 | Times detected while hidden |
| last_hidden_at | str | "" | Location UUID where entity last hid |

### Biome Stealth Modifiers

| Biome | Stealth Modifier | Description |
|-------|-----------------|-------------|
| forest | +20 | Dense foliage provides natural cover |
| cave | +15 | Shadows and irregular surfaces to hide behind |
| swamp | +10 | Mist and dense vegetation |
| misty_highlands | +10 | Fog and rolling terrain |
| mountain_peak | +5 | Rocky outcroppings, limited but present |
| plains | -10 | Flat, open ground with nowhere to hide |
| desert | -15 | Vast empty expanses with clear sightlines |

### Time-of-Day Modifiers

| Time Period | Stealth Modifier | Perception Modifier |
|-------------|-----------------|---------------------|
| dawn | +5 | -5 |
| day | 0 | 0 |
| dusk | +10 | -5 |
| night | +20 | -10 |

### Stealth Score Computation

```python
def _compute_stealth_score(self) -> int:
    """Compute effective stealth score from all modifiers."""
    base = self.data.get("stealth_skill", 10)

    # Biome modifier
    biome_mod = self._get_biome_modifier()

    # Time-of-day modifier
    time_mod = self._get_time_modifier()

    # Equipment bonus
    equip_mod = 0
    try:
        equip = self.entity.aspect("Equipment")
        equip_mod = equip.data.get("stat_bonuses", {}).get("stealth", 0)
    except (ValueError, KeyError):
        pass

    # Level bonus: +2 per stealth level above 1
    level_bonus = (self.data.get("stealth_level", 1) - 1) * 2

    score = base + biome_mod + time_mod + equip_mod + level_bonus
    return max(0, min(100, score))


def _compute_perception_score(self) -> int:
    """Compute effective perception score from all modifiers."""
    base = self.data.get("perception_skill", 10)

    # Time-of-day modifier (perception is reduced at night)
    time_mod = self._get_perception_time_modifier()

    # Equipment bonus
    equip_mod = 0
    try:
        equip = self.entity.aspect("Equipment")
        equip_mod = equip.data.get("stat_bonuses", {}).get("perception", 0)
    except (ValueError, KeyError):
        pass

    # Level bonus: +2 per stealth level above 1 (perception scales with stealth level)
    level_bonus = (self.data.get("stealth_level", 1) - 1) * 2

    score = base + time_mod + equip_mod + level_bonus
    return max(0, min(100, score))
```

## Commands

### `hide`

```python
@player_command
def hide(self) -> dict:
    """Attempt to hide at the current location."""
```

**Validation:**
1. Entity must not already be hidden (`is_hidden == False`)
2. Entity must be at a location (has a `location` set)
3. Entity must not be dead (if Combat aspect exists, `hp > 0`)
4. Entity must not be in active combat (`last_attacker` must be empty or stale -- cannot hide while being attacked)

**Behavior:**
1. Load the current location's Land aspect to get biome
2. Load WorldState for time-of-day modifier (if Weather aspect exists)
3. Load Equipment aspect for stealth_bonus (if Equipment aspect exists)
4. Compute stealth score from base skill + biome + time + equipment + level
5. Set `is_hidden = True` and `current_stealth_score = computed_score`
6. Set `last_hidden_at = current_location_uuid`
7. Increment `times_hidden` and grant stealth XP
8. Save Stealth aspect
9. Do NOT broadcast to location (hiding is silent)

**Stealth XP:**
```python
stealth_xp_gain = 5 + biome_modifier_abs  # Harder terrain = more XP
self.data["stealth_xp"] = self.data.get("stealth_xp", 0) + stealth_xp_gain
if self.data["stealth_xp"] >= self.data.get("stealth_level", 1) * 150:
    self.data["stealth_level"] = self.data.get("stealth_level", 1) + 1
    self.data["stealth_xp"] = 0
    level_up = True
```

**Return format:**
```python
{
    "type": "hide_confirm",
    "stealth_score": 45,
    "biome": "forest",
    "biome_modifier": 20,
    "message": "You slip into the shadows of the forest. (Stealth: 45)"
}
# If biome is unfavorable:
{
    "type": "hide_confirm",
    "stealth_score": 12,
    "biome": "desert",
    "biome_modifier": -15,
    "message": "You crouch low against the sand, but there is little cover here. (Stealth: 12)"
}
# Level up:
{
    "type": "hide_confirm",
    "stealth_score": 52,
    "biome": "cave",
    "biome_modifier": 15,
    "level_up": True,
    "new_level": 3,
    "message": "You melt into the cave shadows. (Stealth: 52) Your stealth skill has improved to level 3!"
}
```

### `sneak <direction>`

```python
@player_command
def sneak(self, direction: str) -> dict:
    """Move to an adjacent location without being detected."""
```

**Validation:**
1. Entity must be hidden (`is_hidden == True`) or will attempt to hide first
2. Direction must be a valid exit from the current location
3. Entity must not be dead

**Behavior:**
1. If not already hidden, attempt to hide first (compute stealth score at current location)
2. Load destination room's Land aspect for biome
3. Compute new stealth score at the destination (biome may differ)
4. If new stealth score <= 0 (e.g., sneaking from forest to open desert): reveal entity, cancel sneak
5. Bypass `Entity.location` setter to avoid departure/arrival broadcasts
6. Directly update `entity.data["location"]` and `entity._save()`
7. Set `current_stealth_score` to the score at the new location
8. Set `last_hidden_at` to the new location UUID
9. Do NOT broadcast departure or arrival
10. Return the destination room description (same as `move` but silent)

```python
def _sneak_move(self, direction: str) -> dict:
    """Move without triggering broadcasts."""
    room = self._current_room()
    if direction not in room.exits:
        return {"type": "error", "message": f"There is no exit to the {direction}."}

    dest_uuid = room.exits[direction]

    # Compute stealth at destination
    try:
        dest_land = Land(uuid=dest_uuid)
        dest_biome = dest_land.data.get("biome", "plains")
    except KeyError:
        dest_biome = "plains"

    new_score = self._compute_stealth_score_for_biome(dest_biome)

    if new_score <= 5:
        # Too exposed at destination -- reveal and move normally
        self.data["is_hidden"] = False
        self.data["current_stealth_score"] = 0
        self._save()
        # Fall through to normal movement
        if self.entity:
            self.entity.location = dest_uuid  # This broadcasts
        return {
            "type": "sneak_failed",
            "direction": direction,
            "message": f"You emerge from cover into the {dest_biome}. There is nowhere to hide here."
        }

    # Silent move -- bypass Entity.location setter
    old_location = self.entity.data.get("location")
    self.entity.data["location"] = dest_uuid
    self.entity._save()

    # Update stealth state
    self.data["current_stealth_score"] = new_score
    self.data["last_hidden_at"] = dest_uuid
    self._save()

    # Load destination description for the sneaker
    try:
        dest_land = Land(uuid=dest_uuid)
    except KeyError:
        dest_land = None

    desc = dest_land.description if dest_land else "An unknown location."

    return {
        "type": "sneak_confirm",
        "direction": direction,
        "stealth_score": new_score,
        "biome": dest_biome,
        "description": desc,
        "exits": list(dest_land.exits.keys()) if dest_land else [],
        "message": f"You creep {direction}, staying hidden. (Stealth: {new_score})"
    }
```

**Return format:**
```python
# Success:
{
    "type": "sneak_confirm",
    "direction": "north",
    "stealth_score": 38,
    "biome": "forest",
    "description": "A dense thicket of ancient oaks...",
    "exits": ["north", "south", "east"],
    "message": "You creep north, staying hidden. (Stealth: 38)"
}
# Failed (too exposed at destination):
{
    "type": "sneak_failed",
    "direction": "east",
    "message": "You emerge from cover into the desert. There is nowhere to hide here."
}
```

### `search`

```python
@player_command
def search(self, target_uuid: str = "") -> dict:
    """Search for hidden entities at the current location."""
```

**Validation:**
1. Entity must be at a location
2. Entity must not be dead

**Behavior:**
1. Compute observer's perception score (base + equipment + time + level)
2. Load all entities at the current location via contents GSI
3. For each entity, check if it has a Stealth aspect with `is_hidden == True`
4. For each hidden entity, compare `observer_perception >= hidden_stealth_score`
5. Entities whose stealth is beaten are revealed: set `is_hidden = False`, broadcast reveal
6. Entities whose stealth holds remain hidden (observer does not even know they are there)
7. If target_uuid is specified, only search for that specific entity (if you suspect someone is there)
8. Grant perception XP regardless of success

```python
def _do_search(self, target_uuid: str = "") -> dict:
    """Perform a perception check against hidden entities."""
    perception = self._compute_perception_score()
    loc_uuid = self.entity.location
    if not loc_uuid:
        return {"type": "error", "message": "You are not at a location."}

    try:
        loc_entity = Entity(uuid=loc_uuid)
    except KeyError:
        return {"type": "error", "message": "Location not found."}

    revealed = []
    searched_count = 0

    for entity_uuid in loc_entity.contents:
        if entity_uuid == self.entity.uuid:
            continue
        if target_uuid and entity_uuid != target_uuid:
            continue

        try:
            other = Entity(uuid=entity_uuid)
            # Check if entity has Stealth aspect and is hidden
            if "Stealth" not in other.data.get("aspects", []):
                continue
            stealth_aspect = other.aspect("Stealth")
            if not stealth_aspect.data.get("is_hidden", False):
                continue

            searched_count += 1
            hidden_score = stealth_aspect.data.get("current_stealth_score", 0)

            if perception >= hidden_score:
                # Detected! Reveal the entity
                stealth_aspect.data["is_hidden"] = False
                stealth_aspect.data["current_stealth_score"] = 0
                stealth_aspect.data["times_detected"] = (
                    stealth_aspect.data.get("times_detected", 0) + 1
                )
                stealth_aspect._save()

                revealed.append({
                    "uuid": other.uuid,
                    "name": other.name,
                    "stealth_score": hidden_score,
                })

                # Notify the revealed entity
                other.push_event({
                    "type": "revealed",
                    "by": self.entity.name,
                    "by_uuid": self.entity.uuid,
                    "message": f"{self.entity.name} spots you hiding!"
                })

                # Broadcast to location
                self.entity.broadcast_to_location(
                    loc_uuid,
                    {
                        "type": "entity_revealed",
                        "searcher": self.entity.name,
                        "revealed": other.name,
                        "revealed_uuid": other.uuid,
                        "message": f"{self.entity.name} discovers {other.name} hiding nearby!"
                    },
                )
        except (KeyError, ValueError):
            continue

    return {
        "type": "search_result",
        "perception": perception,
        "revealed": revealed,
        "message": self._search_message(revealed, searched_count),
    }


def _search_message(self, revealed: list, searched_count: int) -> str:
    """Generate a descriptive message for search results."""
    if not revealed and searched_count == 0:
        return "You search the area carefully but find nothing unusual."
    if not revealed and searched_count > 0:
        return "You sense something nearby, but cannot pinpoint it."
    if len(revealed) == 1:
        return f"You spot {revealed[0]['name']} hiding in the shadows!"
    names = ", ".join(r["name"] for r in revealed)
    return f"Your keen eyes reveal: {names}!"
```

**Return format:**
```python
# Found hidden entities:
{
    "type": "search_result",
    "perception": 35,
    "revealed": [
        {"uuid": "rogue-uuid", "name": "ShadowThief", "stealth_score": 30}
    ],
    "message": "You spot ShadowThief hiding in the shadows!"
}
# Found nothing:
{
    "type": "search_result",
    "perception": 20,
    "revealed": [],
    "message": "You search the area carefully but find nothing unusual."
}
# Sensed but could not detect:
{
    "type": "search_result",
    "perception": 20,
    "revealed": [],
    "message": "You sense something nearby, but cannot pinpoint it."
}
```

### `perception`

```python
@player_command
def perception(self) -> dict:
    """Check your current stealth and perception stats."""
```

**Behavior:** Loads all modifier sources and displays the entity's current stealth and perception capabilities, broken down by component.

**Return format:**
```python
{
    "type": "stealth_status",
    "is_hidden": True,
    "current_stealth_score": 45,
    "stealth_skill": 15,
    "perception_skill": 12,
    "stealth_level": 3,
    "stealth_xp": 80,
    "xp_to_next_level": 450,
    "biome": "forest",
    "biome_stealth_mod": 20,
    "time_period": "night",
    "time_stealth_mod": 20,
    "time_perception_mod": -10,
    "equipment_stealth_mod": 5,
    "equipment_perception_mod": 0,
    "effective_stealth": 62,
    "effective_perception": 14,
    "times_hidden": 47,
    "times_detected": 3,
    "message": "You are hidden. Stealth: 62 | Perception: 14"
}
```

### `reveal` (self-reveal)

```python
@player_command
def reveal(self) -> dict:
    """Step out of hiding voluntarily."""
```

**Behavior:**
1. Set `is_hidden = False`, `current_stealth_score = 0`
2. Broadcast arrival to location (as if the entity just appeared)
3. Save

**Return format:**
```python
{
    "type": "reveal_confirm",
    "message": "You step out of the shadows."
}
```

## Cross-Aspect Interactions

### Stealth + Land (biome modifiers and look filtering)

The primary integration point. `Land.look()` must filter hidden entities from the contents list based on the observer's perception:

```python
# Modified Land.look() -- filter hidden entities
@player_command
def look(self) -> dict:
    """Look around the current location, filtering hidden entities."""
    room = self._current_room()
    self._generate_room(room)

    desc = room.description or f"An empty stretch of land at {room.coordinates}."

    # Get room contents
    room_entity_contents = []
    try:
        room_entity = Entity(uuid=room.uuid)
        all_contents = room_entity.contents
    except (KeyError, Exception):
        all_contents = []

    # Filter hidden entities based on observer's perception
    observer_perception = 10  # Default perception
    try:
        if "Stealth" in self.entity.data.get("aspects", []):
            stealth = self.entity.aspect("Stealth")
            observer_perception = stealth._compute_perception_score()
    except (ValueError, KeyError):
        pass

    for entity_uuid in all_contents:
        if entity_uuid == self.entity.uuid:
            room_entity_contents.append(entity_uuid)
            continue
        try:
            other = Entity(uuid=entity_uuid)
            if "Stealth" not in other.data.get("aspects", []):
                room_entity_contents.append(entity_uuid)
                continue
            other_stealth = other.aspect("Stealth")
            if not other_stealth.data.get("is_hidden", False):
                room_entity_contents.append(entity_uuid)
                continue
            # Hidden entity -- check perception
            hidden_score = other_stealth.data.get("current_stealth_score", 0)
            if observer_perception >= hidden_score:
                room_entity_contents.append(entity_uuid)
                # Don't reveal them -- just the observer can see them
        except (KeyError, ValueError):
            room_entity_contents.append(entity_uuid)

    return {
        "type": "look",
        "description": desc,
        "coordinates": list(room.coordinates),
        "exits": list(room.exits.keys()),
        "contents": room_entity_contents,
        "biome": room.data.get("biome", "unknown"),
    }
```

Biome modifier lookup:

```python
BIOME_STEALTH_MODIFIERS = {
    "forest": 20,
    "cave": 15,
    "swamp": 10,
    "misty_highlands": 10,
    "mountain_peak": 5,
    "plains": -10,
    "desert": -15,
    "dungeon": 10,  # Dungeons are dark
}

def _get_biome_modifier(self) -> int:
    """Get the stealth modifier for the current biome."""
    loc_uuid = self.entity.location if self.entity else None
    if not loc_uuid:
        return 0
    try:
        land = Land(uuid=loc_uuid)
        biome = land.data.get("biome", "plains")
        return BIOME_STEALTH_MODIFIERS.get(biome, 0)
    except KeyError:
        return 0
```

### Stealth + Combat (ambush bonus and reveal on attack)

Attacking from stealth grants a damage bonus and reveals the attacker:

```python
# In Combat.attack(), check for stealth ambush:
def _check_ambush(self, attacker_entity: Entity) -> float:
    """Check if attacker is hidden and calculate ambush bonus."""
    try:
        if "Stealth" not in attacker_entity.data.get("aspects", []):
            return 1.0
        stealth = attacker_entity.aspect("Stealth")
        if stealth.data.get("is_hidden", False):
            # Reveal the attacker
            stealth.data["is_hidden"] = False
            stealth.data["current_stealth_score"] = 0
            stealth._save()

            # Broadcast the reveal
            loc_uuid = attacker_entity.location
            if loc_uuid:
                attacker_entity.broadcast_to_location(
                    loc_uuid,
                    {
                        "type": "ambush_reveal",
                        "actor": attacker_entity.name,
                        "actor_uuid": attacker_entity.uuid,
                        "message": f"{attacker_entity.name} strikes from the shadows!"
                    },
                )
            return 1.5  # 50% damage bonus
    except (ValueError, KeyError):
        pass
    return 1.0

# In the attack damage calculation:
ambush_multiplier = self._check_ambush(self.entity)
final_damage = int(base_damage * ambush_multiplier)
```

### Stealth + Equipment (gear bonuses)

Equipment items can have `stealth_bonus` and `perception_bonus` stats:

```python
# Item with stealth bonus:
{
    "name": "shadow cloak",
    "slot": "body",
    "defense_bonus": 1,
    "stealth_bonus": 15,
    "description": "A cloak woven from shadow-silk that bends light around the wearer."
}

# Item with perception bonus:
{
    "name": "eagle-eye helm",
    "slot": "head",
    "defense_bonus": 2,
    "perception_bonus": 10,
    "description": "A helm enchanted with the keen sight of a mountain eagle."
}

# Reading equipment bonuses in Stealth aspect:
def _get_equipment_stealth_bonus(self) -> int:
    """Get stealth bonus from equipped items."""
    try:
        equip = self.entity.aspect("Equipment")
        return equip.data.get("stat_bonuses", {}).get("stealth", 0)
    except (ValueError, KeyError):
        return 0

def _get_equipment_perception_bonus(self) -> int:
    """Get perception bonus from equipped items."""
    try:
        equip = self.entity.aspect("Equipment")
        return equip.data.get("stat_bonuses", {}).get("perception", 0)
    except (ValueError, KeyError):
        return 0
```

### Stealth + Weather (time-of-day modifiers)

Stealth checks the WorldState for time-of-day modifiers:

```python
WORLD_STATE_UUID = "00000000-0000-0000-0000-000000000001"

TIME_STEALTH_MODIFIERS = {
    "dawn": 5,
    "day": 0,
    "dusk": 10,
    "night": 20,
}

TIME_PERCEPTION_MODIFIERS = {
    "dawn": -5,
    "day": 0,
    "dusk": -5,
    "night": -10,
}

def _get_time_modifier(self) -> int:
    """Get the stealth modifier for the current time of day."""
    try:
        world_state = Entity(uuid=WORLD_STATE_UUID)
        weather = world_state.aspect("Weather")
        time_period = weather.data.get("current_time", "day")
        return TIME_STEALTH_MODIFIERS.get(time_period, 0)
    except (KeyError, Exception):
        return 0

def _get_perception_time_modifier(self) -> int:
    """Get the perception modifier for the current time of day."""
    try:
        world_state = Entity(uuid=WORLD_STATE_UUID)
        weather = world_state.aspect("Weather")
        time_period = weather.data.get("current_time", "day")
        return TIME_PERCEPTION_MODIFIERS.get(time_period, 0)
    except (KeyError, Exception):
        return 0
```

### Stealth + Communication (filtered broadcasts)

Hidden entities should not appear in `say` attribution to observers who cannot see them:

```python
# In Communication.say(), check if speaker is hidden:
def _get_speaker_attribution(self, speaker_entity: Entity, observer_entity: Entity) -> str:
    """Determine how to attribute speech based on stealth."""
    try:
        if "Stealth" not in speaker_entity.data.get("aspects", []):
            return speaker_entity.name
        stealth = speaker_entity.aspect("Stealth")
        if not stealth.data.get("is_hidden", False):
            return speaker_entity.name

        # Speaker is hidden -- check observer's perception
        observer_perception = 10
        if "Stealth" in observer_entity.data.get("aspects", []):
            obs_stealth = observer_entity.aspect("Stealth")
            observer_perception = obs_stealth._compute_perception_score()

        hidden_score = stealth.data.get("current_stealth_score", 0)
        if observer_perception >= hidden_score:
            return speaker_entity.name  # Observer can see them
        return "a voice from the shadows"  # Observer cannot see them
    except (ValueError, KeyError):
        return speaker_entity.name
```

### Stealth + NPC (guard auto-search)

Guard NPCs automatically perform perception checks during their tick:

```python
# In NPC._guard(), add perception check:
def _guard(self):
    """Stay in place, observe surroundings, search for hidden entities."""
    self._check_for_players()
    self._search_for_hidden()

def _search_for_hidden(self):
    """Guard automatically searches for hidden entities."""
    if "Stealth" not in self.entity.data.get("aspects", []):
        return

    loc_uuid = self.entity.location if self.entity else None
    if not loc_uuid:
        return

    stealth = self.entity.aspect("Stealth")
    perception = stealth._compute_perception_score()

    try:
        loc_entity = Entity(uuid=loc_uuid)
    except KeyError:
        return

    for entity_uuid in loc_entity.contents:
        if entity_uuid == self.entity.uuid:
            continue
        try:
            other = Entity(uuid=entity_uuid)
            if "Stealth" not in other.data.get("aspects", []):
                continue
            other_stealth = other.aspect("Stealth")
            if not other_stealth.data.get("is_hidden", False):
                continue

            hidden_score = other_stealth.data.get("current_stealth_score", 0)
            if perception >= hidden_score:
                # Guard detects hidden entity
                other_stealth.data["is_hidden"] = False
                other_stealth.data["current_stealth_score"] = 0
                other_stealth.data["times_detected"] = (
                    other_stealth.data.get("times_detected", 0) + 1
                )
                other_stealth._save()

                # Alert
                self.entity.broadcast_to_location(
                    loc_uuid,
                    {
                        "type": "guard_alert",
                        "guard": self.entity.name,
                        "detected": other.name,
                        "detected_uuid": other.uuid,
                        "message": f"{self.entity.name} shouts: 'I see you, {other.name}! Come out!'"
                    },
                )

                other.push_event({
                    "type": "revealed",
                    "by": self.entity.name,
                    "by_uuid": self.entity.uuid,
                    "message": f"The {self.entity.name} spots you! Your cover is blown!"
                })
        except (KeyError, ValueError):
            continue
```

## Event Flow

### Hide Sequence

```
Player sends: {"command": "hide", "data": {}}
  -> Entity.receive_command(command="hide")
    -> Stealth.hide()
      -> Validate: not already hidden, not dead, not in combat
      -> Load Land aspect for current location biome
      -> Load WorldState for time-of-day modifier
      -> Load Equipment for stealth_bonus
      -> Compute stealth score: base + biome + time + equipment + level
      -> Set is_hidden=True, current_stealth_score=computed
      -> Grant stealth XP, check level up
      -> Save Stealth aspect
      -> push_event(hide_confirm to player)
      -> NO broadcast to location (hiding is silent)
```

### Sneak Movement Sequence

```
Player sends: {"command": "sneak", "data": {"direction": "north"}}
  -> Entity.receive_command(command="sneak")
    -> Stealth.sneak(direction="north")
      -> Validate: direction is valid exit
      -> If not hidden: attempt hide first
      -> Load destination Land aspect for biome
      -> Compute stealth score at destination
      -> If score <= 5: reveal, fall back to normal move with broadcast
      -> If score > 5:
        -> Directly write entity.data["location"] = dest_uuid (bypass setter)
        -> entity._save() (no departure/arrival broadcast)
        -> Update stealth score for new biome
        -> Save Stealth aspect
        -> push_event(sneak_confirm to player)
```

### Search Sequence

```
Player sends: {"command": "search", "data": {}}
  -> Entity.receive_command(command="search")
    -> Stealth.search()
      -> Compute observer perception score
      -> Query contents GSI for entities at location
      -> For each entity with Stealth aspect where is_hidden=True:
        -> Compare perception >= stealth_score
        -> If detected: set is_hidden=False, broadcast reveal
        -> If not detected: skip (observer does not know)
      -> push_event(search_result to player)
```

### Ambush Attack Sequence

```
Hidden player sends: {"command": "attack", "data": {"target_uuid": "goblin-uuid"}}
  -> Entity.receive_command(command="attack")
    -> Combat.attack(target_uuid="goblin-uuid")
      -> Check attacker Stealth aspect: is_hidden=True
      -> Apply ambush multiplier: 1.5x damage
      -> Set attacker is_hidden=False (revealed by attack)
      -> Broadcast ambush reveal to location
      -> Apply damage to target
      -> push_event(attack_confirm with ambush bonus noted)
```

### Guard NPC Auto-Search

```
NPC tick fires every 30 seconds
  -> NPC.tick()
    -> behavior == "guard":
      -> _guard()
        -> _check_for_players() (existing greeting logic)
        -> _search_for_hidden()
          -> Load own Stealth aspect, compute perception
          -> For each entity at location with is_hidden=True:
            -> Compare perception vs stealth score
            -> If detected: reveal entity, broadcast alert
```

## NPC Integration

### Stealth-capable NPCs

NPCs can have the Stealth aspect for ambush predators and rogues:

```python
# Creating a stealthy NPC:
rogue_npc = Entity()
rogue_npc.data["aspects"] = ["NPC", "Combat", "Stealth"]
rogue_npc.data["primary_aspect"] = "NPC"
rogue_npc.data["name"] = "Shadow Lurker"
rogue_npc._save()

stealth = rogue_npc.aspect("Stealth")
stealth.data["stealth_skill"] = 40
stealth.data["perception_skill"] = 25
stealth.data["is_hidden"] = True
stealth.data["current_stealth_score"] = 55
stealth._save()

npc = rogue_npc.aspect("NPC")
npc.create(behavior="hostile", name="Shadow Lurker")
```

### NPC behavior variants with stealth

| Behavior | Stealth Usage |
|----------|--------------|
| guard | Auto-searches for hidden entities every tick |
| hostile | If has Stealth aspect: hides, ambushes players who enter |
| patrol | If has Stealth aspect: stays hidden while patrolling |
| wander | Does not use stealth (too casual) |
| merchant | Does not use stealth |

### Hostile NPC ambush behavior

```python
# In NPC._seek_and_attack(), check if NPC should ambush:
def _seek_and_attack(self):
    """Attack players, with ambush if hidden."""
    # If NPC has stealth and is hidden, wait for player to get close
    if "Stealth" in self.entity.data.get("aspects", []):
        stealth = self.entity.aspect("Stealth")
        if stealth.data.get("is_hidden", False):
            # Ambush! Attack from stealth (Combat will handle the bonus)
            for entity_uuid in loc_entity.contents:
                if entity_uuid == self.entity.uuid:
                    continue
                try:
                    target = Entity(uuid=entity_uuid)
                    if target.connection_id:  # It's a player
                        combat = self.entity.aspect("Combat")
                        combat.attack(target_uuid=entity_uuid)
                        return
                except (KeyError, ValueError):
                    continue
    # Fall through to normal hostile behavior
    # ...
```

### Guard NPCs in high-security areas

Guards in important locations (settlements, quest areas) should have higher perception:

```python
# Creating a high-perception guard:
guard = Entity()
guard.data["aspects"] = ["NPC", "Combat", "Stealth"]
guard.data["primary_aspect"] = "NPC"
guard._save()

stealth = guard.aspect("Stealth")
stealth.data["stealth_skill"] = 10  # Guards are not stealthy
stealth.data["perception_skill"] = 45  # But very perceptive
stealth._save()

combat = guard.aspect("Combat")
combat.data["hp"] = 40
combat.data["attack"] = 8
combat.data["defense"] = 6
combat._save()

npc = guard.aspect("NPC")
npc.create(behavior="guard", name="Settlement Guard")
```

## AI Agent Considerations

### Stealth decision-making

AI agents receive the same stealth events and commands as human players. The structured data enables tactical decision-making:

1. Check biome via `look` response before attempting to hide
2. Use `perception` command to assess own stealth/perception scores
3. Use `hide` in favorable biomes (forest, cave) before approaching dangerous areas
4. Use `sneak` to avoid hostile NPCs when health is low
5. Use `search` when entering rooms where ambush is likely (dungeons, caves)
6. Attack from stealth for the ambush bonus when initiating combat

### Stealth planning loop

```
1. look -> check biome
2. If biome has positive stealth modifier:
   a. perception -> check own scores
   b. If stealth_skill + biome_mod > 30: hide -> sneak toward objective
   c. If target found: attack from stealth (ambush bonus)
3. If biome has negative stealth modifier:
   a. search -> check for hidden enemies
   b. Proceed openly, use combat if necessary
4. Track "times_detected" -- if high, invest in stealth equipment
```

### Information asymmetry

AI agents should understand that hidden entities may exist at their location even if `look` does not show them. The `search` command is the only way to confirm an area is clear. An agent should search before resting, crafting, or performing other vulnerable actions.

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/stealth.py` | Stealth aspect class with hide, sneak, search, perception, reveal commands |
| `backend/aspects/tests/test_stealth.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/serverless.yml` | Add `stealth` Lambda with SNS filter for `Stealth` aspect |
| `backend/aspects/land.py` | Modify `look()` to filter hidden entities based on observer perception |
| `backend/aspects/combat.py` | Add ambush check in `attack()` for stealth damage bonus and reveal |
| `backend/aspects/npc.py` | Add `_search_for_hidden()` to guard behavior in `tick()` |
| `backend/aspects/communication.py` | Modify `say` attribution for hidden speakers |

### Implementation order

1. Create `stealth.py` with Stealth class, biome modifiers, score computation
2. Implement `hide`, `reveal`, `perception` commands (no cross-aspect deps)
3. Implement `search` command with perception vs stealth comparison
4. Implement `sneak` command with silent movement (bypass Entity.location setter)
5. Modify `Land.look()` to filter hidden entities
6. Modify `Combat.attack()` for ambush bonus and reveal-on-attack
7. Modify `NPC.tick()` for guard auto-search behavior
8. Add Lambda + SNS filter to serverless.yml
9. Write tests (hide score calc, biome modifiers, search detection, sneak movement, ambush damage, look filtering)

## Open Questions

1. **Should hiding break on any action, or only attack?** Current design: only attacking reveals you. But what about casting a spell, using an item, or speaking? A fireball from stealth should probably reveal you. Speaking while hidden could remain anonymous ("a voice from the shadows"). Define a list of actions that break stealth.

2. **Can you hide in combat?** Current design says no (cannot hide while `last_attacker` is set). But what about fleeing into stealth? If a player flees combat and immediately hides, is that valid? It creates a disengage-hide loop that could be exploited. Possible solution: add a cooldown after taking damage before hiding is allowed.

3. **Group stealth?** If two players are sneaking together, does the lower stealth score apply to both? Or is each checked independently? Independent checks are simpler but mean the stealthy rogue is penalized by their clumsy paladin companion. Group stealth is more realistic but requires new mechanics.

4. **Stealth versus area-of-effect spells.** If a fog_cloud or fireball targets "all entities at location," do hidden entities get hit? The design principle says hidden entities are still at the location and can be affected by area effects. But this means you could cast fireball to "flush out" hidden entities -- which is valid tactically but reveals their presence (they take damage) without a perception check.

5. **Should perception passively detect hidden entities during look, or require active search?** Current design: `look` passively compares perception vs stealth. This means high-perception characters automatically see hidden entities without using `search`. An alternative: `look` never shows hidden entities, and only `search` reveals them. The passive approach rewards perception investment; the active approach creates more gameplay decisions.

6. **Stealth skill progression speed.** At 5 XP per hide and 150 XP per level, level 2 requires 30 successful hides. Is this too fast or too slow? The level bonus (+2 per level) compounds with equipment and biome, so high-level stealth characters could become nearly undetectable. Consider diminishing returns at higher levels.

7. **What happens when a hidden entity's location is destroyed (dungeon cleanup)?** If a hidden player is in a dungeon room that gets cleaned up, the entity is still at a location UUID that no longer exists. This is the same as the non-stealth case, but stealth means the player might not receive warning broadcasts about the dungeon ending. Ensure dungeon cleanup broadcasts reach hidden entities.
