# Magic/Spells Aspect

## Overview

The Magic aspect adds a mana pool, spell book, and spell casting to entities. Spells have elemental affinities (fire, water, earth, air, shadow, light) that interact with biomes -- fire spells are stronger in deserts, weaker in swamps. Spells consume mana, which regenerates over time via the tick system. Magic integrates with Combat (damage spells), Land (biome affinity), Equipment (enchanted items), and Inventory (spell scrolls, reagents).

## Design Principles

**Biome matters.** The worldgen system assigns biomes to every location. Magic leverages this existing data -- a spell's effectiveness scales with biome affinity. This makes geography strategically meaningful beyond just navigation.

**Mana as a resource.** Unlike combat attacks (unlimited), spells cost mana. Mana regenerates slowly via ticks, creating a strategic tension: cast a powerful spell now or save mana for later. This encourages diverse play (mix combat and magic) rather than spell-spam.

**Spells are data.** Spell definitions are JSON with element, cost, effect type, and base power. Adding a new spell is a data entry, not a new method. The `cast` command resolves any spell by looking up its definition and applying the appropriate effect handler.

**Each aspect owns its data.** Magic stores mana, known_spells, and elemental_affinity in its aspect record. Spell effects that touch other aspects (damage to Combat, items to Inventory) use explicit cross-aspect access.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| mana | int | 20 | Current mana |
| max_mana | int | 20 | Maximum mana pool |
| known_spells | list | [] | List of spell IDs this entity knows |
| elemental_affinity | str | "" | Primary element ("fire", "water", etc.) |
| mana_regen_rate | int | 2 | Mana regenerated per tick |
| magic_level | int | 1 | Magic proficiency level |
| magic_xp | int | 0 | XP toward next magic level |

### Spell Definitions

```python
SPELLS = {
    "fireball": {
        "name": "Fireball",
        "element": "fire",
        "mana_cost": 8,
        "effect_type": "damage",
        "base_power": 12,
        "description": "Hurl a ball of flame at the target.",
        "target_required": True,
        "level_required": 1,
    },
    "heal": {
        "name": "Heal",
        "element": "light",
        "mana_cost": 10,
        "effect_type": "heal",
        "base_power": 15,
        "description": "Restore health to yourself.",
        "target_required": False,
        "level_required": 1,
    },
    "stone_wall": {
        "name": "Stone Wall",
        "element": "earth",
        "mana_cost": 6,
        "effect_type": "defense_buff",
        "base_power": 5,
        "duration_ticks": 3,
        "description": "Raise a wall of stone, increasing defense temporarily.",
        "target_required": False,
        "level_required": 2,
    },
    "lightning_bolt": {
        "name": "Lightning Bolt",
        "element": "air",
        "mana_cost": 15,
        "effect_type": "damage",
        "base_power": 20,
        "description": "Call down a bolt of lightning.",
        "target_required": True,
        "level_required": 3,
    },
    "fog_cloud": {
        "name": "Fog Cloud",
        "element": "water",
        "mana_cost": 5,
        "effect_type": "area_debuff",
        "base_power": 0,
        "duration_ticks": 5,
        "description": "Summon a thick fog, reducing visibility for all at this location.",
        "target_required": False,
        "level_required": 2,
    },
    "shadow_step": {
        "name": "Shadow Step",
        "element": "shadow",
        "mana_cost": 12,
        "effect_type": "teleport",
        "base_power": 0,
        "description": "Step through the shadows to an adjacent location.",
        "target_required": False,
        "level_required": 3,
    },
}
```

### Biome Affinity Table

Multiplier applied to spell base_power based on biome and spell element:

| Element | Plains | Forest | Desert | Swamp | Mountain | Cave |
|---------|--------|--------|--------|-------|----------|------|
| fire | 1.0 | 0.8 | 1.5 | 0.5 | 1.0 | 1.2 |
| water | 1.0 | 1.2 | 0.5 | 1.5 | 0.8 | 1.0 |
| earth | 1.2 | 1.0 | 1.0 | 0.8 | 1.5 | 1.3 |
| air | 1.0 | 0.8 | 1.2 | 0.8 | 1.5 | 0.5 |
| shadow | 0.8 | 1.2 | 0.8 | 1.2 | 1.0 | 1.5 |
| light | 1.2 | 1.0 | 1.2 | 0.8 | 1.0 | 0.5 |

## Commands

### `cast <spell_id> [target_uuid]`

