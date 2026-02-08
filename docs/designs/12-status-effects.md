# Status Effects / Conditions Aspect

## What This Brings to the World

Status effects are the connective tissue between every combat-adjacent system in the game. Right now, poison is a list of dicts on the Combat aspect, magic buffs have `duration_ticks` that nobody decrements for players, weather has "narrative only" effects that never touch stats, and equipment bonuses are static numbers that never change dynamically. Each of these systems independently invented its own temporary-state mechanism, and none of them work properly. Status Effects replaces all of them with a single, general-purpose system for applying, tracking, ticking, and removing temporary modifications to entity state.

This is the second-best design in the series after Dialogue Trees, and for a similar reason: it requires minimal new infrastructure while fixing problems that already exist across multiple other systems. The StatusEffects aspect needs one new Lambda, stores data in the existing LOCATION_TABLE, and uses the existing Call.after() mechanism for tick scheduling. But unlike Dialogue Trees (which adds new content), StatusEffects fixes broken content. Player poison that never ticks? Fixed -- StatusEffects schedules its own ticks. Magic buffs that last forever? Fixed -- StatusEffects tracks duration and removes expired effects. The moment this system exists, three other designs (Combat, Magic, Weather) become more correct.

The critical insight is the tick scheduling model. The NPC tick system runs on a per-entity loop: every NPC schedules its next tick via Call.after(). Players do not have NPC aspects, so they do not tick. This means any system that needs periodic processing on player entities has been stuck. StatusEffects solves this by scheduling ticks only for entities that have active effects. No active effects means no ticks, no Step Functions cost, no Lambda invocations. A player who gets poisoned starts ticking; the poison wears off and the ticks stop. This is elegant and cost-efficient because ticks are proportional to active effects, not to total player count.

The risk is combinatorial complexity. Nine effect types with stacking rules, interaction effects (frozen + burning = thawed?), magnitude variations, and duration management create a state space that grows multiplicatively. Every new effect type interacts with every existing one. Every combat action that checks stats must now call `get_effective_stat()` which loads the StatusEffects aspect and iterates active effects. This is a constant-factor increase to every stat-dependent operation in the game, and the constant grows with the number of active effects. The system is architecturally clean but computationally greedy.

## Critical Analysis

**Tick scheduling per affected entity incurs Step Functions cost.** Each entity with active effects gets a recurring tick scheduled via `Call.after(seconds=N)`. Each Step Functions execution costs $0.000025 per state transition. A tick with a 10-second interval means roughly $0.00075 per tick cycle (30 transitions for the delay). With 100 poisoned players, that is 100 concurrent Step Functions executions at $0.075 per tick cycle. If poison lasts 5 ticks, the total cost per mass-poison event is $0.375. This is bounded by effect duration -- when effects expire, ticks stop. But in a world event where a dragon poisons 100 players simultaneously, the burst of 100 Step Functions starts is noticeable. More critically, each tick Lambda invocation loads the entity, loads the StatusEffects aspect, processes all active effects, saves -- that is at minimum 3 DynamoDB reads and 2 writes per tick per entity.

**With 100 poisoned players: 100 tick schedules create bounded but noticeable cost.** The worst case is a sustained scenario: 100 players each with a long-duration effect (e.g., blessed for 30 ticks = 5 minutes at 10-second intervals). That is 100 * 30 * $0.00075 = $2.25 total. Per hour with continuous effect application: $27/hour. This is substantially less than the Procedural Dungeons tick cost ($9,720/month) but still the second-highest recurring cost in the system. The key mitigating factor is that effect durations are bounded -- unlike NPC ticks which run forever, StatusEffects ticks stop when effects expire. Cost is proportional to gameplay intensity, which is architecturally sound.

**Effect data stored in aspect record grows with active effects but is bounded.** Each active effect is a dict with 5-6 fields (~100-200 bytes). An entity with 10 simultaneous effects (the realistic maximum -- you cannot stack much more before they interact destructively) adds ~2KB to the aspect record. This is well within DynamoDB's 400KB item limit. The concern is not storage size but serialization time and iteration cost: every `get_effective_stat()` call must iterate all active effects to compute the aggregate modifier. With 10 effects, this is 10 dict lookups per stat query -- negligible for a single call but multiplicative when Combat checks attack, defense, speed, and magic in a single action (4 stat queries * 10 effects = 40 lookups).

**get_effective_stat() requires loading StatusEffects aspect -- adds 1 DynamoDB read per stat check.** Every aspect that reads a stat must now load the StatusEffects aspect to get the effective value. Combat's `_effective_attack()` currently loads Equipment (1 read). With StatusEffects, it also loads StatusEffects (1 read). A single attack command that checks attacker attack, attacker speed, target defense, and target HP now requires 4 StatusEffects reads (2 for attacker stats, 2 for target stats -- though caching within a Lambda invocation means only 2 reads: one per entity). The caching via `entity._aspect_cache` prevents redundant reads within a single Lambda invocation, but the first access per entity per invocation always hits DynamoDB.

**Combat already has a `status_effects` field -- migration and dedup needed.** The Combat aspect design (doc 01) includes `status_effects: list` that stores poison effects as inline dicts. The StatusEffects aspect introduces a competing system. During migration, existing Combat status effects must be moved to the new StatusEffects aspect, and the Combat `status_effects` field must be deprecated. If both systems coexist, an entity could have poison tracked in Combat AND in StatusEffects, leading to double-ticking (poison damage applied twice per tick). The migration must be atomic per entity: read Combat status_effects, write to StatusEffects, delete from Combat. With put_item and no transactions, a crash between the write and delete would duplicate effects.

**Magic buffs (`stone_wall` with `duration_ticks`) overlap with this system.** The Magic design (doc 04) gives spells like Stone Wall a `duration_ticks: 3` field and says buffs are processed "during tick handler" -- a tick handler that does not exist for players. StatusEffects provides exactly the missing tick handler. But the Magic design stores buff state differently (as a direct stat modifier on the Magic aspect) than StatusEffects would (as an effect entry with type, magnitude, and duration). Unifying requires Magic to apply buffs through `StatusEffects.apply_effect()` instead of directly modifying stats. This changes the Magic aspect's internal design, which means the Magic implementation must be aware of StatusEffects. The dependency flows the wrong direction -- StatusEffects should not require Magic to change, but Magic needs to use StatusEffects.

**Effect stacking rules add combinatorial complexity.** If an entity has both `blessed` (+10% all stats) and `weakened` (attack -50%), how do they combine? Additively (+10% - 50% = -40% attack, +10% other stats)? Multiplicatively (1.1 * 0.5 = 55% attack)? The design must define an evaluation order: positive modifiers first, then negative? Or vice versa? And what about opposing effects: `frozen` (cannot move) + `burning` (HP drain + spread) = thawed (cancel both)? Each interaction rule is a special case. With 9 effect types, there are 36 possible pairs. Not all pairs interact specially, but the ones that do (frozen+burning, blessed+cursed, invisible+burning) need explicit rules. Without these rules, effects simply stack additively, which can produce nonsensical results (simultaneously frozen solid and on fire).

