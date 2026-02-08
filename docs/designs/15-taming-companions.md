# Taming/Companion Aspect

## What This Brings to the World

A companion transforms the player's relationship with the world from observer to participant. Without companions, the player is a solitary agent passing through a landscape of NPCs that exist for their own purposes -- guards guard, merchants sell, hermits mutter. With a tamed companion, one of those creatures becomes *yours*. It follows you, fights beside you, carries your loot, and -- if you neglect it -- turns on you and walks away. That arc from wild creature to loyal companion to potential betrayal is the most emotionally resonant system a MUD can offer, because the companion is not a static item in your inventory. It is an NPC that chose to stop being an NPC.

The design's strongest architectural choice is that companions are not new entities. They are existing NPC entities whose behavior field changes from `"hostile"` or `"wanderer"` to `"companion"`. The wolf that was prowling the forest is the same wolf that now follows you. It keeps its UUID, its combat stats, its location record. The aspect model handles this cleanly: the NPC aspect's `behavior` field changes, a `master_uuid` field is added, and the NPC's tick loop dispatches to a new `_companion` behavior method. No new tables, no new entity types, no new GSI patterns.

The danger is that companions are the most expensive per-player persistent cost in the entire system. An active companion ticks every 30 seconds via Step Functions, forever, whether the player is online or not. Each tick reads the companion entity, reads the NPC aspect, checks the master's location, potentially moves the companion, and saves updated loyalty -- a minimum of 4 DynamoDB operations per tick. Multiply by 100 players and the companion system costs $6,480/month in Step Functions executions alone. This is a FUN system -- high engagement, strong player attachment, genuine emotional stakes -- but it needs a leash as much as the companion does.

## Critical Analysis

**Companion following player = 1 extra entity write per player move.** When a player moves, `Entity.location.setter` fires, writing the entity table and broadcasting arrival/departure. If the player has a companion, the companion must also move: second entity write, second departure broadcast, second arrival broadcast. Each broadcast is O(N) reads. A player with a companion in a settlement with 10 entities per room: 2 writes + 40 reads per move (vs 1 write + 20 reads without companion). With 10 players moving simultaneously (each with companions): 20 writes competing for 1 WCU -- a 20-second write queue just for movement.

**Companion tick costs $0.00075 per 30 seconds per companion.** Per companion per day: $2.16. Per companion per month: $64.80. With 100 players: $6,480/month in Step Functions. Adding companions doubles the NPC tick bill. Total NPC+companion tick cost at 100 players with companions and 100 world NPCs: $12,960/month.

**Loyalty decay means companion ticks MUST fire reliably.** If Step Functions drops ticks, loyalty freezes -- the companion stays loyal longer than intended. No timestamp-based catchup mechanism exists. A wolf with `base_loyalty_decay=2` should hit 0 loyalty in 25 minutes without feeding; dropped ticks extend this for free. This is a soft exploit if Step Functions is unreliable.

**Taming modifies the NPC entity's data -- a cross-aspect write from Taming to NPC.** This violates the "each aspect owns its data" principle. The alternatives are worse: routing through SNS adds latency to a time-sensitive operation, and duplicating the behavior field fragments state. The direct cross-aspect write is pragmatic but documented.

**Race condition: player moves, companion follow fires, player moves again before companion write completes.** The companion's location write lands at a stale destination. Not data corruption -- the companion catches up on the next tick -- but produces confusing narrative output ("A loyal wolf arrives." in a room the player left 10 seconds ago).

**Companion death destroys a world-generated NPC permanently.** The forest wolf population drops with each companion death. No respawn mechanism applies to `behavior="companion"` entities. The design needs a companion-death-triggered wild creature respawn at the original spawn location.

**Max 1 companion limit creates a silent dismissal problem.** Taming a second creature dismisses the first via cross-location write. The dismissed companion reverts to its original behavior (potentially `"hostile"`) and may immediately attack other players at its location with no warning.

**Combat companion auto-attack adds 4 reads + 2 writes + 1 broadcast per companion attack per tick.** Not catastrophic alone, but additive with the player's combat operations.

**Disconnected players still pay for companion ticks.** A player who disconnects with a freshly-fed wolf companion pays for ~25 minutes of ticks ($0.0375) that serve only to make the companion go feral.

**Dependency chain.** Taming depends on NPC (behavior system, tick loop), Combat (companion combat, creature death), Inventory (bait items, carry capacity), and Land (following). NPC and Combat must be fully implemented. This is a late-stage feature that also modifies NPC core behavior.

## Overview

