# Crafting Aspect

## What This Brings to the World

Crafting transforms the game from a world you pass through into a world you reshape. Without crafting, items are static objects -- you find a sword or you do not. With crafting, a fallen branch becomes potential. A pile of stones becomes a wall. The player's relationship to the environment shifts from consumer to creator, and that shift is what separates a forgettable MUD from one people return to.

The design's strongest contribution is that it ties crafting directly to the existing terrain entity system from worldgen. Those "a fallen branch" and "some loose stones" entities that the world generator scatters across locations gain purpose. Instead of being flavor text you walk past, they become resources. This retroactively makes the entire world map feel more intentional. The gather-craft loop also creates a reason to explore -- you need to find the right biomes for the right materials.

For this architecture, crafting is a moderate fit. The recipe-as-data model is clean and works well with the aspect pattern. The problematic parts are the inventory scanning costs (every craft operation requires reading every carried item to find matching tags) and the terrain respawn system that relies on Step Functions delayed calls. Crafting will not break the architecture, but at scale -- 100 players gathering and crafting simultaneously -- the DynamoDB read costs will be the limiting factor.

## Critical Analysis

**Ingredient scanning is O(N) DynamoDB reads per craft.** The `craft` command scans all inventory items to find those matching required tags. For each item in `self.entity.contents`, it loads the Entity (1 read) and then loads the Inventory aspect (1 read). A player carrying 50 items who crafts anything triggers 100 DynamoDB reads just for the ingredient search. If the recipe has 3 different ingredient tags, the scan runs once but checks all tags per item -- still 100 reads total, not 300. But the cost is linear with inventory size, and there is no caching or indexing by tag. A player who hoards materials will pay more for every craft than one who travels light. On a 1 RCU table, 100 reads will throttle for approximately 100 seconds.

**Terrain respawn via Call.after(seconds=300) has real Step Functions cost.** Each gathered terrain entity schedules a respawn 5 minutes later. Each Step Functions execution costs $0.000025 per state transition, and a 300-second wait is 300 transitions = $0.0075 per terrain respawn. If 50 players are actively gathering and each gathers 10 terrain per hour, that is 500 Step Functions executions per hour = $3.75/hour = $2,700/month just for terrain respawn timers. This is among the most expensive tick-based operations in the entire system.

**The gather command vacuums entire rooms.** The design says gather "picks up all gatherable terrain" at the current location. There is no limit on how many terrain entities can be gathered in one command. If a forest location has 8 fallen branches and 4 loose stones, one `gather` command picks up all 12. This has two problems: (1) it strips the location bare, leaving nothing for subsequent visitors, and (2) it triggers 12 terrain respawn timers simultaneously ($0.09 in Step Functions cost for that single gather). There should be a per-command gather limit, or gather should target a single entity.

**Tag-based ingredient matching loses item identity.** Recipes match ingredients by tag (e.g., "wood"), not by specific item type. If there are two different wood items -- "a fallen branch" (common, weight 1) and "an ancient oak limb" (rare, weight 3) -- the recipe treats them identically. A player might accidentally consume a rare quest-relevant item as a generic crafting ingredient because it has the "wood" tag. There is no confirmation step, no priority system (use cheapest items first), and no way to protect specific items from crafting consumption. At minimum, the craft command should prefer the lowest-value matching items.

**No currency or exchange mechanism.** The design mentions merchants and trade but never defines how exchange works. It says "trade UI uses dialogue trees" and points to 09-dialogue-trees.md, but there is no currency system, no barter valuation, no price list. Can a player buy wood from a merchant? What do they pay with? Gold does not exist as a concept anywhere in the aspect system. This is a critical gap -- merchants are decorative without a functioning economy.

**Recipe definitions are code-deploy-only.** Despite the design principle stating "recipes are data, not code," the recipe registry is a module-level Python dict loaded at Lambda cold start. Adding or modifying a recipe requires a code change, a git commit, and a full serverless deployment. The design acknowledges this ("Future: move to DynamoDB for dynamic recipe creation") but treats it as a deferred concern. In practice, recipe tuning is the most frequent type of game balance change. Coupling it to code deploys means every balance tweak requires a full deploy cycle.