```python
@player_command
def cast(self, spell_id: str, target_uuid: str = "") -> dict:
    """Cast a spell, optionally targeting another entity."""
```

**Validation:**
1. Spell must be in `known_spells`
2. Entity magic_level must meet spell level_required
3. Entity must have enough mana
4. If `target_required`, target_uuid must be provided and target must be at same location
5. Entity must not be dead (if Combat aspect exists)

**Effect resolution:**

```python
def _resolve_spell(self, spell_def: dict, target_uuid: str) -> dict:
    # Get biome affinity multiplier
    biome = self._get_current_biome()
    element = spell_def["element"]
    multiplier = BIOME_AFFINITY.get(biome, {}).get(element, 1.0)

    # Character affinity bonus (+20% if spell element matches entity affinity)
    if self.data.get("elemental_affinity") == element:
        multiplier *= 1.2

    effective_power = int(spell_def["base_power"] * multiplier)

    if spell_def["effect_type"] == "damage":
        return self._apply_damage(target_uuid, effective_power)
    elif spell_def["effect_type"] == "heal":
        return self._apply_heal(effective_power)
    elif spell_def["effect_type"] == "defense_buff":
        return self._apply_buff("defense", effective_power, spell_def.get("duration_ticks", 3))
    elif spell_def["effect_type"] == "teleport":
        return self._apply_teleport()
    elif spell_def["effect_type"] == "area_debuff":
        return self._apply_area_effect(spell_def)
```

**Return format:**
```python
# Damage spell:
{
    "type": "cast_confirm",
    "spell": "Fireball",
    "target": "goblin",
    "damage": 18,  # 12 base * 1.5 desert affinity
    "biome_effect": "The desert heat amplifies your flames!",
    "mana_remaining": 12,
    "message": "You cast Fireball at the goblin for 18 damage!"
}

# Self-heal:
{
    "type": "cast_confirm",
    "spell": "Heal",
    "healed": 15,
    "hp": 20,
    "mana_remaining": 10,
    "message": "You cast Heal, restoring 15 health."
}
```

### `spells`

```python
@player_command
def spells(self) -> dict:
    """List known spells with mana costs and descriptions."""
```

**Return format:**
```python
{
    "type": "spells",
    "mana": 20,
    "max_mana": 20,
    "known_spells": [
        {
            "id": "fireball",
            "name": "Fireball",
            "element": "fire",
            "mana_cost": 8,
            "can_cast": True,
            "description": "Hurl a ball of flame at the target."
        }
    ]
}
```

### `meditate`

```python
@player_command
def meditate(self) -> dict:
    """Recover mana faster by meditating (skip next move opportunity)."""
```

**Behavior:** Immediately restores `mana_regen_rate * 3` mana (triple regen). The tradeoff is the player must stay still -- narratively they are meditating.

**Return format:**
```python
{
    "type": "meditate",
    "mana_recovered": 6,
    "mana": 26,
    "max_mana": 30,
    "message": "You focus your mind and feel magical energy flow back into you."
}
```

## Cross-Aspect Interactions

### Magic + Combat (damage spells)

Damage spells apply damage through the target's Combat aspect:

```python
def _apply_damage(self, target_uuid: str, power: int) -> dict:
    try:
        target_entity = Entity(uuid=target_uuid)
        target_combat = target_entity.aspect("Combat")
        # Apply damage (reduced by defense)
        defense = target_combat.data.get("defense", 0)
        actual_damage = max(1, power - defense // 2)  # Magic partially bypasses defense
        target_combat.data["hp"] -= actual_damage
        if target_combat.data["hp"] <= 0:
            target_combat._on_death(killer_uuid=self.entity.uuid)
        target_combat._save()
        return {"damage": actual_damage, "target_hp": target_combat.data["hp"]}
    except (KeyError, ValueError):
        return {"damage": 0, "message": "Target has no combat stats."}
```