The Taming aspect allows players to tame wild NPC creatures (wolves, hawks, bears, elementals) to become persistent companions. Taming requires a food/bait item matching the creature type and a success roll based on player level and item quality. Tamed creatures change their NPC behavior to `"companion"`, follow the player, fight alongside them, and can carry items. Companions require ongoing feeding to maintain loyalty; neglected companions go feral. Each player may have at most one active companion.

## Design Principles

**Companions are NPCs, not items.** A tamed wolf is still an entity with NPC and Combat aspects. The Taming aspect transforms an existing entity by modifying its behavior and adding a `master_uuid` link.

**Loyalty is the leash.** Loyalty decays per tick and must be restored by feeding. Neglected companions go feral -- the consequence is real and permanent.

**Each aspect owns its data.** Taming stores `companion_uuid` and skill on the player. NPC stores `master_uuid`, `loyalty`, and companion fields on the creature. The cross-aspect write during taming is the one documented exception.

**Follow, don't lead.** Companions react to the player's actions. Movement follows the master. Combat targets the master's target. The tick checks master state and responds.

## Aspect Data

### Player Taming Data (LOCATION_TABLE)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Player entity UUID (primary key) |
| companion_uuid | str | "" | UUID of current active companion |
| taming_skill | int | 0 | Taming proficiency level |
| taming_xp | int | 0 | XP toward next taming level |
| tame_attempts | int | 0 | Total taming attempts |
| tame_successes | int | 0 | Total successful tames |

### Companion Data (added to NPC aspect on tame)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| master_uuid | str | "" | UUID of the owning player |
| loyalty | int | 50 | Current loyalty (0-100) |
| companion_name | str | "" | Player-assigned name |
| original_behavior | str | "" | Behavior before taming (for feral revert) |
| creature_type | str | "" | Registry key (wolf, hawk, bear, fire_elemental) |
| carry_capacity | int | 0 | Max items companion can hold |
| combat_style | str | "melee" | Combat approach (melee, ranged, tank, magic) |
| special_ability | str | "" | Unique ability (scout, light) |
| ticks_without_master | int | 0 | Absence counter |

### CREATURE_TAMING_TABLE Registry

```python
CREATURE_TAMING_TABLE = {
    "wolf":           {"food_tag": "meat",  "min_level": 1, "base_loyalty_decay": 2, "carry_capacity": 5,  "combat_style": "melee", "special": None,    "tame_xp": 10},
    "hawk":           {"food_tag": "seeds", "min_level": 3, "base_loyalty_decay": 3, "carry_capacity": 1,  "combat_style": "ranged","special": "scout", "tame_xp": 20},
    "bear":           {"food_tag": "fish",  "min_level": 5, "base_loyalty_decay": 1, "carry_capacity": 15, "combat_style": "tank",  "special": None,    "tame_xp": 35},
    "fire_elemental": {"food_tag": "gem",   "min_level": 8, "base_loyalty_decay": 4, "carry_capacity": 0,  "combat_style": "magic", "special": "light", "tame_xp": 50},
}
```

### Loyalty Scale

| Loyalty | State | Behavior |
|---------|-------|----------|
| 100 | Devoted | Always obeys, +10% combat damage |
| 70-99 | Loyal | Always obeys |
| 30-69 | Content | Obeys, may ignore complex commands |
| 10-29 | Restless | 30% chance to disobey |
| 1-9 | Defiant | 70% chance to disobey, will not fight |
| 0 | Feral | Reverts to original behavior |

## Commands

### `tame <target_uuid>`

```python
@player_command
def tame(self, target_uuid: str) -> dict:
    """Attempt to tame a wild creature as your companion."""
```

**Validation:**
1. Player must not already have a companion
2. Target must exist and be at the same location
3. Target must be an NPC with `creature_type` in `CREATURE_TAMING_TABLE`
4. Target must not already be tamed (`master_uuid` empty)
5. Player `taming_skill` must meet creature's `min_level`
6. Player must have bait item with matching `food_tag` in inventory

**Behavior:**
1. Consume bait item (`bait_item.destroy()`)
2. Calculate success chance: `(player_level * 10 + bait_quality * 20) / (creature_level * 15 + 50)`, capped at 90%
3. On failure: return `tame_failed`, broadcast attempt to location
4. On success: write NPC aspect (`behavior="companion"`, `master_uuid`, `loyalty=50`, creature fields), update player Taming aspect (`companion_uuid`), award taming XP

**Return format:**
```python
# Success:
{"type": "tame_success", "companion_name": "a wolf", "companion_uuid": "wolf-uuid",
 "creature_type": "wolf", "loyalty": 50, "message": "You have tamed a wolf!"}
# Failure:
{"type": "tame_failed", "target": "a wolf", "chance": 35,
 "message": "The Wolf rejects your offering. (35% chance)"}
```