**If the tick Lambda crashes, effects persist past intended duration.** The tick handler decrements `duration_ticks` and removes expired effects. If the Lambda invocation crashes before the save (network error, DynamoDB throttle, Lambda timeout), the duration is not decremented. The next tick (if it fires -- the crash may have prevented scheduling the next one) will retry. But if the crash also prevented scheduling the next tick via Call.after(), the effect persists indefinitely. There is no TTL on individual effects, no background janitor, and no "check effect expiry on next player action" fallback. An entity could be permanently poisoned by a Lambda crash. The mitigation is to store `applied_at` timestamp on each effect and compute remaining duration from wall-clock time rather than tick counts, but this changes the tick-based model to a time-based model.

**This is the SECOND BEST design after Dialogue Trees.** It centralizes scattered temporary-state management (Combat status_effects, Magic duration_ticks, Weather "narrative only" effects) into a single system. It solves the "player ticks" problem that plagues Combat and Magic. It requires minimal new infrastructure (one Lambda, existing table). The cost model is proportional to gameplay activity rather than player count. The main risks (combinatorial complexity, migration from existing systems, tick crash resilience) are all manageable with careful implementation. This system should be implemented before Magic buffs, before Combat status effects get more complex, and before Weather tries to add mechanical effects -- because all three of those systems need this foundation.

## Overview

The StatusEffects aspect provides a general-purpose system for temporary and persistent effects on entities. Effects have a type, magnitude, duration, and source. The aspect manages application, stacking, ticking (periodic processing), stat modification, and removal of effects. It integrates with Combat (poison, burning, weakened from special attacks), Magic (blessed, invisible, frozen from spells), Weather (future: frostbite, heatstroke from extreme conditions), and any future system that needs to temporarily modify entity state. The tick scheduler activates only for entities with active effects, solving the "player ticks" problem.

## Design Principles

**Effects are data, not code.** Each effect type is defined in a registry with base properties: is it stackable, what is the max stack count, does it tick, what stat does it modify. Applying an effect is a data operation (add to list, set duration), not a new method. New effect types are added to the registry, not to the codebase.

**Tick on demand, not on schedule.** Entities without active effects have no ticks scheduled. The first effect applied to a clean entity schedules a tick. The last effect expiring cancels further ticks. This means the system's cost scales with active effects, not with total entities -- a critical property for a serverless architecture where idle resources should cost nothing.

**Centralized stat modification.** Instead of each aspect applying its own stat modifiers (Combat checks its own status_effects, Magic checks its own buffs), all temporary stat modifications route through `get_effective_stat()`. Other aspects call this method instead of reading raw stat values. This creates a single source of truth for "what are this entity's actual stats right now."

**Each aspect owns its data.** StatusEffects stores effect entries, tick state, and last-processed timestamp. It does not store base stats (those belong to Combat, Magic, etc.). It reads base stats from other aspects and returns modified values.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| active_effects | list | [] | List of active effect dicts |
| tick_active | bool | False | Whether a tick loop is scheduled for this entity |
| last_tick_at | int | 0 | Timestamp (epoch seconds) of last tick processing |
| tick_interval | int | 10 | Seconds between ticks (default 10) |
| effects_applied_total | int | 0 | Total effects ever applied (for stats/debugging) |
| effects_expired_total | int | 0 | Total effects that expired naturally |

### Active Effect Schema

Each entry in `active_effects` is a dict:

```python
{
    "effect_type": "poison",          # Registry key
    "magnitude": 3,                   # Strength (damage per tick, stat modifier %, etc.)
    "duration_ticks": 5,              # Ticks remaining (0 = permanent until cured)
    "source_uuid": "snake-entity-uuid",  # Who/what applied this
    "applied_at": 1706500000,         # Epoch timestamp when applied
    "stack_count": 1,                 # Current stack count for stackable effects
    "effect_id": "eff-uuid-1234",     # Unique ID for this effect instance
}
```

### Effect Registry

```python
EFFECT_REGISTRY = {
    "poison": {
        "name": "Poison",
        "description": "Deals damage over time.",
        "tick_effect": "damage",         # What happens each tick
        "stat_modifier": None,           # No passive stat change
        "stackable": True,
        "max_stacks": 5,                 # Up to 5 poison stacks
        "default_duration": 5,           # 5 ticks
        "default_magnitude": 3,          # 3 HP per tick per stack
        "curable": True,
        "cure_items": ["antidote", "cure_potion"],
        "category": "damage_over_time",
    },
    "burning": {
        "name": "Burning",
        "description": "Deals fire damage over time. Can spread to adjacent entities.",
        "tick_effect": "damage",
        "stat_modifier": None,
        "stackable": False,
        "max_stacks": 1,
        "default_duration": 3,
        "default_magnitude": 5,
        "curable": True,
        "cure_items": ["water_flask", "ice_shard"],
        "spread_chance": 0.2,            # 20% chance to spread per tick
        "category": "damage_over_time",
    },
    "frozen": {
        "name": "Frozen",
        "description": "Cannot move. Defense increased, but attack reduced.",
        "tick_effect": None,
        "stat_modifier": {"defense": 1.25, "attack": 0.5},  # Multiplicative
        "stackable": False,
        "max_stacks": 1,
        "default_duration": 3,
        "default_magnitude": 1,
        "curable": True,
        "cure_items": ["fire_shard", "warm_potion"],
        "blocks_movement": True,
        "category": "crowd_control",
        "cancelled_by": ["burning"],     # Fire melts ice
    },
    "blessed": {
        "name": "Blessed",
        "description": "All stats increased by a percentage.",
        "tick_effect": None,
        "stat_modifier": {"attack": 1.10, "defense": 1.10, "magic": 1.10, "hp_regen": 1.10},
        "stackable": False,
        "max_stacks": 1,
        "default_duration": 10,
        "default_magnitude": 10,         # +10%
        "curable": False,                # Positive effect, no reason to cure
        "category": "buff",
        "cancelled_by": ["cursed"],
    },
    "cursed": {
        "name": "Cursed",
        "description": "All stats decreased by a percentage.",
        "tick_effect": None,
        "stat_modifier": {"attack": 0.90, "defense": 0.90, "magic": 0.90},
        "stackable": False,
        "max_stacks": 1,
        "default_duration": 10,
        "default_magnitude": 10,         # -10%
        "curable": True,
        "cure_items": ["holy_water", "blessing_scroll"],
        "category": "debuff",
        "cancelled_by": ["blessed"],
    },
    "invisible": {
        "name": "Invisible",
        "description": "Magically hidden. Functions like stealth but ignores biome modifiers.",
        "tick_effect": None,
        "stat_modifier": None,
        "stackable": False,
        "max_stacks": 1,
        "default_duration": 5,
        "default_magnitude": 80,         # Effective stealth score of 80
        "curable": True,
        "cure_items": ["reveal_dust", "dispel_scroll"],
        "grants_hidden": True,           # Sets Stealth is_hidden if Stealth aspect exists
        "category": "buff",
        "breaks_on_attack": True,
    },
    "stunned": {
        "name": "Stunned",
        "description": "Cannot take any action for the duration.",
        "tick_effect": None,
        "stat_modifier": None,
        "stackable": False,
        "max_stacks": 1,
        "default_duration": 2,
        "default_magnitude": 1,
        "curable": False,                # Must wait it out
        "blocks_actions": True,
        "blocks_movement": True,
        "category": "crowd_control",
    },
    "regenerating": {
        "name": "Regenerating",
        "description": "Restores HP over time.",
        "tick_effect": "heal",
        "stat_modifier": None,
        "stackable": False,
        "max_stacks": 1,
        "default_duration": 5,
        "default_magnitude": 4,          # 4 HP per tick
        "curable": False,                # Positive effect
        "category": "heal_over_time",
    },
    "weakened": {
        "name": "Weakened",
        "description": "Attack power reduced by half.",
        "tick_effect": None,
        "stat_modifier": {"attack": 0.5},
        "stackable": False,
        "max_stacks": 1,
        "default_duration": 5,
        "default_magnitude": 50,         # -50% attack
        "curable": True,
        "cure_items": ["strength_potion", "restoration_scroll"],
        "category": "debuff",
    },
}
```

