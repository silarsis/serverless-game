# Combat Aspect

## What This Brings to the World

Combat is the gravity well of a game like this. Without it, you have a walking simulator with an inventory system -- pleasant but inert. Adding combat gives entities a reason to exist in adversarial relationships, gives players a reason to care about the items they carry, and gives the world stakes. When a goblin blocks a cave entrance, the player has to make a decision. That decision -- fight, flee, or find another way -- is the seed of emergent gameplay.

For this architecture specifically, combat is a natural fit in some ways and a dangerous one in others. The aspect-oriented model means you can slap Combat onto any entity and it becomes fightable, which is elegant. A door could have hit points. A tree could fight back. The broadcast_to_location mechanism maps well to combat narration -- everyone in the room sees the fight play out. And the SNS event model means death can trigger cascading effects (loot drops, respawns, quest updates) without Combat knowing about those systems.

The danger is that combat is the single highest-write-frequency system in the game. Every attack touches at minimum two entities and two aspect records. In a busy room with 5 players fighting 3 NPCs, the write contention on DynamoDB items will be intense. Combat is the system most likely to expose the cracks in a 1 WCU provisioned table, and the system most likely to produce corrupted state from concurrent last-write-wins overwrites. It belongs in this game, but it will be the first thing that breaks at scale.

## Critical Analysis

**The _on_death underscore problem is a showstopper.** The `_on_death` method is decorated with `@callable`, meaning it is intended to be invoked via SNS dispatch. However, `Entity._action()` explicitly rejects methods that start with an underscore as a security measure to prevent players from calling internal methods. This means `_on_death` will never actually fire when called via `Call(...).after()`, because the SNS handler will route through `_action()` and reject it. The respawn system as written is dead code. Either rename it to `on_death` (and accept that players could theoretically invoke it directly) or add a bypass for system-originated calls.

**Two-player-attack race condition will corrupt HP.** When two players attack the same target simultaneously, both Lambda invocations read the target's Combat aspect, both compute `hp -= damage`, and both call `_save()` which does a full `put_item`. The second write overwrites the first. If the goblin has 20 HP and Player A deals 5 and Player B deals 8, the goblin should have 7 HP. Instead it will have either 15 or 12, depending on which Lambda finishes last. There are no DynamoDB transactions or conditional writes anywhere in the codebase. This is not an edge case -- it is the primary use case for combat.

**Death loot drop is an O(N*M) broadcast bomb.** When an entity dies, `_on_death` iterates every item in inventory and sets each item's location to the current room. Each location change is a separate entity write. Worse, if any of these item drops trigger broadcasts (e.g., "a sword clatters to the ground"), each broadcast requires 1 GSI query + M get_items + M API Gateway posts for M entities at the location. For an entity carrying 20 items in a room with 10 observers, that is 20 entity writes + 20 * (1 + 10 + 10) = 420 DynamoDB operations + 200 API Gateway posts. On a 1 WCU table, this will throttle for minutes.

**Respawn via Call.after(seconds=30) costs Step Functions money.** Each death creates one Step Functions execution with 30 state transitions (one per second of wait). At $0.000025 per transition, that is $0.00075 per death. If hostile NPCs respawn too and the world has 100 hostile NPCs dying and respawning in a cycle, that is 100 * $0.00075 * 2 (player + NPC deaths) every cycle. More critically, on the local development server, `Call.after()` executes immediately with no delay, so respawn timing is completely untestable locally. A 30-second respawn and a 300-second respawn behave identically in dev.

**XP scaling is linear and too easy.** The formula `level * 100` XP to level up means level 1 needs 100 XP, level 10 needs 1000 XP, level 20 needs 2000 XP. Since XP gain is `target.level * 10`, killing a level 10 creature gives 100 XP. A level 19 player needs 1900 XP to reach 20, which means killing 19 level-10 creatures. Quadratic or exponential scaling (e.g., `level^2 * 50`) would create a more meaningful progression curve. As-is, a player can max out combat level in a single play session.

**Status effect ticks have no scheduling mechanism for players.** `Combat.tick()` processes status effects like poison, but `tick()` is only called by the NPC aspect's tick loop. Players do not have NPC aspects, so player status effects will never tick. A player poisoned by a snake will stay poisoned forever (or until they die from some other cause). The design needs either a dedicated Combat tick scheduler for players or a time-based calculation that resolves poison damage on the next player action.