**Crafting skill provides no meaningful gate.** The `crafting_skill` field exists and recipes have `skill_required`, but the design does not explain how crafting skill increases besides `xp_reward` from successful crafts. If a player can craft basic recipes (skill_required: 0) to gain XP and level up to unlock advanced recipes, there is no meaningful gate -- just craft 100 wooden clubs to unlock leather armor. There is no failure chance, no quality variance, no skill-based differentiation.

**Workbench check requires loading location contents.** The `requires_workbench` check means the craft command must query the current location's contents (1 GSI query), then scan those entities for one with a workbench flag (N entity reads + N aspect reads). In a busy town location with 50 entities, that is up to 100 additional reads just to check if a workbench is present. This check happens on every craft of a workbench-required recipe.

**Dependency chain.** Crafting depends on Inventory (item creation and consumption), Land (location for terrain gathering), and optionally Equipment (crafted gear properties) and NPC (merchants, teachers). Inventory must exist first. The terrain respawn mechanism also modifies Inventory, so the Inventory aspect needs a new `respawn_terrain` callable method, meaning Crafting's implementation requires modifying a foundational aspect.

## Overview

The Crafting aspect allows entities to combine items from their inventory into new items using recipes. Recipes are defined as data (not code) and map a set of input items to an output item. Materials come from terrain entities (gatherable resources at locations) and loot drops. Workbench entities at landmarks enable advanced recipes. Crafting integrates with Inventory (item consumption and creation), Land (terrain gathering), and NPC (merchant trade for materials).

## Design Principles

**Recipes are data, not code.** Recipe definitions live in a registry (DynamoDB or in-memory dict). Adding a new recipe means adding a data entry, not writing a new method. This lets world builders extend crafting without code deploys.

**Items are entities.** A crafted sword is an entity with an Inventory aspect (`is_item=True`). It has the same UUID/location/aspects model as everything else. No special "item class" -- just entities with item properties.

**Gathering is interaction with terrain.** The worldgen system already creates terrain entities ("a fallen branch", "some loose stones"). Gathering means picking up these terrain items, which uses the existing `Inventory.take()` command. The Crafting aspect adds a `gather` command that specifically targets terrain entities (items with `is_terrain=True`).

**Each aspect owns its data.** Crafting stores `known_recipes` and `crafting_skill` in its aspect record. Item properties (weight, description, tags) live on the item's Inventory aspect. The entity table stores identity and location.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| known_recipes | list | [] | List of recipe IDs this entity knows |
| crafting_skill | int | 0 | Crafting proficiency level |
| crafting_xp | int | 0 | XP toward next crafting level |

### Recipe Registry

Recipes are stored in a module-level dict (loaded once per Lambda cold start). Future: move to DynamoDB for dynamic recipe creation.

```python
RECIPES = {
    "wooden_club": {
        "name": "Wooden Club",
        "ingredients": {"wood": 2},
        "output": {
            "name": "a wooden club",
            "description": "A rough club fashioned from branches.",
            "weight": 3,
            "tags": ["weapon", "melee", "wood"],
            "slot": "held_main",       # For Equipment aspect
            "attack_bonus": 2,         # For Combat aspect
        },
        "skill_required": 0,
        "xp_reward": 5,
        "requires_workbench": False,
    },
    "torch": {
        "name": "Torch",
        "ingredients": {"wood": 1, "cloth": 1},
        "output": {
            "name": "a torch",
            "description": "A flickering torch that pushes back the darkness.",
            "weight": 1,
            "tags": ["light", "fire"],
        },
        "skill_required": 0,
        "xp_reward": 3,
        "requires_workbench": False,
    },
    "leather_armor": {
        "name": "Leather Armor",
        "ingredients": {"leather": 3, "thread": 2},
        "output": {
            "name": "leather armor",
            "description": "A sturdy set of leather armor.",
            "weight": 5,
            "tags": ["armor", "body", "leather"],
            "slot": "body",
            "defense_bonus": 3,
        },
        "skill_required": 5,
        "xp_reward": 15,
        "requires_workbench": True,
    },
}
```