### Effect Interaction Rules

```python
EFFECT_INTERACTIONS = {
    # (effect_being_applied, existing_effect) -> action
    ("burning", "frozen"): "cancel_both",     # Fire melts ice
    ("frozen", "burning"): "cancel_both",     # Ice quenches fire
    ("blessed", "cursed"): "cancel_both",     # They neutralize
    ("cursed", "blessed"): "cancel_both",     # They neutralize
    ("invisible", "burning"): "cancel_new",   # Can't be invisible while on fire
    ("stunned", "stunned"): "refresh",        # Re-stun refreshes duration
}
```

## Commands

### `status`

```python
@player_command
def status(self) -> dict:
    """View all active status effects and their remaining durations."""
```

**Behavior:**
1. Load active_effects list
2. For each effect, compute remaining ticks and describe the effect
3. Also show effective stat modifiers if any effects are active
4. Return structured data and human-readable summary

```python
def _format_effects(self) -> list:
    """Format active effects for display."""
    formatted = []
    for effect in self.data.get("active_effects", []):
        registry = EFFECT_REGISTRY.get(effect["effect_type"], {})
        ticks_left = effect.get("duration_ticks", 0)
        stacks = effect.get("stack_count", 1)

        entry = {
            "effect_type": effect["effect_type"],
            "name": registry.get("name", effect["effect_type"]),
            "description": registry.get("description", ""),
            "ticks_remaining": ticks_left,
            "magnitude": effect.get("magnitude", 0),
            "stack_count": stacks,
            "source_uuid": effect.get("source_uuid", ""),
            "category": registry.get("category", "unknown"),
        }

        if ticks_left == 0:
            entry["duration_display"] = "permanent"
        else:
            entry["duration_display"] = f"{ticks_left} ticks remaining"

        formatted.append(entry)
    return formatted
```

**Return format:**
```python
{
    "type": "status_effects",
    "active_effects": [
        {
            "effect_type": "poison",
            "name": "Poison",
            "ticks_remaining": 3,
            "magnitude": 3,
            "stack_count": 2,
            "duration_display": "3 ticks remaining",
            "category": "damage_over_time",
            "source_uuid": "snake-uuid",
        },
        {
            "effect_type": "blessed",
            "name": "Blessed",
            "ticks_remaining": 7,
            "magnitude": 10,
            "stack_count": 1,
            "duration_display": "7 ticks remaining",
            "category": "buff",
            "source_uuid": "priest-uuid",
        }
    ],
    "stat_modifiers": {
        "attack": "+10%",
        "defense": "+10%",
    },
    "total_effects": 2,
    "message": "Active effects: Poison x2 (3 ticks, -6 HP/tick), Blessed (7 ticks, +10% all stats)"
}
# No effects:
{
    "type": "status_effects",
    "active_effects": [],
    "stat_modifiers": {},
    "total_effects": 0,
    "message": "You have no active status effects."
}
```

### `cure <effect_type>`

```python
@player_command
def cure(self, effect_type: str) -> dict:
    """Attempt to cure a status effect using an item or spell."""
```

**Validation:**
1. Effect type must exist in the registry
2. Effect must be present in entity's active_effects
3. Effect must be marked as `curable` in the registry
4. Entity must have a cure item in inventory (check Inventory aspect for item with matching tag)

**Behavior:**
1. Look up the effect in the registry to find `cure_items`
2. Search entity's inventory for an item with a matching tag
3. If found: remove the effect from active_effects, consume the cure item
4. If not found: return error explaining what cure is needed
5. If this was the last active effect, cancel the tick schedule
6. Save

```python
def _attempt_cure(self, effect_type: str) -> dict:
    """Try to cure an effect using inventory items."""
    registry = EFFECT_REGISTRY.get(effect_type)
    if not registry:
        return {"type": "error", "message": f"Unknown effect type: {effect_type}"}

    if not registry.get("curable", False):
        return {"type": "error", "message": f"{registry['name']} cannot be cured. It must run its course."}

    # Find the effect in active effects
    active = self.data.get("active_effects", [])
    effect_entry = None
    for e in active:
        if e["effect_type"] == effect_type:
            effect_entry = e
            break

    if not effect_entry:
        return {"type": "error", "message": f"You are not affected by {registry['name']}."}

    # Check for cure items in inventory
    cure_tags = registry.get("cure_items", [])
    cure_item_uuid = None
    cure_item_name = None

    try:
        for item_uuid in self.entity.contents:
            try:
                item = Entity(uuid=item_uuid)
                item_inv = item.aspect("Inventory")
                item_tags = item_inv.data.get("tags", [])
                for tag in cure_tags:
                    if tag in item_tags:
                        cure_item_uuid = item_uuid
                        cure_item_name = item.name
                        break
                if cure_item_uuid:
                    break
            except (KeyError, ValueError):
                continue
    except Exception:
        pass

    if not cure_item_uuid:
        cure_names = ", ".join(cure_tags)
        return {
            "type": "error",
            "message": f"You need one of [{cure_names}] to cure {registry['name']}."
        }

    # Remove the effect
    active = [e for e in active if e["effect_type"] != effect_type]
    self.data["active_effects"] = active
    self.data["effects_expired_total"] = self.data.get("effects_expired_total", 0) + 1

    # Consume the cure item
    try:
        cure_entity = Entity(uuid=cure_item_uuid)
        cure_entity.destroy()
    except (KeyError, Exception):
        pass

    # If no more effects, stop ticking
    if not active:
        self.data["tick_active"] = False

    self._save()

    return {
        "type": "cure_confirm",
        "effect_cured": effect_type,
        "effect_name": registry["name"],
        "item_used": cure_item_name,
        "remaining_effects": len(active),
        "message": f"You use the {cure_item_name} to cure {registry['name']}."
    }
```