Note: magic damage partially bypasses defense (defense // 2 reduction instead of full), making magic effective against heavily armored targets.

### Magic + Land (biome affinity)

```python
def _get_current_biome(self) -> str:
    """Get the biome at the entity's current location."""
    loc_uuid = self.entity.location
    if not loc_uuid:
        return "plains"
    try:
        loc = Land(uuid=loc_uuid)
        return loc.data.get("biome", "plains")
    except KeyError:
        return "plains"
```

### Magic + Equipment (enchanted items)

Equipment items can have `magic_bonus` properties that increase effective spell power:

```python
try:
    equip = self.entity.aspect("Equipment")
    magic_bonus = equip.data.get("stat_bonuses", {}).get("magic", 0)
    effective_power += magic_bonus
except (ValueError, KeyError):
    pass
```

### Magic + Inventory (spell scrolls)

Spell scrolls are items with `"tags": ["spell_scroll"]` and a `"teaches_spell"` field. Using a scroll teaches the spell and destroys the scroll.

### Magic + Crafting (enchanting)

Future integration: use the Crafting system to enchant items by combining base items with magical reagents. Enchanted items gain stat bonuses.

## Event Flow

### Mana Regeneration (tick-based)

```
Entity.schedule_next_tick() fires every tickDelay seconds
  -> Magic.tick() (if Magic is primary aspect or NPC has magic)
    -> mana = min(max_mana, mana + mana_regen_rate)
    -> Process duration-based buffs (decrement ticks, remove expired)
    -> Save
```

For player entities, mana regen is piggybacked on the NPC tick system. If the entity is a player without NPC aspect, a separate tick can be scheduled specifically for Magic.

### Spell Cast Sequence

```
Player sends: {"command": "cast", "data": {"spell_id": "fireball", "target_uuid": "goblin-uuid"}}
  -> Entity.receive_command(command="cast", ...)
    -> Magic.cast(spell_id="fireball", target_uuid="goblin-uuid")
      -> Validate spell, mana, target
      -> Deduct mana
      -> Calculate biome affinity multiplier
      -> Resolve spell effect (damage, heal, buff, etc.)
      -> broadcast_to_location(spell cast event)
      -> push_event(cast_confirm to caster)
      -> Save
```

## NPC Integration

### Magic-capable NPCs

NPCs can have the Magic aspect, giving them spellcasting in combat:

```python
# In NPC hostile behavior:
if "Magic" in self.entity.data.get("aspects", []):
    magic = self.entity.aspect("Magic")
    if magic.data.get("mana", 0) >= 8:
        magic.cast(spell_id="fireball", target_uuid=player_uuid)
        return
# Fall back to melee attack if no mana
```

### NPC spell teachers

Hermit NPCs can teach spells (similar to crafting recipe teachers):

```python
{
    "behavior": "hermit",
    "teaches_spells": ["heal", "stone_wall"],
    "requires_quest": "find_the_hermit"
}
```

### Elemental NPCs

NPCs spawned in specific biomes can have matching elemental affinities, making them stronger in their home territory. A fire elemental in a desert is more dangerous than one in a swamp.

## AI Agent Considerations

### Spell selection

AI agents can evaluate spell effectiveness using the structured data:
1. Call `spells` to see available spells and mana costs
2. Check current biome via `look` response
3. Select the spell with the best element-biome match
4. Reserve mana for `heal` when low health
5. Use `meditate` when safe and mana is low

### Mana management

The AI agent needs to track `mana_remaining` from cast_confirm events and plan spell usage accordingly. The `spells` command provides current mana state.

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/magic.py` | Magic aspect class with spell registry |
| `backend/aspects/tests/test_magic.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/serverless.yml` | Add `magic` Lambda with SNS filter for `Magic` aspect |
| `backend/aspects/npc.py` | Add spell-casting to hostile NPC behavior |

### Implementation order

1. Define spell registry and biome affinity table
2. Create `magic.py` with Magic class, cast, spells, meditate commands
3. Implement effect handlers (damage, heal, buff, teleport)
4. Add mana regeneration to tick system
5. Add Lambda + SNS filter to serverless.yml
6. Write tests (cast, mana deduction, biome affinity, level check, meditate)

## Open Questions

1. **Should mana regen be tick-based or time-based?** Tick-based (every N seconds via Step Functions) is simpler but costs Lambda invocations. Time-based (calculate regen on demand from last_action timestamp) is more efficient but less intuitive.

2. **Spell resistance?** Should entities have magic resistance separate from defense? Adds complexity but makes magic-focused combat more interesting.

3. **Spell combos?** Casting water then lightning in the same location could create bonus effects. Cool but adds combinatorial complexity. Defer to future.

4. **Friendly fire?** Can area spells hit allies? Current design: targeted spells require a specific target. Area spells affect all entities at the location except the caster.

5. **Mana potions?** Consumable items that restore mana. Would integrate with Inventory and Crafting. Add once both aspects exist.