### Material Tags

Items have `tags` in their Inventory aspect data. Crafting uses tags to match ingredients:
- `"wood"` -- from fallen branches, logs
- `"stone"` -- from loose stones, rocks
- `"cloth"` -- from fabric scraps
- `"leather"` -- from animal hides
- `"metal"` -- from ore deposits
- `"herb"` -- from plants

## Commands

### `craft <recipe_id>`

```python
@player_command
def craft(self, recipe_id: str) -> dict:
    """Craft an item from a recipe using inventory materials."""
```

**Validation:**
1. Recipe must exist in registry
2. Recipe must be in `known_recipes` (or `skill_required == 0` for basic recipes)
3. Entity must have all required ingredients in inventory (matched by tag)
4. Entity crafting_skill must meet recipe `skill_required`
5. If `requires_workbench`, entity must be at a location containing a workbench entity

**Behavior:**
1. Find matching items in inventory by tag
2. Consume ingredient items (call `item.destroy()` for each)
3. Create output item via `Inventory.create_item()`
4. Award crafting XP
5. Check for crafting level up

**Return format:**
```python
{
    "type": "craft_confirm",
    "recipe": "wooden_club",
    "item_name": "a wooden club",
    "item_uuid": "new-item-uuid",
    "message": "You craft a wooden club from 2 wood."
}
```

### `recipes`

```python
@player_command
def recipes(self) -> dict:
    """List known recipes and their ingredients."""
```

**Return format:**
```python
{
    "type": "recipes",
    "recipes": [
        {
            "id": "wooden_club",
            "name": "Wooden Club",
            "ingredients": {"wood": 2},
            "skill_required": 0,
            "can_craft": True,  # Has materials?
            "requires_workbench": False
        }
    ]
}
```

### `gather`

```python
@player_command
def gather(self) -> dict:
    """Gather materials from terrain at the current location."""
```

**Behavior:**
1. Check current location for terrain entities (`is_terrain=True` in their Inventory aspect)
2. If terrain entity is gatherable, pick it up (same as `Inventory.take()`)
3. Terrain entities may regenerate after a delay (via `Call(...).after()`)

**Return format:**
```python
{
    "type": "gather_confirm",
    "items": [{"name": "wood", "uuid": "item-uuid"}],
    "message": "You gather some wood from a fallen branch."
}
```

### `learn <recipe_id>`

```python
@player_command
def learn(self, recipe_id: str) -> dict:
    """Learn a recipe (from a recipe scroll item or NPC teacher)."""
```

**Validation:** Entity must have a recipe scroll item in inventory, or be interacting with an NPC teacher. The recipe scroll is consumed on use.

## Cross-Aspect Interactions

### Crafting + Inventory

**Ingredient consumption:** Crafting scans the entity's inventory (via `self.entity.contents`) for items matching required tags. Matched items are destroyed (`item.destroy()`).

**Item creation:** Output items are created via `Inventory.create_item()` with properties from the recipe definition. The new item appears in the crafter's inventory.

```python
# Finding ingredients by tag
inv = self.entity.aspect("Inventory")
for item_uuid in self.entity.contents:
    try:
        item_entity = Entity(uuid=item_uuid)
        item_inv = item_entity.aspect("Inventory")
        item_tags = item_inv.data.get("tags", [])
        if required_tag in item_tags:
            matched_items.append(item_entity)
    except (KeyError, ValueError):
        continue
```

### Crafting + Equipment

Crafted items can have equipment properties (`slot`, `attack_bonus`, `defense_bonus`). These properties are stored in the item's Inventory aspect data and read by the Equipment aspect when equipped.

### Crafting + Land (terrain resources)

The worldgen system creates terrain entities at locations. Terrain entities have:
- `is_terrain=True` in Inventory aspect
- `terrain_type` matching a material tag ("wood", "stone", etc.)
- Optional `gather_description` for flavor text

