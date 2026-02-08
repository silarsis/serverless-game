# Equipment Aspect

## Overview

The Equipment aspect adds gear slots to entities, allowing them to equip items that modify combat stats and appearance. Entities have slots for head, body, hands, feet, main hand, off hand, and accessory. Equipped items provide stat bonuses (attack, defense, magic) that other aspects read via cross-aspect access. Items gain durability that degrades with use and can be repaired via crafting or NPC services.

## Design Principles

**Items are entities with properties.** An equipped sword is the same entity that was in inventory -- its location is still the entity's UUID. Equipment just tracks *which* items are in which slots and computes aggregate stat bonuses. No new storage model needed.

**Stat computation is lazy.** Equipment doesn't push stat changes to Combat. Instead, Combat pulls bonuses from Equipment when calculating effective attack/defense: `self.entity.aspect("Equipment").data["stat_bonuses"]`. This keeps aspects independent -- Equipment works even if Combat doesn't exist.

**Slots are fixed.** The slot set (head, body, hands, feet, held_main, held_off, accessory) is hardcoded. This simplifies UI and prevents edge cases. New slot types require a code change, which is intentional -- slots are a game design decision, not user data.

**Each aspect owns its data.** Equipment stores the slot-to-item mapping and computed stat_bonuses. Item properties (slot compatibility, bonus values) live on the item's Inventory aspect. The entity table stores shared identity fields.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| equipped | dict | {} | Map of slot -> item UUID |
| stat_bonuses | dict | {} | Computed aggregate stat bonuses |

### Slot Definitions

```python
SLOTS = {
    "head": {"name": "Head", "description": "Helmets, hats, crowns"},
    "body": {"name": "Body", "description": "Armor, robes, cloaks"},
    "hands": {"name": "Hands", "description": "Gloves, gauntlets"},
    "feet": {"name": "Feet", "description": "Boots, shoes, greaves"},
    "held_main": {"name": "Main Hand", "description": "Weapons, staves, wands"},
    "held_off": {"name": "Off Hand", "description": "Shields, secondary weapons"},
    "accessory": {"name": "Accessory", "description": "Rings, amulets, charms"},
}
```

### Item Equipment Properties

Items that can be equipped have these fields in their Inventory aspect data:

```python
{
    "slot": "held_main",       # Which slot this item goes in
    "attack_bonus": 3,         # Bonus to attack stat
    "defense_bonus": 0,        # Bonus to defense stat
    "magic_bonus": 0,          # Bonus to magic power
    "hp_bonus": 0,             # Bonus to max HP
    "durability": 50,          # Current durability
    "max_durability": 50,      # Maximum durability
    "level_required": 1,       # Minimum combat/magic level to equip
    "set_id": "",              # Set bonus identifier (optional)
}
```

### stat_bonuses Computation

When equipment changes, `stat_bonuses` is recomputed by scanning all equipped items:

```python
def _recompute_bonuses(self):
    bonuses = {"attack": 0, "defense": 0, "magic": 0, "hp": 0}
    for slot, item_uuid in self.data.get("equipped", {}).items():
        try:
            item_entity = Entity(uuid=item_uuid)
            item_inv = item_entity.aspect("Inventory")
            for stat in bonuses:
                bonuses[stat] += item_inv.data.get(f"{stat}_bonus", 0)
        except (KeyError, ValueError):
            continue

    # Check for set bonuses
    bonuses = self._apply_set_bonuses(bonuses)
    self.data["stat_bonuses"] = bonuses
```

## Commands

### `equip <item_uuid>`

```python
@player_command
def equip(self, item_uuid: str) -> dict:
    """Equip an item from inventory to the appropriate slot."""
```

**Validation:**
1. Item must be in entity's inventory (location == entity UUID)
2. Item must have a `slot` property in its Inventory aspect
3. Entity must meet `level_required` for the item
4. If slot is occupied, automatically unequip current item first

**Behavior:**
1. Load item's Inventory aspect to get slot and bonuses
2. If slot occupied: unequip current item (moves it back to general inventory)
3. Map item UUID to slot in `equipped` dict
4. Recompute `stat_bonuses`
5. Save

