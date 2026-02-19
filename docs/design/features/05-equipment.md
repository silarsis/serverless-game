# Equipment Aspect

## What This Brings to the World

Equipment transforms items from fungible resources into personal identity. Without equipment slots, a sword is just a thing in your inventory that exists in a description. With equipment, that sword is in your hand -- it changes your stats, it appears in your description, and losing it hurts. Equipment creates attachment to specific items, which creates stakes, which creates stories. "I found this sword in the cave where I almost died" means something when the sword is equipped and actively keeping you alive.

The gear slot system also creates meaningful inventory management decisions. Seven slots means seven choices about tradeoffs: the lighter helmet with magic bonus versus the heavy one with defense. These decisions are the backbone of RPG character building, and they emerge naturally from the item system without requiring any class or build mechanics. A player's loadout tells you who they are and how they play.

For this architecture, Equipment is a solid fit in the data model but a costly one in read operations. The aspect stores only a slot-to-UUID mapping and computed stat bonuses -- minimal data, clean design. The problem is that every stat computation requires loading up to 7 item entities and their aspects, and this computation triggers on every equip, unequip, and durability change. Since Combat reads Equipment bonuses on every attack (for both attacker and target), the equipment system effectively doubles the DynamoDB reads per combat action. The design is sound in principle; the execution cost is the concern.

## Critical Analysis

**The gear command is a 14-read DynamoDB operation.** Displaying all equipment slots requires loading each equipped item's Entity (1 read) and its Inventory aspect (1 read) to get name, bonuses, and durability. With 7 slots filled, that is 14 DynamoDB reads for a single informational command. On a 1 RCU table, this takes 14 seconds to execute without throttling. Players are likely to check their gear frequently -- before combat, after looting, when deciding what to equip. This is a read-heavy query that would benefit enormously from a batch_get_item call, but the codebase does not use batch operations anywhere.

**_recompute_bonuses is called too frequently and reads too much.** The method loads every equipped item's Entity and Inventory aspect (up to 14 reads) and is called on every equip and every unequip. If a player equips a full loadout of 7 items in rapid succession, each equip triggers a recompute: first equip reads 1 item, second reads 2, third reads 3... totaling 1+2+3+4+5+6+7 = 28 item reads across 7 equip operations, plus 28 aspect reads = 56 DynamoDB reads. And if equipping to an occupied slot auto-unequips the current item first, that unequip also triggers a recompute, potentially doubling the total. A "equip full loadout" scenario could hit over 100 DynamoDB reads.

**Durability degradation adds writes to every combat action.** The design says weapon durability decreases when the attacker hits and armor durability decreases when the defender is hit. This means every attack now requires: (1) write to attacker Combat aspect, (2) write to target Combat aspect, (3) write to attacker's weapon item Inventory aspect (durability), (4) write to target's armor item Inventory aspect (durability), (5) recompute attacker Equipment stat_bonuses and write, (6) recompute target Equipment stat_bonuses and write. That is 6 aspect writes per attack, up from 2 without equipment. Each write is a full put_item. On a 1 WCU table, a single attack takes at minimum 6 seconds of write capacity. In a fight with 10 exchanges, that is 60 writes -- a full minute of write capacity consumed.

**Weight exemption creates a dependency inversion.** Inventory is the foundational aspect -- it exists before Equipment, and Equipment depends on it. But the weight exemption feature requires Inventory's `_carried_weight()` method to check Equipment's `equipped` dict to know which items to exclude. This means Inventory now depends on Equipment: a circular dependency. Inventory needs to `try: equip = self.entity.aspect("Equipment")` on every weight calculation. If Equipment is not deployed, the try/except handles it gracefully, but conceptually the base aspect now has knowledge of a derived aspect. Every future weight calculation pays the cost of attempting to load the Equipment aspect (1 read, or a KeyError), even for entities that will never have equipment.

**stat_bonuses cache has no invalidation mechanism.** The `stat_bonuses` dict is computed on equip/unequip and stored in the Equipment aspect data. Combat reads this cached value instead of computing it fresh. But what if an item's properties change after it is equipped? If an enchanting system modifies a weapon's `attack_bonus` from 3 to 5, the Equipment aspect's cached `stat_bonuses` still says 3. There is no event, no hook, and no invalidation trigger. The stale cache persists until the player unequips and re-equips the item. This is a latent bug that will manifest the moment any system modifies item properties in-place.

**Concurrent equip operations can corrupt slot state.** If two Lambda invocations process equip commands for the same entity simultaneously (e.g., player rapidly equips two items), both read the same `equipped` dict, both modify it, and both call `_save()` with put_item. The second write overwrites the first. The player thinks they equipped both items but only one is actually recorded. Worse, the recompute_bonuses for each invocation may read different item states, resulting in stat_bonuses that do not match actual equipped items.

**Durability at zero halves bonuses but does not force unequip.** When durability hits 0, the item is "broken" and its bonuses are halved. But it stays equipped. A player can continue using a broken sword at half effectiveness indefinitely. There is no repair urgency because the item still functions. This undermines the durability system's purpose as a gold sink or maintenance requirement. Either broken items should provide zero bonuses (creating urgency to repair) or they should auto-unequip (creating urgency to replace).

**Set bonus computation is referenced but not defined.** The `_recompute_bonuses` method calls `self._apply_set_bonuses(bonuses)`, but no implementation or data structure for set bonuses exists in the design. The `set_id` field is listed in item properties as "optional," but there is no set registry, no definition of what set bonuses are, and no documentation of how they are computed. This is dead code in the design -- it references a system that does not exist and will raise an AttributeError if called.

**Equipment has no level-check enforcement path.** Items have `level_required` but the equip command checks it against "combat/magic level." If the player has Combat level 5 and Magic level 2, and an item requires level 3, which level is checked? The design does not specify. If it checks Combat level only, magic-focused items with level requirements are gated on the wrong skill. If it checks the max of all levels, every player eventually bypasses all level gates by leveling any skill. The level check logic is underspecified.

**Dependency chain.** Equipment depends on Inventory (item data, weight exemption) and is consumed by Combat (stat bonuses) and Magic (magic_bonus). Inventory must exist first. The durability system requires Combat to call Equipment methods after every attack, creating a bidirectional dependency: Combat reads Equipment for bonuses, and Combat writes to Equipment for durability. The design also modifies Inventory's `_carried_weight()` method, meaning Equipment's implementation touches a foundational aspect.

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

---

## Implementation decision (2026-02-18)

To address the spec's concern about **14 DynamoDB reads per gear check**, the implementation uses DynamoDB **batch_get_item** to load:
- all equipped item Entity rows (ENTITY_TABLE) in one request, and
- all equipped item Inventory rows (LOCATION_TABLE) in one request.

This reduces a full gear display/bonus recompute to **2 batch reads** instead of 14 sequential get_item calls.