**DynamoDB operations:** 1 entity read (target) + 1 NPC aspect read + N inventory reads (bait scan) + 1 Combat read (creature level) + 1 item delete + 1 NPC write + 1 Taming write + broadcast. Minimum 6 reads + 3 writes.

### `companion`

```python
@player_command
def companion(self) -> dict:
    """View your companion's status."""
```

**Return format:**
```python
{"type": "companion_status", "has_companion": True, "name": "Fang", "uuid": "wolf-uuid",
 "creature_type": "wolf", "loyalty": 72, "loyalty_state": "loyal",
 "combat": {"hp": 18, "max_hp": 20, "attack": 6, "defense": 2},
 "carry_capacity": 5, "items_carried": 2, "special_ability": "",
 "at_master_location": True, "message": "Fang: loyal (loyalty 72/100)"}
```

**DynamoDB operations:** 1 entity read + 1 NPC read + 1 Combat read + 1 GSI query = 4 reads, 0 writes.

### `command <action>`

```python
@player_command
def command(self, action: str) -> dict:
    """Give a command to your companion (attack/defend/follow/stay/dismiss/scout)."""
```

**Validation:** Companion must exist. Loyalty > 0 (not feral). Disobedience check: loyalty < 30 = 30% disobey chance, loyalty < 10 = 70% disobey chance.

**Actions:** `attack` (companion targets master's attacker on ticks), `defend` (companion guards master), `follow` (companion moves to master's location on ticks), `stay` (companion remains at current location), `dismiss` (revert to wild behavior), `scout` (hawk only -- reveals adjacent rooms).

**Return format:**
```python
{"type": "command_confirm", "action": "attack",
 "message": "Fang bares its teeth, ready to attack."}
# Or disobey:
{"type": "command_disobey", "action": "attack",
 "message": "Fang ignores your command."}
```

### `feed <item_uuid>`

```python
@player_command
def feed(self, item_uuid: str) -> dict:
    """Feed your companion to restore HP and loyalty."""
```

**Validation:** Companion must be at same location. Food item must have tag matching creature's `food_tag`. Food must be in player inventory.

**Behavior:** Destroy food item. Loyalty gain: `15 + quality * 5`. HP gain: `5 + quality * 3`.

**Return format:**
```python
{"type": "feed_confirm", "companion": "Fang", "loyalty_before": 45, "loyalty_after": 65,
 "loyalty_gain": 20, "hp_gain": 8, "message": "You feed Fang. Loyalty: 45 -> 65."}
```

**DynamoDB operations:** 4 reads + 3 writes (companion entity/NPC, food entity/Inventory, companion Combat).

### `name_companion <name>`

```python
@player_command
def name_companion(self, name: str) -> dict:
    """Give your companion a custom name (max 30 chars)."""
```

**Return format:**
```python
{"type": "name_confirm", "old_name": "a wolf", "new_name": "Fang",
 "message": "Your companion is now known as Fang."}
```

## Cross-Aspect Interactions

### Taming + NPC (behavior transformation)

The core interaction. Taming directly modifies the NPC aspect (cross-aspect write):

```python
# In Taming.tame() on success:
target_npc = target_entity.aspect("NPC")
target_npc.data["original_behavior"] = target_npc.data.get("behavior", "wander")
target_npc.data["behavior"] = "companion"
target_npc.data["master_uuid"] = self.entity.uuid
target_npc.data["loyalty"] = 50
target_npc._save()
```

NPC.tick() gains a new behavior branch:

```python
# In NPC.tick():
elif behavior == "companion":
    self._companion()

def _companion(self):
    """Follow master, assist in combat, decay loyalty."""
    master_uuid = self.data.get("master_uuid", "")
    if not master_uuid:
        self._go_feral()
        return
    try:
        master = Entity(uuid=master_uuid)
    except KeyError:
        self._go_feral()
        return

    # Decay loyalty
    creature_def = CREATURE_TAMING_TABLE.get(self.data.get("creature_type", ""), {})
    decay = creature_def.get("base_loyalty_decay", 2)
    self.data["loyalty"] = max(0, self.data.get("loyalty", 0) - decay)
    if self.data["loyalty"] <= 0:
        self._go_feral()
        return

    if self.entity.location == master.location:
        self.data["ticks_without_master"] = 0
        if self.data.get("companion_mode") == "attack":
            self._companion_combat(master)
    else:
        mode = self.data.get("companion_mode", "follow")
        if mode == "follow":
            self._move_to(self.entity.location, master.location)
        elif mode == "stay":
            self.data["ticks_without_master"] = self.data.get("ticks_without_master", 0) + 1
            if self.data["ticks_without_master"] > 20:  # 10 minutes
                self._wander()
    self._save()

def _go_feral(self):
    """Revert to wild behavior, notify master."""
    master_uuid = self.data.get("master_uuid", "")
    if master_uuid:
        try:
            master = Entity(uuid=master_uuid)
            master.push_event({"type": "companion_feral",
                "message": f"{self.data.get('companion_name', 'Your companion')} has gone feral!"})
            master_taming = master.aspect("Taming")
            if master_taming.data.get("companion_uuid") == self.entity.uuid:
                master_taming.data["companion_uuid"] = ""
                master_taming._save()
        except (KeyError, ValueError):
            pass
    self.data["behavior"] = self.data.get("original_behavior", "wander")
    self.data["master_uuid"] = ""
    self.data["loyalty"] = 0
    self._save()
```