**Return format:**
```python
# Success:
{
    "type": "cure_confirm",
    "effect_cured": "poison",
    "effect_name": "Poison",
    "item_used": "antidote",
    "remaining_effects": 1,
    "message": "You use the antidote to cure Poison."
}
# Missing cure item:
{
    "type": "error",
    "message": "You need one of [antidote, cure_potion] to cure Poison."
}
# Not curable:
{
    "type": "error",
    "message": "Stunned cannot be cured. It must run its course."
}
```

## Core Methods (Internal API)

### `apply_effect` (callable from other aspects)

```python
@callable
def apply_effect(
    self,
    effect_type: str,
    magnitude: int = 0,
    duration_ticks: int = 0,
    source_uuid: str = "",
) -> dict:
    """Apply a status effect to this entity. Called by other aspects."""
```

This is the primary integration point. Other aspects call this to apply effects:

```python
def _apply_effect_internal(
    self, effect_type: str, magnitude: int, duration_ticks: int, source_uuid: str
) -> dict:
    """Internal effect application logic."""
    registry = EFFECT_REGISTRY.get(effect_type)
    if not registry:
        return {"type": "error", "message": f"Unknown effect type: {effect_type}"}

    if magnitude == 0:
        magnitude = registry.get("default_magnitude", 1)
    if duration_ticks == 0:
        duration_ticks = registry.get("default_duration", 5)

    active = self.data.get("active_effects", [])

    # Check interaction rules
    for existing in list(active):
        interaction_key = (effect_type, existing["effect_type"])
        interaction = EFFECT_INTERACTIONS.get(interaction_key)
        if interaction == "cancel_both":
            # Remove existing, do not apply new
            active = [e for e in active if e["effect_type"] != existing["effect_type"]]
            self.data["active_effects"] = active
            self._save()

            # Notify entity
            if self.entity:
                existing_name = EFFECT_REGISTRY.get(
                    existing["effect_type"], {}
                ).get("name", existing["effect_type"])
                new_name = registry.get("name", effect_type)
                self.entity.push_event({
                    "type": "effect_cancelled",
                    "cancelled": existing_name,
                    "by": new_name,
                    "message": f"{new_name} and {existing_name} cancel each other out!"
                })
            return {
                "type": "effect_cancelled",
                "cancelled": existing["effect_type"],
                "by": effect_type,
            }
        elif interaction == "cancel_new":
            if self.entity:
                self.entity.push_event({
                    "type": "effect_resisted",
                    "effect": effect_type,
                    "message": f"{registry['name']} has no effect -- blocked by {EFFECT_REGISTRY.get(existing['effect_type'], {}).get('name', '')}."
                })
            return {"type": "effect_resisted", "effect": effect_type}
        elif interaction == "refresh":
            # Refresh duration of existing
            existing["duration_ticks"] = duration_ticks
            self.data["active_effects"] = active
            self._save()
            return {"type": "effect_refreshed", "effect": effect_type}

    # Check stacking
    existing_effect = None
    for e in active:
        if e["effect_type"] == effect_type:
            existing_effect = e
            break

    if existing_effect:
        if registry.get("stackable", False):
            max_stacks = registry.get("max_stacks", 1)
            if existing_effect.get("stack_count", 1) < max_stacks:
                existing_effect["stack_count"] = existing_effect.get("stack_count", 1) + 1
                existing_effect["duration_ticks"] = max(
                    existing_effect["duration_ticks"], duration_ticks
                )
                self.data["active_effects"] = active
            else:
                # At max stacks, just refresh duration
                existing_effect["duration_ticks"] = max(
                    existing_effect["duration_ticks"], duration_ticks
                )
        else:
            # Not stackable -- refresh duration if longer
            existing_effect["duration_ticks"] = max(
                existing_effect["duration_ticks"], duration_ticks
            )
            existing_effect["magnitude"] = max(
                existing_effect["magnitude"], magnitude
            )
    else:
        # New effect
        import time as time_module
        from uuid import uuid4 as gen_uuid

        new_effect = {
            "effect_type": effect_type,
            "magnitude": magnitude,
            "duration_ticks": duration_ticks,
            "source_uuid": source_uuid,
            "applied_at": int(time_module.time()),
            "stack_count": 1,
            "effect_id": str(gen_uuid()),
        }
        active.append(new_effect)
        self.data["active_effects"] = active

    self.data["effects_applied_total"] = self.data.get("effects_applied_total", 0) + 1

    # Schedule tick if not already running
    if not self.data.get("tick_active", False):
        self._schedule_tick()
        self.data["tick_active"] = True

    # Handle special effect properties
    if registry.get("grants_hidden", False) and self.entity:
        try:
            if "Stealth" in self.entity.data.get("aspects", []):
                stealth = self.entity.aspect("Stealth")
                stealth.data["is_hidden"] = True
                stealth.data["current_stealth_score"] = magnitude
                stealth._save()
        except (ValueError, KeyError):
            pass

    self._save()

    # Notify entity
    if self.entity:
        self.entity.push_event({
            "type": "effect_applied",
            "effect": effect_type,
            "name": registry.get("name", effect_type),
            "magnitude": magnitude,
            "duration_ticks": duration_ticks,
            "source_uuid": source_uuid,
            "message": self._effect_applied_message(effect_type, magnitude, source_uuid),
        })

    # Broadcast to location
    if self.entity and self.entity.location:
        self.entity.broadcast_to_location(
            self.entity.location,
            {
                "type": "effect_visible",
                "target": self.entity.name,
                "target_uuid": self.entity.uuid,
                "effect": effect_type,
                "message": self._effect_visible_message(effect_type),
            },
        )

    return {
        "type": "effect_applied",
        "effect": effect_type,
        "magnitude": magnitude,
        "duration_ticks": duration_ticks,
    }


def _effect_applied_message(self, effect_type: str, magnitude: int, source: str) -> str:
    """Generate a message for the affected entity."""
    messages = {
        "poison": f"You feel venom coursing through your veins! (-{magnitude} HP/tick)",
        "burning": f"Flames engulf you! (-{magnitude} HP/tick)",
        "frozen": "Ice encases your body! You cannot move.",
        "blessed": f"A warm light surrounds you. (+{magnitude}% all stats)",
        "cursed": f"A dark shadow falls over you. (-{magnitude}% all stats)",
        "invisible": "You fade from sight.",
        "stunned": "Your vision swims. You cannot act!",
        "regenerating": f"Healing energy flows through you. (+{magnitude} HP/tick)",
        "weakened": "Your arms feel heavy. Attack power reduced.",
    }
    return messages.get(effect_type, f"You are affected by {effect_type}.")


def _effect_visible_message(self, effect_type: str) -> str:
    """Generate a message visible to observers."""
    messages = {
        "poison": f"{self.entity.name} looks sickly and pale.",
        "burning": f"Flames lick at {self.entity.name}!",
        "frozen": f"{self.entity.name} is encased in ice!",
        "blessed": f"A golden light surrounds {self.entity.name}.",
        "cursed": f"A dark aura clings to {self.entity.name}.",
        "invisible": f"{self.entity.name} fades from view.",
        "stunned": f"{self.entity.name} staggers, dazed.",
        "regenerating": f"A soft glow emanates from {self.entity.name}.",
        "weakened": f"{self.entity.name} appears weakened.",
    }
    return messages.get(effect_type, f"{self.entity.name} is affected by something.")
```