After gathering, terrain entities can regenerate:
```python
# Schedule terrain respawn
Call(
    tid=str(uuid4()), originator="",
    uuid=terrain_uuid, aspect="Inventory", action="respawn_terrain"
).after(seconds=300)  # Respawn in 5 minutes
```

### Crafting + NPC (merchants and teachers)

**Merchants** can sell recipe scrolls or raw materials. This uses the existing NPC greeting/dialogue system to present trade options.

**Teachers** are NPCs that teach recipes when interacted with. The `learn` command checks if the entity is at a location with a teacher NPC.

### Crafting + Combat

Crafted weapons and armor integrate with Combat via Equipment. A crafted "wooden club" with `attack_bonus: 2` adds to the entity's effective attack when equipped.

## Event Flow

### Craft Sequence

```
Player sends: {"command": "craft", "data": {"recipe_id": "wooden_club"}}
  -> Entity.receive_command(command="craft", recipe_id="wooden_club")
    -> Crafting.craft(recipe_id="wooden_club")
      -> Validate recipe exists, skill met, materials present
      -> For each ingredient: find matching item, call item.destroy()
      -> Call Inventory.create_item(name, description, **properties)
      -> Award crafting XP, check level up
      -> Return craft_confirm event
```

### Gather Sequence

```
Player sends: {"command": "gather"}
  -> Crafting.gather()
    -> Query location contents for terrain entities
    -> For each gatherable terrain: call Inventory.take(terrain_uuid)
    -> Schedule terrain respawn via delayed Call
    -> Return gather_confirm event
```

## NPC Integration

### Crafting-aware NPCs

**Merchant NPCs** gain a trade inventory of raw materials and recipe scrolls. Players can buy materials they cannot find in the wild. Trade UI uses dialogue trees (see 09-dialogue-trees.md).

**Hermit NPCs** can serve as crafting teachers, teaching recipes when players complete dialogue or quests.

### NPC crafting

NPCs do not craft items themselves in the initial implementation. Future: NPCs could craft items to sell based on available materials.

## AI Agent Considerations

### Material planning

AI agents can use `recipes` to see what materials are needed, `inventory` to check current stock, and `gather` to collect materials. The structured responses make planning straightforward:

1. Call `recipes` to get ingredient lists
2. Call `inventory` to check current materials
3. Calculate shortfall
4. Navigate to locations with terrain resources
5. `gather` until materials sufficient
6. `craft` the desired item

### Recipe discovery

AI agents discover recipes the same way players do -- finding recipe scrolls or visiting NPC teachers. No special recipe API exists.

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/crafting.py` | Crafting aspect class with recipe registry |
| `backend/aspects/tests/test_crafting.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/serverless.yml` | Add `crafting` Lambda with SNS filter for `Crafting` aspect |
| `backend/aspects/inventory.py` | Add `respawn_terrain` callable method |
| `backend/aspects/worldgen/describe.py` | Ensure terrain entities have material tags |

### Implementation order

1. Define recipe registry as module-level dict
2. Create `crafting.py` with Crafting class, craft, recipes, gather, learn commands
3. Add terrain respawn logic to Inventory
4. Ensure worldgen terrain entities have proper tags
5. Add Lambda + SNS filter to serverless.yml
6. Write tests (craft success, missing ingredients, skill check, gather, workbench check)

## Open Questions

1. **Where to store recipes long-term?** Module-level dict works for now. DynamoDB table allows dynamic recipe creation (player-submitted recipes, quest rewards). The dict is simpler; migrate when needed.

2. **Should gathering be automatic or require a specific target?** Current design: `gather` picks up all gatherable terrain at the location. Alternative: `gather <item_uuid>` for specific targeting. Starting with "gather all" for simplicity.

3. **Terrain respawn timing.** 5 minutes is arbitrary. Should it scale with resource scarcity? Should some resources be non-renewable? Start with fixed timer, tune later.

4. **Recipe complexity scaling.** How many tiers of recipes? Should there be a tech tree? Start with flat recipes, add complexity when the base crafting works.

5. **Workbench placement.** Who places workbenches -- world generation only, or can players build them? If players can build, this ties into the Building aspect (see 08-building-construction.md).