### Taming + Combat (companion combat and death)

Companion auto-attacks the master's target:

```python
def _companion_combat(self, master: Entity):
    try:
        master_combat = master.aspect("Combat")
        target_uuid = master_combat.data.get("last_attacker", "")
        if not target_uuid:
            return
        target = Entity(uuid=target_uuid)
        if target.location != self.entity.location:
            return
        comp_combat = self.entity.aspect("Combat")
        if comp_combat.data.get("hp", 0) > 0:
            comp_combat.attack(target_uuid=target_uuid)
    except (KeyError, ValueError):
        pass
```

On companion death, Combat._on_death() must notify master and clear taming data:

```python
# Added to Combat._on_death():
try:
    npc = self.entity.aspect("NPC")
    if npc.data.get("behavior") == "companion":
        master = Entity(uuid=npc.data.get("master_uuid", ""))
        master.push_event({"type": "companion_death",
            "message": f"{npc.data.get('companion_name')} has been slain!"})
        master_taming = master.aspect("Taming")
        master_taming.data["companion_uuid"] = ""
        master_taming._save()
except (KeyError, ValueError):
    pass
```

### Taming + Inventory (companion carry capacity)

Players can give items to companions (up to `carry_capacity`):

```python
@player_command
def give_companion(self, item_uuid: str) -> dict:
    """Give an item to your companion to carry."""
    # Validate companion exists, is at same location
    # Check len(comp_entity.contents) < carry_capacity
    # Set item_entity.location = companion_uuid
    return {"type": "give_confirm", "companion": comp_name,
            "item": item_entity.name, "carried": current + 1, "capacity": capacity}
```

### Taming + Land (following)

Companion following is handled via the tick loop (see `_companion()` above), not by modifying `Land.move()`. The companion follows on its next tick (up to 30 seconds later). This trades responsiveness for simplicity -- hooking into `Land.move()` would add +1 entity read, +1 aspect read, +1 entity write per player move.

## Event Flow

### Taming Sequence

```
Player sends: {"command": "tame", "data": {"target_uuid": "wolf-uuid"}}
  -> SNS: Entity.receive_command(command="tame", target_uuid="wolf-uuid")
    -> Taming.tame(target_uuid="wolf-uuid")
      -> Validate: no companion, target at location, NPC with creature_type, bait in inventory
      -> Consume bait (Entity.destroy())
      -> Roll success chance
      -> Success: write NPC aspect (behavior, master_uuid, loyalty), write Taming aspect
      -> broadcast_to_location(tame event), push_event(result to player)
```

### Companion Tick Loop

```
Step Functions: Call(uuid=companion-uuid, aspect="NPC", action="tick").after(seconds=30)
  -> NPC.tick() -> behavior=="companion" -> _companion()
    -> Load master entity (1 read)
    -> Decay loyalty by base_loyalty_decay
    -> loyalty <= 0: _go_feral(), notify master, clear taming data
    -> Master at same location: reset absence counter, combat assist if attack mode
    -> Master elsewhere + follow mode: _move_to(master.location)
    -> Master elsewhere + stay mode: increment absence, wander after 20 ticks
    -> Save NPC aspect, schedule_next_tick()
```

### Companion Death

```
Companion takes lethal damage
  -> Combat._on_death() fires
  -> Drop carried items at location
  -> Detect behavior=="companion": notify master, clear master.companion_uuid
  -> Entity.destroy() removes companion permanently
  -> Schedule wild creature respawn at spawn location (300s delay, $0.0075)
```

### Player Movement with Companion

```
Player moves north -> entity.location = north_room
[Up to 30 seconds later]
Companion tick -> master.location != companion.location
  -> mode=="follow": _move_to(master.location)
  -> Broadcast: "A loyal wolf trots in."
```