### `get_effective_stat` (called by other aspects)

```python
def get_effective_stat(self, stat_name: str, base_value: int) -> int:
    """Compute the effective value of a stat after all active effects.

    Args:
        stat_name: The stat to modify (e.g., "attack", "defense", "magic").
        base_value: The raw stat value before effects.

    Returns:
        The modified stat value.
    """
    multiplier = 1.0
    flat_bonus = 0

    for effect in self.data.get("active_effects", []):
        registry = EFFECT_REGISTRY.get(effect["effect_type"], {})
        stat_mods = registry.get("stat_modifier")
        if not stat_mods:
            continue
        if stat_name in stat_mods:
            mod = stat_mods[stat_name]
            if isinstance(mod, float) and mod != 0:
                # Multiplicative modifier
                stacks = effect.get("stack_count", 1)
                multiplier *= mod ** stacks

    effective = int(base_value * multiplier) + flat_bonus
    return max(0, effective)
```

### `tick` (scheduled processing)

```python
@callable
def tick(self) -> dict:
    """Process all active effects: apply tick damage/healing, decrement durations, remove expired."""
```

```python
def _process_tick(self) -> dict:
    """Process one tick of all active effects."""
    import time as time_module

    active = self.data.get("active_effects", [])
    if not active:
        self.data["tick_active"] = False
        self._save()
        return {"type": "tick_complete", "effects_remaining": 0}

    tick_results = []
    expired = []
    remaining = []

    for effect in active:
        effect_type = effect["effect_type"]
        registry = EFFECT_REGISTRY.get(effect_type, {})
        magnitude = effect.get("magnitude", 0)
        stacks = effect.get("stack_count", 1)

        # Process tick effect (damage, heal)
        tick_effect = registry.get("tick_effect")
        if tick_effect == "damage":
            total_damage = magnitude * stacks
            self._apply_tick_damage(total_damage, effect_type)
            tick_results.append({
                "effect": effect_type,
                "action": "damage",
                "amount": total_damage,
            })
        elif tick_effect == "heal":
            total_heal = magnitude * stacks
            self._apply_tick_heal(total_heal)
            tick_results.append({
                "effect": effect_type,
                "action": "heal",
                "amount": total_heal,
            })

        # Handle burning spread
        if registry.get("spread_chance") and self.entity and self.entity.location:
            import random
            if random.random() < registry["spread_chance"]:
                self._try_spread_burning(effect)

        # Decrement duration
        if effect["duration_ticks"] > 0:
            effect["duration_ticks"] -= 1
            if effect["duration_ticks"] <= 0:
                expired.append(effect)
                tick_results.append({
                    "effect": effect_type,
                    "action": "expired",
                })
            else:
                remaining.append(effect)
        else:
            # Permanent effect (duration_ticks == 0 means permanent)
            remaining.append(effect)

    # Remove expired effects
    for effect in expired:
        self.data["effects_expired_total"] = (
            self.data.get("effects_expired_total", 0) + 1
        )
        # Handle invisible expiry
        registry = EFFECT_REGISTRY.get(effect["effect_type"], {})
        if registry.get("grants_hidden", False) and self.entity:
            try:
                if "Stealth" in self.entity.data.get("aspects", []):
                    stealth = self.entity.aspect("Stealth")
                    stealth.data["is_hidden"] = False
                    stealth.data["current_stealth_score"] = 0
                    stealth._save()
            except (ValueError, KeyError):
                pass

    self.data["active_effects"] = remaining
    self.data["last_tick_at"] = int(time_module.time())

    # Notify entity of tick results
    if self.entity and tick_results:
        self.entity.push_event({
            "type": "status_tick",
            "results": tick_results,
            "active_effects": len(remaining),
            "message": self._tick_message(tick_results),
        })

    # Schedule next tick or stop
    if remaining:
        self._schedule_tick()
    else:
        self.data["tick_active"] = False

    self._save()
    return {"type": "tick_complete", "effects_remaining": len(remaining)}


def _apply_tick_damage(self, damage: int, source_effect: str):
    """Apply tick damage through Combat aspect."""
    if not self.entity:
        return
    try:
        combat = self.entity.aspect("Combat")
        combat.data["hp"] = combat.data.get("hp", 0) - damage
        if combat.data["hp"] <= 0:
            combat.data["hp"] = 0
            # Trigger death via Combat
            Call(
                tid=str(uuid4()),
                originator=self.entity.uuid,
                uuid=self.entity.uuid,
                aspect="Combat",
                action="on_death",
                killer_uuid=self.data.get("active_effects", [{}])[0].get("source_uuid", ""),
            ).now()
        combat._save()
    except (ValueError, KeyError):
        pass


def _apply_tick_heal(self, amount: int):
    """Apply tick healing through Combat aspect."""
    if not self.entity:
        return
    try:
        combat = self.entity.aspect("Combat")
        max_hp = combat.data.get("max_hp", 20)
        combat.data["hp"] = min(max_hp, combat.data.get("hp", 0) + amount)
        combat._save()
    except (ValueError, KeyError):
        pass


def _try_spread_burning(self, effect: dict):
    """Attempt to spread burning to a random adjacent entity."""
    try:
        loc_entity = Entity(uuid=self.entity.location)
        for entity_uuid in loc_entity.contents:
            if entity_uuid == self.entity.uuid:
                continue
            try:
                other = Entity(uuid=entity_uuid)
                if "StatusEffects" not in other.data.get("aspects", []):
                    continue
                other_effects = other.aspect("StatusEffects")
                # Don't re-apply if already burning
                already_burning = any(
                    e["effect_type"] == "burning"
                    for e in other_effects.data.get("active_effects", [])
                )
                if already_burning:
                    continue
                # Spread!
                other_effects.apply_effect(
                    effect_type="burning",
                    magnitude=effect["magnitude"],
                    duration_ticks=2,  # Spread fire is shorter
                    source_uuid=self.entity.uuid,
                )
                return  # Spread to one entity per tick
            except (KeyError, ValueError):
                continue
    except (KeyError, Exception):
        pass


def _schedule_tick(self):
    """Schedule the next status effect tick via Step Functions."""
    if not self.entity:
        return
    interval = self.data.get("tick_interval", 10)
    Call(
        tid=str(uuid4()),
        originator=self.entity.uuid,
        uuid=self.entity.uuid,
        aspect="StatusEffects",
        action="tick",
    ).after(seconds=interval)


def _tick_message(self, results: list) -> str:
    """Generate a human-readable tick summary."""
    parts = []
    for r in results:
        registry = EFFECT_REGISTRY.get(r["effect"], {})
        name = registry.get("name", r["effect"])
        if r["action"] == "damage":
            parts.append(f"{name}: -{r['amount']} HP")
        elif r["action"] == "heal":
            parts.append(f"{name}: +{r['amount']} HP")
        elif r["action"] == "expired":
            parts.append(f"{name} wore off")
    return " | ".join(parts)
```