**Hostile NPC targeting is first-come, ignore-the-rest.** The `_seek_and_attack` method iterates `loc_entity.contents` and attacks the first entity with a `connection_id` (i.e., the first player), then returns. If five players are in a room with a hostile dragon, the dragon attacks whichever player happens to be first in the contents list every single tick. There is no aggro table, no threat tracking, no target-switching. The other four players can attack with impunity. This makes group combat trivially exploitable.

**Dependency chain.** Combat depends on Inventory (loot drops), Communication (broadcasts), Land (location checks), and optionally Equipment (stat bonuses). It must be implemented after Inventory and Land. The NPC integration means NPC aspect must also exist. This is a mid-tier dependency position -- not the worst, but not standalone either.

**No damage log or combat history.** The design tracks `last_attacker` but not a history of damage dealt or received. For debugging race conditions or auditing combat exploits, there is no record of what happened. The only trace is the ephemeral broadcast messages sent to connected players.

## Overview

The Combat aspect adds hit points, attack, defense, and damage mechanics to any entity. Entities with Combat can attack each other, take damage, and die. Death triggers respawn at origin (0,0,0) and inventory drop. Combat integrates with existing Inventory (loot drops), Communication (combat narration), NPC (guard behavior, hostile creatures), and Land (location-based encounters).

## Design Principles

**Aspect-oriented, not class-based.** A dragon does not `extend CombatCreature`. It is an entity that *has* a Combat aspect alongside Land, Inventory, and NPC aspects. Adding combat to a previously peaceful NPC means adding `"Combat"` to its aspects list and setting stats -- no code changes.

**Each aspect owns its data.** Combat stats (hp, max_hp, attack, defense) live in the Combat aspect's record in `LOCATION_TABLE`. The entity table stores only shared fields (uuid, name, location, connection_id). Equipment bonuses are read cross-aspect via `self.entity.aspect("Equipment").data["stat_bonuses"]`.

**Explicit cross-aspect access.** When Combat needs to check if the target has an Equipment aspect, it uses `target_entity.aspect("Equipment")` -- the dependency is visible in code. No hidden coupling.

**Events, not direct calls.** Combat results broadcast to the location via `self.entity.broadcast_to_location()`. Death events route through SNS so other aspects (Inventory for loot drop, NPC for respawn behavior) can react independently.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| hp | int | 20 | Current hit points |
| max_hp | int | 20 | Maximum hit points |
| attack | int | 5 | Base attack power |
| defense | int | 2 | Base defense |
| is_dead | bool | False | Whether entity is currently dead |
| xp | int | 0 | Experience points earned |
| level | int | 1 | Combat level |
| pvp_enabled | bool | False | Whether this entity opts into PvP |
| last_attacker | str | "" | UUID of last entity that dealt damage |
| status_effects | list | [] | Active status effects (poison, stun, etc.) |

### Status Effects

Each status effect is a dict:

```python
{
    "name": "poison",
    "damage_per_tick": 2,
    "ticks_remaining": 3,
    "source_uuid": "attacker-uuid"
}
```

Status effects are processed during `Combat.tick()` via the delayed event system (`Call(...).after(seconds=N)`).

## Commands

### `attack <target_uuid>`

```python
@player_command
def attack(self, target_uuid: str) -> dict:
    """Attack another entity at the same location."""
```

**Validation:**
- Attacker must have hp > 0 (not dead)
- Target must exist and be at the same location
- Target must have a Combat aspect
- If target is a player entity, target must have `pvp_enabled=True` (or attacker is NPC)
- Cannot attack self

**Damage calculation:**
```python
base_damage = max(1, attacker_attack - target_defense)
# Equipment bonuses added if Equipment aspect exists
if attacker has Equipment aspect:
    base_damage += equipment_attack_bonus
if target has Equipment aspect:
    base_damage -= equipment_defense_bonus
    base_damage = max(1, base_damage)
final_damage = base_damage
```

**Return format:**
```python
{
    "type": "attack_confirm",
    "target": target_name,
    "target_uuid": target_uuid,
    "damage": final_damage,
    "target_hp": target_hp_remaining,
    "message": "You strike the goblin for 5 damage."
}
```