## NPC Integration

### Adding companion behavior to NPC.tick()

Add `elif behavior == "companion": self._companion()` to the tick dispatch in `NPC.tick()`, plus `_companion()`, `_companion_combat()`, and `_go_feral()` methods.

### Marking creatures as tameable

World-generated NPCs need `creature_type` in their NPC aspect data:

```python
npc = npc_entity.aspect("NPC")
npc.data["behavior"] = "hostile"
npc.data["is_npc"] = True
npc.data["creature_type"] = "wolf"  # Makes it tameable
npc._save()
```

NPCs without `creature_type` (guards, merchants) cannot be tamed.

### Companion greeted behavior

The `_companion()` method replaces `_guard()`/`_wander()` and does not call `_check_for_players()`, so companions do not spam greetings at their master.

### Creature population management

When a companion dies, schedule a wild creature respawn at the original spawn location:

```python
Call(tid=str(uuid4()), originator="", uuid="WORLD_SPAWNER",
    aspect="NPC", action="spawn_creature",
    creature_type=creature_type, location=spawn_location
).after(seconds=300)
```

## AI Agent Considerations

### Taming strategy

1. Check `inventory` for bait items matching target creature's `food_tag`
2. Check own `taming_skill` against creature's `min_level`
3. Calculate expected success chance before attempting
4. Higher quality bait increases chance -- prioritize quality over quantity

### Companion management

1. Monitor loyalty via `companion` command
2. Feed when loyalty drops below 50 (wolf needs feeding every ~12.5 minutes at decay 4/minute)
3. Keep food items matching `food_tag` stocked
4. Before combat: `command attack`. After combat: check companion HP, feed if needed.

### Companion selection

- **Wolf** (level 1): low maintenance, 5-item carry, melee. Best first companion.
- **Hawk** (level 3): `scout` reveals adjacent rooms. Critical for exploration.
- **Bear** (level 5): 15-item carry, tank style. Best for resource runs.
- **Fire Elemental** (level 8): `light` for dark areas, magic combat. Highest maintenance (decay 4/tick).

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/taming.py` | Taming aspect class with all commands |
| `backend/aspects/tests/test_taming.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/serverless.yml` | Add `taming` Lambda with SNS filter for `Taming` aspect |
| `backend/aspects/npc.py` | Add `companion` behavior dispatch, `_companion()`, `_companion_combat()`, `_go_feral()` |
| `backend/aspects/combat.py` | Add companion death handling in `_on_death()` |
| `backend/aspects/worldgen/describe.py` | Add `creature_type` field to creature NPCs |

### Implementation order

1. Define `CREATURE_TAMING_TABLE` registry in `taming.py`
2. Create `Taming` class with `tame` command (success/fail mechanic)
3. Add `companion`, `feed`, `name_companion`, `command`, `give_companion` commands
4. Modify `NPC.tick()` to dispatch `"companion"` behavior
5. Implement `_companion()` with loyalty decay, following, combat
6. Implement `_go_feral()` reversion
7. Modify `Combat._on_death()` for companion death handling
8. Add `creature_type` to worldgen creature NPCs
9. Add Lambda + SNS filter to `serverless.yml`
10. Write tests: tame success/fail, loyalty decay, feeding, dismiss, feral reversion, companion death, max-one enforcement, scout, disobedience

## Open Questions

1. **Should companion following be immediate or tick-delayed?** Current: tick-delayed (up to 30s lag). Cheaper but feels sluggish. Immediate following doubles movement write cost. Start with tick-delayed; switch if players complain.

2. **Should companions persist across player sessions?** Current: yes, ticks fire forever. Alternative: freeze ticks on disconnect, saving thousands in Step Functions. But frozen companions never go feral, removing maintenance pressure.

3. **Should companion death be permanent?** Current: yes, entity destroyed. Alternative: companions flee at 0 HP and respawn at rest point. Permanent death creates stakes; resurrection creates forgiveness.

4. **Should there be a recall mechanic?** If a companion is left far away via `stay`, the player must physically travel to it. A `recall` command with cooldown adds convenience but breaks the physical-presence design.

5. **Should companions gain XP and level?** Current: static stats. Companion progression creates investment but risks trivializing combat. If added, cap companion level relative to master.

6. **What happens to companion-carried items on death?** Current: items drop at death location. If companion dies remotely, items are stranded. Should items transfer to master's location instead?

7. **Should taming consume bait on failure?** Current: yes. Creates resource cost per attempt. Alternative: consume only on success. Current is more punishing but more interesting.