## Cross-Aspect Interactions

### StatusEffects + Combat (effective stats and applying effects)

Combat uses `get_effective_stat` for all stat computations:

```python
# Modified Combat._effective_attack():
def _effective_attack(self) -> int:
    base = self.data.get("attack", 5)
    # Equipment bonus
    try:
        equip = self.entity.aspect("Equipment")
        base += equip.data.get("stat_bonuses", {}).get("attack", 0)
    except (ValueError, KeyError):
        pass
    # Status effect modifiers
    try:
        if "StatusEffects" in self.entity.data.get("aspects", []):
            effects = self.entity.aspect("StatusEffects")
            base = effects.get_effective_stat("attack", base)
    except (ValueError, KeyError):
        pass
    return max(1, base)

# Modified Combat._effective_defense():
def _effective_defense(self) -> int:
    base = self.data.get("defense", 2)
    try:
        equip = self.entity.aspect("Equipment")
        base += equip.data.get("stat_bonuses", {}).get("defense", 0)
    except (ValueError, KeyError):
        pass
    try:
        if "StatusEffects" in self.entity.data.get("aspects", []):
            effects = self.entity.aspect("StatusEffects")
            base = effects.get_effective_stat("defense", base)
    except (ValueError, KeyError):
        pass
    return max(0, base)
```

Combat applies effects via special attacks:

```python
# In Combat.attack(), after damage calculation:
def _apply_combat_effects(self, attacker: Entity, target: Entity, weapon_tags: list):
    """Apply status effects from combat (poison weapons, fire attacks, etc.)."""
    if "StatusEffects" not in target.data.get("aspects", []):
        return

    target_effects = target.aspect("StatusEffects")

    # Poison weapon tag
    if "poisoned" in weapon_tags:
        target_effects.apply_effect(
            effect_type="poison",
            magnitude=2,
            duration_ticks=3,
            source_uuid=attacker.uuid,
        )

    # Fire weapon tag
    if "flaming" in weapon_tags:
        target_effects.apply_effect(
            effect_type="burning",
            magnitude=4,
            duration_ticks=2,
            source_uuid=attacker.uuid,
        )
```

### StatusEffects + Magic (spell-applied effects)

Magic spells apply effects through the StatusEffects system instead of managing their own buff state:

```python
# In Magic._resolve_spell(), for buff/debuff spells:
def _apply_spell_effect(self, spell_def: dict, target_uuid: str = "") -> dict:
    """Apply a spell's status effect through the StatusEffects aspect."""
    target = self.entity if not target_uuid else Entity(uuid=target_uuid)

    if "StatusEffects" not in target.data.get("aspects", []):
        return {"type": "error", "message": "Target cannot receive status effects."}

    effects_aspect = target.aspect("StatusEffects")

    # Map spell effects to StatusEffects types
    spell_to_effect = {
        "stone_wall": ("blessed", {"attack": 1.0, "defense": 1.25}),  # Defense only
        "fog_cloud": ("invisible", 60),  # High stealth score
        "lightning_stun": ("stunned", 1),
        "flame_touch": ("burning", 5),
        "frost_bolt": ("frozen", 1),
        "divine_blessing": ("blessed", 10),
        "shadow_curse": ("cursed", 10),
        "nature_regen": ("regenerating", 4),
    }

    effect_mapping = spell_to_effect.get(spell_def.get("spell_effect_id"))
    if effect_mapping:
        effect_type, magnitude = effect_mapping
        if isinstance(magnitude, dict):
            # Custom stat modifiers handled by the effect itself
            magnitude = spell_def.get("base_power", 5)

        return effects_aspect.apply_effect(
            effect_type=effect_type,
            magnitude=magnitude if isinstance(magnitude, int) else 1,
            duration_ticks=spell_def.get("duration_ticks", 5),
            source_uuid=self.entity.uuid,
        )

    return {"type": "error", "message": "Spell has no effect mapping."}
```

### StatusEffects + Movement (frozen blocks movement)

The `frozen` and `stunned` effects block movement:

```python
# In Land.move(), before processing movement:
def _check_movement_blocks(self) -> dict:
    """Check if any status effects prevent movement."""
    if not self.entity:
        return None
    try:
        if "StatusEffects" not in self.entity.data.get("aspects", []):
            return None
        effects = self.entity.aspect("StatusEffects")
        for effect in effects.data.get("active_effects", []):
            registry = EFFECT_REGISTRY.get(effect["effect_type"], {})
            if registry.get("blocks_movement", False):
                name = registry.get("name", effect["effect_type"])
                ticks = effect.get("duration_ticks", 0)
                return {
                    "type": "error",
                    "message": f"You cannot move -- you are {name}! ({ticks} ticks remaining)"
                }
    except (ValueError, KeyError):
        pass
    return None
```

### StatusEffects + Command Dispatch (stunned blocks actions)

The `stunned` effect blocks all commands:

```python
# In Entity.receive_command(), before dispatching:
def _check_action_blocks(self) -> dict:
    """Check if any status effects prevent all actions."""
    try:
        if "StatusEffects" not in self.data.get("aspects", []):
            return None
        effects = self.aspect("StatusEffects")
        for effect in effects.data.get("active_effects", []):
            registry = EFFECT_REGISTRY.get(effect["effect_type"], {})
            if registry.get("blocks_actions", False):
                name = registry.get("name", effect["effect_type"])
                ticks = effect.get("duration_ticks", 0)
                return {
                    "type": "error",
                    "message": f"You are {name} and cannot act! ({ticks} ticks remaining)"
                }
    except (ValueError, KeyError):
        pass
    return None
```