**Return format:**
```python
{
    "type": "equip_confirm",
    "item": "iron sword",
    "slot": "held_main",
    "stat_changes": {"attack": "+3"},
    "message": "You equip the iron sword in your main hand."
}
```

### `unequip <slot>`

```python
@player_command
def unequip(self, slot: str) -> dict:
    """Remove an item from an equipment slot."""
```

**Validation:**
1. Slot must be valid
2. Slot must have an item equipped

**Behavior:**
1. Remove item UUID from `equipped` dict
2. Item remains in inventory (location unchanged)
3. Recompute `stat_bonuses`
4. Save

**Return format:**
```python
{
    "type": "unequip_confirm",
    "item": "iron sword",
    "slot": "held_main",
    "stat_changes": {"attack": "-3"},
    "message": "You remove the iron sword from your main hand."
}
```

### `gear`

```python
@player_command
def gear(self) -> dict:
    """Show all equipment slots and what's equipped."""
```

**Return format:**
```python
{
    "type": "gear",
    "slots": {
        "head": null,
        "body": {"name": "leather armor", "uuid": "item-uuid", "defense_bonus": 3},
        "hands": null,
        "feet": {"name": "leather boots", "uuid": "item-uuid", "defense_bonus": 1},
        "held_main": {"name": "iron sword", "uuid": "item-uuid", "attack_bonus": 3},
        "held_off": null,
        "accessory": null
    },
    "total_bonuses": {"attack": 3, "defense": 4, "magic": 0, "hp": 0}
}
```

## Cross-Aspect Interactions

### Equipment + Combat (stat bonuses)

Combat reads equipment bonuses when calculating effective stats:

```python
# In Combat._effective_attack():
def _effective_attack(self) -> int:
    base = self.data.get("attack", 5)
    try:
        equip = self.entity.aspect("Equipment")
        bonuses = equip.data.get("stat_bonuses", {})
        base += bonuses.get("attack", 0)
    except (ValueError, KeyError):
        pass
    return base

# In Combat._effective_defense():
def _effective_defense(self) -> int:
    base = self.data.get("defense", 2)
    try:
        equip = self.entity.aspect("Equipment")
        bonuses = equip.data.get("stat_bonuses", {})
        base += bonuses.get("defense", 0)
    except (ValueError, KeyError):
        pass
    return base
```

### Equipment + Inventory (weight exemption)

Equipped items do not count toward carry weight. The Inventory's `_carried_weight()` method excludes items listed in Equipment's `equipped` dict:

```python
# In Inventory._carried_weight():
equipped_uuids = set()
try:
    equip = self.entity.aspect("Equipment")
    equipped_uuids = set(equip.data.get("equipped", {}).values())
except (ValueError, KeyError):
    pass

for item_uuid in self.entity.contents:
    if item_uuid in equipped_uuids:
        continue  # Skip equipped items
    # ... count weight
```

### Equipment + Inventory (item descriptions)

`Inventory.examine()` could include equipment status:

```python
# Append to examine output:
try:
    equip = self.entity.aspect("Equipment")
    equipped_items = equip.data.get("equipped", {})
    if item_uuid in equipped_items.values():
        slot = [s for s, u in equipped_items.items() if u == item_uuid][0]
        result["equipped_in"] = slot
except (ValueError, KeyError):
    pass
```

### Equipment + Crafting (repairs)

When durability reaches 0, the item's bonuses are halved (broken but not destroyed). Repairs use the Crafting system:

```python
# Future: Crafting.repair(item_uuid)
# Requires materials matching item tags
# Restores durability to max
```

### Equipment + Magic (enchanted gear)

Items with `magic_bonus > 0` increase spell power. The Magic aspect reads `stat_bonuses.magic` from Equipment.

### Equipment + Communication (appearance)

The entity's visual description can include equipped items:

```python
def get_appearance(self) -> str:
    """Generate a description including equipped items."""
    desc_parts = [f"{self.entity.name}"]
    equipped = self.data.get("equipped", {})
    if equipped.get("body"):
        body_item = Entity(uuid=equipped["body"])
        desc_parts.append(f"wearing {body_item.name}")
    if equipped.get("held_main"):
        weapon = Entity(uuid=equipped["held_main"])
        desc_parts.append(f"wielding {weapon.name}")
    return ", ".join(desc_parts)
```