**Broadcasts to location:**
```python
{
    "type": "combat",
    "actor": attacker_name,
    "actor_uuid": attacker_uuid,
    "target": target_name,
    "target_uuid": target_uuid,
    "damage": final_damage,
    "message": "PlayerName attacks the goblin for 5 damage!"
}
```

### `flee`

```python
@player_command
def flee(self) -> dict:
    """Attempt to flee combat by moving to a random exit."""
```

**Behavior:** Loads the Land aspect of the current location, picks a random exit, moves there. 50% success chance. On failure, the entity stays and takes a free hit from `last_attacker` (if present and at same location).

**Return format:**
```python
# Success:
{"type": "flee_confirm", "message": "You flee north!", "direction": "north"}
# Failure:
{"type": "flee_failed", "message": "You fail to escape! The goblin strikes you for 3 damage."}
```

### `status`

```python
@player_command
def status(self) -> dict:
    """Show combat stats (HP, attack, defense, level, effects)."""
```

**Return format:**
```python
{
    "type": "combat_status",
    "hp": 15,
    "max_hp": 20,
    "attack": 5,
    "defense": 2,
    "level": 3,
    "xp": 45,
    "status_effects": ["poison (2 ticks)"],
    "pvp": False
}
```

### `pvp`

```python
@player_command
def pvp(self) -> dict:
    """Toggle PvP mode on/off."""
```