### StatusEffects + Stealth (invisible effect)

The `invisible` effect interacts with the Stealth aspect:

```python
# When invisible is applied:
# -> Sets Stealth.is_hidden = True with high stealth score
# -> Breaks on attack (like regular stealth)
# -> Ignores biome modifiers (magical concealment)

# When invisible expires (in tick processing):
# -> Sets Stealth.is_hidden = False
# -> Resets current_stealth_score to 0
# -> Broadcasts reveal to location
```

### StatusEffects + Inventory (cure items)

Cure items are regular inventory entities with specific tags:

```python
# Example cure items created during world generation:
{
    "name": "antidote",
    "tags": ["antidote", "consumable", "cure"],
    "description": "A small vial of green liquid that neutralizes poison.",
    "weight": 1,
}
{
    "name": "fire shard",
    "tags": ["fire_shard", "consumable", "cure"],
    "description": "A warm crystal that melts ice on contact.",
    "weight": 1,
}
{
    "name": "holy water",
    "tags": ["holy_water", "consumable", "cure"],
    "description": "Blessed water that dispels dark magic.",
    "weight": 1,
}
```

## Event Flow

### Effect Application (from Combat)

```
Player attacks with poisoned weapon
  -> Combat.attack() calculates damage, applies to target
  -> Combat._apply_combat_effects()
    -> target_effects = target.aspect("StatusEffects")
    -> target_effects.apply_effect(effect_type="poison", magnitude=2, duration_ticks=3)
      -> Check interaction rules (no conflicts)
      -> Check stacking (add stack if < max)
      -> Add/update effect in active_effects
      -> Schedule tick if not already running: Call.after(seconds=10)
      -> push_event(effect_applied to target)
      -> broadcast_to_location(effect_visible)
      -> Save StatusEffects aspect
```

### Tick Processing

```
Call.after(seconds=10) fires
  -> StatusEffects.tick()
    -> For each active effect:
      -> If tick_effect == "damage": apply damage via Combat aspect
      -> If tick_effect == "heal": apply heal via Combat aspect
      -> Decrement duration_ticks
      -> If duration_ticks <= 0: mark for removal
      -> If "burning" and spread_chance: maybe spread to adjacent entity
    -> Remove expired effects
    -> push_event(status_tick with results)
    -> If effects remaining: schedule next tick
    -> If no effects: set tick_active = False, stop scheduling
    -> Save
```

### Cure Sequence

```
Player sends: {"command": "cure", "data": {"effect_type": "poison"}}
  -> Entity.receive_command(command="cure")
    -> StatusEffects.cure(effect_type="poison")
      -> Validate: effect exists, is curable
      -> Search entity inventory for cure item (tag in cure_items list)
      -> If found: remove effect, destroy cure item
      -> If last effect removed: stop tick schedule
      -> push_event(cure_confirm)
      -> Save
```

### Effect Interaction (Frozen + Burning)

```
Entity is frozen (has frozen in active_effects)
  -> Burning is applied (fire spell or flaming weapon)
    -> apply_effect checks EFFECT_INTERACTIONS: ("burning", "frozen") -> "cancel_both"
    -> Remove frozen from active_effects
    -> Do NOT add burning
    -> push_event(effect_cancelled: "Burning and Frozen cancel each other out!")
    -> If no effects remaining: stop tick schedule
```

### Stat Check with Effects

```
Combat.attack() needs attacker's effective attack
  -> Combat._effective_attack()
    -> base = self.data["attack"] (e.g., 10)
    -> equipment bonus: +3 from sword
    -> StatusEffects.get_effective_stat("attack", 13)
      -> Iterate active_effects
      -> "blessed": attack multiplier 1.10 -> 13 * 1.10 = 14.3 -> 14
      -> "weakened": attack multiplier 0.5 -> but wait, entity has both blessed and weakened
        -> blessed cancels cursed, not weakened
        -> 13 * 1.10 * 0.5 = 7.15 -> 7
      -> Return 7
    -> Effective attack = 7
```

## NPC Integration

### NPCs with StatusEffects

Any NPC with combat capabilities can receive status effects. During NPC creation:

```python
# Creating an NPC that can be poisoned, burned, etc.:
enemy = Entity()
enemy.data["aspects"] = ["NPC", "Combat", "StatusEffects"]
enemy.data["primary_aspect"] = "NPC"
enemy.data["name"] = "Venomous Spider"
enemy._save()

combat = enemy.aspect("Combat")
combat.data["hp"] = 20
combat.data["attack"] = 6
combat.data["defense"] = 1
combat._save()

# StatusEffects aspect is created lazily -- no data needed at creation
```

### NPC effect application

Hostile NPCs with special attack types apply effects:

```python
# In NPC._seek_and_attack(), special attack types:
def _special_attack(self, target_uuid: str):
    """NPC applies a special attack with status effect."""
    npc_type = self.data.get("npc_type", "")
    target = Entity(uuid=target_uuid)

    if "StatusEffects" not in target.data.get("aspects", []):
        return

    target_effects = target.aspect("StatusEffects")

    special_attacks = {
        "venomous_spider": ("poison", 3, 4),  # 3 damage, 4 ticks
        "fire_elemental": ("burning", 5, 3),
        "ice_wraith": ("frozen", 1, 2),
        "shadow_priest": ("cursed", 10, 8),
        "berserker": ("weakened", 50, 3),      # Weakening strike
    }

    attack_data = special_attacks.get(npc_type)
    if attack_data:
        effect_type, magnitude, duration = attack_data
        target_effects.apply_effect(
            effect_type=effect_type,
            magnitude=magnitude,
            duration_ticks=duration,
            source_uuid=self.entity.uuid,
        )
```

### NPC behavior modification from effects

NPCs affected by status effects should change behavior:

```python
# In NPC.tick(), check for blocking effects:
def tick(self):
    """Execute behavior, respecting status effects."""
    # Check if stunned or frozen
    if "StatusEffects" in self.entity.data.get("aspects", []):
        effects = self.entity.aspect("StatusEffects")
        for effect in effects.data.get("active_effects", []):
            registry = EFFECT_REGISTRY.get(effect["effect_type"], {})
            if registry.get("blocks_actions", False):
                # NPC is stunned -- skip this tick
                self.entity.schedule_next_tick()
                return
            if registry.get("blocks_movement", False):
                # NPC is frozen -- can still attack but not move
                self._attack_only()
                self.entity.schedule_next_tick()
                return

    # Normal behavior
    behavior = self.data.get("behavior", "wander")
    # ... (existing behavior logic)
```

### Boss NPCs with effect resistance

Boss NPCs can have reduced effect durations or be immune to certain effects:

```python
# Boss NPC data:
{
    "npc_type": "dragon_boss",
    "effect_resistance": {
        "stunned": "immune",         # Cannot be stunned
        "frozen": "immune",          # Cannot be frozen (fire dragon)
        "poison": 0.5,               # Poison lasts half duration
        "weakened": 0.75,            # Weakened lasts 75% duration
    }
}

# In StatusEffects.apply_effect(), check target resistance:
def _check_resistance(self, effect_type: str) -> float:
    """Check if entity has resistance to an effect type."""
    try:
        npc = self.entity.aspect("NPC")
        resistances = npc.data.get("effect_resistance", {})
        resistance = resistances.get(effect_type, 1.0)
        if resistance == "immune":
            return 0.0
        return resistance
    except (ValueError, KeyError):
        return 1.0  # No resistance
```

## AI Agent Considerations

### Effect awareness

AI agents receive structured status effect events that enable tactical decision-making:

```json
{
    "type": "effect_applied",
    "effect": "poison",
    "name": "Poison",
    "magnitude": 3,
    "duration_ticks": 5,
    "message": "You feel venom coursing through your veins! (-3 HP/tick)"
}
```

```json
{
    "type": "status_tick",
    "results": [
        {"effect": "poison", "action": "damage", "amount": 6},
        {"effect": "regenerating", "action": "heal", "amount": 4}
    ],
    "active_effects": 2,
    "message": "Poison: -6 HP | Regenerating: +4 HP"
}
```

### Decision-making with effects

An AI agent's effect management loop:

1. After taking damage: check `status` for active effects
2. If poisoned and have antidote: `cure poison` immediately
3. If health low and poisoned without antidote: `flee` and find a merchant
4. Before entering combat: check for beneficial effects (blessed, regenerating)
5. If no buffs available: consider casting buff spells before engaging
6. Track effect durations to know when debuffs will expire naturally
7. Prioritize curing effects that block actions (stunned) or movement (frozen) -- though stunned cannot be cured, knowing its duration enables planning

### Effect-aware combat planning

```
1. status -> check active effects
2. If weakened: avoid combat until it expires
3. If blessed: seek combat to maximize the buff window
4. If regenerating: fight more aggressively (HP is recovering)
5. If frozen: use ranged attacks (spells) since movement is blocked
6. Track enemy effects from broadcast events to time attacks
   (e.g., attack when enemy is weakened or stunned)
```

### Cure item inventory management

AI agents should:
1. Maintain a supply of antidotes and cure items
2. Buy cure items from merchants during safe periods
3. Prioritize cure items over general inventory when heading into dangerous areas
4. Know which cure items counter which effects (structured in `cure_items` field)

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/status_effects.py` | StatusEffects aspect class with effect registry, tick system, apply/cure/status commands |
| `backend/aspects/tests/test_status_effects.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/serverless.yml` | Add `status_effects` Lambda with SNS filter for `StatusEffects` aspect |
| `backend/aspects/combat.py` | Replace inline `status_effects` list with calls to StatusEffects aspect; modify `_effective_attack()` and `_effective_defense()` to call `get_effective_stat()` |
| `backend/aspects/magic.py` | Apply buff/debuff spells through StatusEffects instead of direct stat modification; remove `duration_ticks` handling from Magic |
| `backend/aspects/land.py` | Add movement block check for frozen/stunned effects in `move()` |
| `backend/aspects/npc.py` | Add effect-aware behavior in `tick()` (skip tick if stunned, attack-only if frozen); add special attack effects for typed NPCs |
| `backend/aspects/thing.py` | Add action block check in `receive_command()` for stunned effect |

### Migration steps for existing systems

| System | Migration |
|--------|-----------|
| Combat `status_effects` field | Deprecate. Read existing effects on first StatusEffects access, migrate to new format, clear old field. |
| Magic `duration_ticks` on buffs | Route through StatusEffects.apply_effect(). Remove tick handling from Magic. |
| Weather "narrative only" effects | Future: add Weather -> StatusEffects integration for frostbite/heatstroke. No migration needed. |

### Implementation order

1. Create `status_effects.py` with StatusEffects class, effect registry, and interaction rules
2. Implement `apply_effect()` with stacking, interactions, and tick scheduling
3. Implement `tick()` with damage/heal processing, duration management, expiry
4. Implement `get_effective_stat()` for stat modification queries
5. Implement `status` and `cure` player commands
6. Add Lambda + SNS filter to serverless.yml
7. Modify Combat to use `get_effective_stat()` and apply effects via StatusEffects
8. Modify Magic to apply buffs/debuffs through StatusEffects
9. Modify Land.move() for frozen/stunned movement blocks
10. Modify Entity.receive_command() for stunned action blocks
11. Add NPC special attacks that apply effects
12. Write tests (apply, stack, interact, tick, cure, stat modification, movement block, expiry)

## Open Questions

1. **Should effect durations be tick-based or time-based?** Tick-based (current design) is simpler and integrates with the existing Step Functions model. Time-based (compute remaining from `applied_at` + duration_seconds) is more resilient to tick failures. A hybrid approach -- tick-based with a fallback time check -- would be most robust but adds complexity.

2. **How should effect resistance work for players?** The design includes boss NPC resistance via `effect_resistance` on the NPC aspect. Should players gain resistance through equipment, level, or a dedicated resistance stat? Adding resistance to players means every `apply_effect` call must check player resistance, which adds another cross-aspect read.

3. **Should there be an `effect_limit` per entity?** Currently an entity can have up to one of each non-stackable effect and up to `max_stacks` of each stackable effect. With 9 effect types, the theoretical maximum is 9 + (5-1) * number_of_stackable_types active effects. Should there be a hard cap (e.g., max 10 active effects) to bound computation cost?

4. **Tick interval tuning.** 10-second ticks are frequent enough for combat relevance (poison ticking every 10 seconds during a fight) but may be too frequent for out-of-combat effects (blessed lasting 10 ticks = 100 seconds feels short). Should different effect categories have different tick intervals? Fast ticks for damage-over-time, slow ticks for buffs?

5. **Effect persistence through death.** When an entity dies and respawns, should effects clear? The Combat design clears `status_effects` on respawn, which suggests yes. But some effects (blessed by a quest NPC, cursed by a powerful enemy) might narratively persist through death. Define a `persists_through_death` flag per effect type?

6. **Should effects be visible to other players?** Currently, `effect_visible` broadcasts when an effect is applied. But should `look` at an entity show their active effects? Seeing "a player wreathed in flames" (burning) or "a player glowing with golden light" (blessed) adds atmospheric detail but leaks tactical information. Option: show effects on look but only with descriptive text, not numerical details.

7. **PvP effect application.** If a player casts a curse on another player, should PvP opt-in be required (like Combat's `pvp_enabled`)? Or should debuff spells work on any entity? Allowing debuffs without PvP consent creates griefing potential (perma-cursing someone). Require PvP for negative effects, allow positive effects (blessed, regenerating) on any willing target?