## Event Flow

### Equip Sequence

```
Player sends: {"command": "equip", "data": {"item_uuid": "sword-uuid"}}
  -> Entity.receive_command(command="equip", item_uuid="sword-uuid")
    -> Equipment.equip(item_uuid="sword-uuid")
      -> Load item entity, get slot from Inventory aspect
      -> If slot occupied: unequip current
      -> Set equipped[slot] = item_uuid
      -> Recompute stat_bonuses
      -> Save Equipment aspect
      -> push_event(equip_confirm)
```

### Durability Degradation

```
Combat.attack() resolves damage
  -> After hit: degrade attacker's weapon durability
  -> After being hit: degrade defender's armor durability

Equipment._degrade_durability(slot):
  -> item_uuid = equipped[slot]
  -> item_inv = item_entity.aspect("Inventory")
  -> item_inv.data["durability"] -= 1
  -> If durability <= 0:
    -> Halve stat bonuses from this item
    -> push_event(item_broken)
  -> item_inv._save()
  -> Recompute stat_bonuses
```

## NPC Integration

### NPC equipment

NPCs can have Equipment aspects with pre-set gear. Guards spawn with armor and weapons, giving them combat stat bonuses:

```python
# During NPC creation:
guard_entity.data["aspects"] = ["NPC", "Combat", "Equipment", "Inventory"]
equip = guard_entity.aspect("Equipment")
# Create and equip a guard sword
sword = create_item(name="guard's sword", slot="held_main", attack_bonus=3)
equip.data["equipped"] = {"held_main": sword.uuid}
equip._recompute_bonuses()
equip._save()
```

### NPC loot

When an NPC with equipment dies, equipped items can drop as loot (unequip + drop at location). This creates meaningful combat rewards -- kill the guard, take the sword.

### Merchant NPCs

Merchants can sell equipment items. Players browse via dialogue, then receive items via `Inventory.create_item()`.

## AI Agent Considerations

### Gear optimization

AI agents can use `gear` to see current equipment and `inventory` to see available items. An optimization loop:

1. Call `gear` to see current stat bonuses
2. Call `inventory` to list available items
3. For each unequipped item: check if its bonuses exceed current slot occupant
4. `equip` items that provide upgrades
5. Sell or drop downgraded items

### Equipment-aware combat

Before engaging in combat, an AI agent should:
1. Ensure best weapon is equipped in `held_main`
2. Check armor durability
3. Consider switching gear for biome-specific encounters

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/equipment.py` | Equipment aspect class |
| `backend/aspects/tests/test_equipment.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/serverless.yml` | Add `equipment` Lambda with SNS filter for `Equipment` aspect |
| `backend/aspects/combat.py` | Read stat_bonuses from Equipment for effective stats |
| `backend/aspects/inventory.py` | Exclude equipped items from weight calculation |

### Implementation order

1. Create `equipment.py` with Equipment class, equip, unequip, gear commands
2. Implement stat_bonuses computation
3. Add durability system
4. Integrate with Combat (effective stats calculation)
5. Integrate with Inventory (weight exemption)
6. Add Lambda + SNS filter to serverless.yml
7. Write tests (equip, unequip, stat computation, slot validation, durability, weight exemption)

## Open Questions

1. **Two-handed weapons?** Items that occupy both `held_main` and `held_off`. Would need a `two_handed: True` flag and auto-unequip of off-hand item. Add when weapon variety justifies the complexity.

2. **Set bonuses.** Equipping multiple items from the same set (e.g., "Forest Ranger" set) grants extra bonuses. Adds meaningful gear planning but requires maintaining set definitions. Good future enhancement.

3. **Equip restrictions by aspect?** Should only entities with Combat benefit from attack bonuses? Currently Equipment is purely additive -- any entity can equip anything. Combat reads bonuses only if it exists. This is correct -- Equipment is neutral, consumers decide what bonuses mean.

4. **Visual descriptions.** Should equipping items change how others see you? The `get_appearance()` method is a nice addition but needs integration with `Land.look()` or a new `look_at <entity>` command.

5. **Equipment persistence on death.** Should equipped items drop on death like inventory? Current design says yes (Combat._on_death drops everything). Could make "soulbound" items that persist through death.