Toggles `pvp_enabled`. Returns confirmation. Players must opt in before other players can attack them. NPCs can always be attacked (they don't check PvP flag).

## Cross-Aspect Interactions

### Combat + Inventory (loot drops)

On death:
1. Combat aspect sets `is_dead = True`
2. Broadcasts death event to location
3. Calls `self.entity.aspect("Inventory")` to get inventory contents
4. For each item in inventory, sets `item_entity.location = current_location` (drops items on the ground)
5. After delay (respawn timer), resets hp and moves entity to origin

```python
# Death handler (internal)
@callable
def _on_death(self, killer_uuid: str = "") -> dict:
    self.data["is_dead"] = True
    self.data["hp"] = 0
    self._save()

    # Drop all inventory items at current location
    try:
        inv = self.entity.aspect("Inventory")
        for item_uuid in self.entity.contents:
            try:
                item = Entity(uuid=item_uuid)
                item.location = self.entity.location
            except KeyError:
                pass
    except (ValueError, KeyError):
        pass

    # Schedule respawn after 30 seconds
    Call(
        tid=str(uuid4()), originator=self.entity.uuid,
        uuid=self.entity.uuid, aspect="Combat", action="_respawn"
    ).after(seconds=30)

    return {"type": "death", "entity_uuid": self.entity.uuid}
```

### Combat + Equipment (stat bonuses)

When calculating attack/defense, Combat checks for an Equipment aspect:

```python
def _effective_attack(self) -> int:
    base = self.data.get("attack", 5)
    try:
        equip = self.entity.aspect("Equipment")
        bonuses = equip.data.get("stat_bonuses", {})
        base += bonuses.get("attack", 0)
    except (ValueError, KeyError):
        pass
    return base
```

### Combat + NPC (hostile behavior)

NPCs with `behavior: "guard"` gain combat capabilities:
- When a hostile entity enters their location, guards attack automatically
- Guards have combat stats set during creation
- On guard death, respawn at patrol origin after delay

NPCs with `behavior: "hostile"` attack any player on sight:
- Added as a new NPC behavior variant
- Hostile NPCs attack the first player they see during `_check_for_players()`

### Combat + Land (terrain effects)

Future: certain biomes could modify combat (e.g., high ground gives +1 attack, swamp gives -1 defense). Not in initial implementation.

### Combat + Communication (combat narration)

Combat broadcasts are styled as Communication events. Players at the location see combat play out in real-time via their event stream. The same `broadcast_to_location` mechanism used for `say` handles combat events.

## Event Flow

### Attack Sequence

```
Player sends: {"command": "attack", "data": {"target_uuid": "goblin-uuid"}}
  -> websocket_handlers.command_handler
    -> SNS: Entity.receive_command(command="attack", target_uuid="goblin-uuid")
      -> Combat.attack(target_uuid="goblin-uuid")
        -> Load target entity
        -> Calculate damage
        -> Apply damage to target Combat aspect
        -> If target hp <= 0: Call target._on_death()
        -> broadcast_to_location(combat event)
        -> push_event(attack_confirm to attacker)
        -> Save both aspects
```

### Death and Respawn

```
Combat._on_death()
  -> Set is_dead=True, hp=0
  -> Drop inventory items (set item locations to current room)
  -> broadcast_to_location(death event)
  -> Call(...).after(seconds=30) -> Combat._respawn()

Combat._respawn()
  -> Set is_dead=False, hp=max_hp
  -> Clear status_effects
  -> Set entity.location to origin (0,0,0 room UUID)
  -> push_event(respawn event)
```

### XP and Leveling

```
On kill:
  -> Attacker gains xp = target.level * 10
  -> If xp >= level * 100:
    -> level += 1
    -> max_hp += 5
    -> attack += 1
    -> defense += 1
    -> hp = max_hp (full heal on level up)
    -> push_event(level_up event)
```

## NPC Integration

### Creating combat NPCs

```python
# During world generation or NPC creation:
npc_entity = Entity()
npc_entity.data["aspects"] = ["NPC", "Combat", "Land"]
npc_entity.data["primary_aspect"] = "NPC"
npc_entity._save()

# Set combat stats
combat = npc_entity.aspect("Combat")
combat.data["hp"] = 30
combat.data["max_hp"] = 30
combat.data["attack"] = 8
combat.data["defense"] = 3
combat.data["level"] = 3
combat._save()

# Set NPC behavior
npc = npc_entity.aspect("NPC")
npc.create(behavior="guard", name="Town Guard")
```

### NPC combat AI

In `NPC.tick()`, hostile NPCs check for targets:

```python
if behavior == "hostile":
    self._seek_and_attack()

def _seek_and_attack(self):
    """Attack the nearest player at this location."""
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
```

### NPC death and respawn

NPC deaths follow the same pattern as player deaths but with different respawn behavior:
- NPCs respawn at their creation location (stored as `spawn_location` in NPC data)
- Respawn delay is longer (60-300 seconds depending on NPC type)
- NPCs do not drop inventory (or drop only specific "loot table" items)

## AI Agent Considerations

### Combat decision-making

AI agents receive the same combat events as human players:
- `combat` events show who is attacking whom and for how much damage
- `status` command provides numeric stats for decision-making
- `flee` is available when health is low

An AI agent's combat loop:
1. Receive `arrive` event -- check if hostile NPCs present
2. Use `status` to assess own health
3. Decide: `attack` if healthy, `flee` if low hp
4. Process combat events to track target health
5. Loot items after combat via `take`

### No special combat API

AI agents use the same `attack`, `flee`, `status` commands as human players. The structured JSON responses (`damage`, `target_hp`, `hp`) provide all the numeric data an agent needs for decision trees.

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/combat.py` | Combat aspect class |
| `backend/aspects/tests/test_combat.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/serverless.yml` | Add `combat` Lambda with SNS filter for `Combat` aspect |
| `backend/aspects/npc.py` | Add hostile behavior, combat AI in tick() |

### Implementation order

1. Create `combat.py` with Combat class, attack, flee, status, pvp commands
2. Add death/respawn logic with delayed events
3. Add XP/leveling
4. Add Lambda + SNS filter to serverless.yml
5. Modify NPC to support hostile behavior
6. Write tests (attack, damage calc, death, respawn, flee, PvP toggle)

## Open Questions

1. **Should combat be turn-based or real-time?** Current design is real-time (attack whenever you want). Turn-based would need a combat state machine. Starting with real-time, simpler to implement and works with the event model.

2. **Damage formula complexity?** Starting simple (attack - defense, min 1). Could add randomness (roll 1d6 + attack), critical hits, etc. Keep simple initially.

3. **Should NPCs have loot tables?** Currently NPCs drop nothing on death. Adding loot tables means maintaining item definitions per NPC type. Defer to Crafting aspect integration.

4. **PvP zones vs opt-in?** Current design uses opt-in PvP flag. Alternative: certain locations are PvP zones. Could support both -- PvP flag OR PvP zone.

5. **How does death interact with quests?** If a player dies during a quest, do they lose progress? Probably not -- just respawn and continue. But certain quest items could be "soulbound" (don't drop on death).
