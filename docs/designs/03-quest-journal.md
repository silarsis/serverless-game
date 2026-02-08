# Quest/Journal Aspect

## What This Brings to the World

Quests give the game a narrative spine. Without them, the world is a sandbox with no direction -- players wander, fight things, pick stuff up, and eventually ask "what am I supposed to be doing?" Quests answer that question. They turn a collection of disconnected rooms and NPCs into a story the player is part of. The guard is not just a guard; he is the person who needs you to gather supplies for the fortifications. The hermit is not just a hermit; she is the one who knows the ancient secrets. Quests create meaning from game mechanics.

The journal system is equally important. It gives players a persistent record of what they have accomplished and what remains. In a text-based game where there is no minimap or quest tracker HUD, the journal command is the player's lifeline. It tells them where they are in the story without forcing them to remember every NPC conversation. For AI agents, the journal is even more critical -- it provides the structured data needed to plan multi-step objectives.

For this architecture, quests are a conceptual fit but an implementation nightmare. The quest system is by far the most invasive of all the proposed aspects. It requires hooking into Land (movement), Inventory (item pickup), Combat (kills), Crafting (crafting), and NPC (dialogue) -- essentially every other system. The design principle of "aspects don't know about each other" is violated in spirit if not in letter, because those other aspects must be modified to emit events that the Quest aspect consumes. This is the system most likely to create a tangled dependency web that makes future changes risky.

## Critical Analysis

**Most invasive design of all proposed aspects.** Auto-detection of quest objectives requires modifications to five existing aspects: Land.move() must trigger `on_location_change`, Inventory.take() must trigger collection checks, Combat._on_death() must trigger defeat checks, Crafting.craft() must trigger craft checks, and NPC._greet_player() must trigger dialogue checks. Every one of these existing aspects must be edited to add Quest-specific SNS calls. This directly contradicts the "aspects don't know about each other" principle. Land should not need to know that Quest exists in order to function. But with this design, removing the Quest aspect means leaving dead SNS calls in five other aspects.

**on_location_change routing violates aspect independence.** The `on_location_change` method is `@callable` on the Quest aspect, but it must be triggered FROM `Land.move()`. Land does not know about Quest. For this to work, `Land.move()` must explicitly call `Call(aspect="Quest", action="on_location_change")` after every move. This means Land has a hard dependency on Quest's existence. If Quest is not deployed, every move generates a failed SNS message. If Land is supposed to be a foundational aspect that works independently, this coupling is a design flaw. The alternative -- having Quest poll the entity's location periodically -- would be even worse (tick cost).

**Collection objective checking is O(N) on every relevant action.** The `_check_collect_objective` method iterates `self.entity.contents`, loading each item Entity and its Inventory aspect to check tags. This is the same O(2N) read pattern as crafting ingredient scanning. But it is worse here because it fires not just on craft, but on EVERY item pickup. If a player has 3 active quests with collection objectives and picks up an item while carrying 40 items, that single `take` action triggers 3 * (40 * 2) = 240 DynamoDB reads for quest checking alone, on top of the reads for the actual take operation. This will throttle immediately on a 1 RCU table.

**Quest definitions are code-deploy-only despite claiming otherwise.** The design principle states "quests are data, not code" but the quest registry is a module-level Python dict (`QUESTS = {...}`). This is identical to the crafting recipe problem. Adding a quest requires editing Python source, committing, and deploying. For a system whose primary value is narrative content, coupling content to code deploys is backwards. Quest content changes more frequently than quest logic, so the data should be in DynamoDB or at minimum in a JSON file loaded at runtime.

**Massive dependency chain -- requires nearly every other aspect.** The quest system assumes Combat exists (for defeat objectives and XP rewards), Crafting exists (for craft objectives and recipe rewards), Inventory exists (for collection objectives and item rewards), NPC exists (for quest-givers and dialogue), Land exists (for location objectives), and optionally Faction exists (for reputation rewards). If you implement Quest before Combat is ready, defeat objectives silently break. If Crafting is not deployed, craft objectives fail. There is no graceful degradation -- a quest with a "defeat_entity" objective will error if the target has no Combat aspect. This makes Quest the last system you can implement, even though narratively it should be the first.

**Quest completion reward distribution is a write amplifier.** When a quest completes, the system potentially writes to: Quest aspect (mark complete), Combat aspect (award XP), Inventory aspect (create reward items), Crafting aspect (add known_recipes), and Faction aspect (add reputation). That is up to 5 aspect writes for a single quest completion, each a full put_item. Plus item creation requires entity table writes. A quest that rewards 3 items means 3 entity creates (3 entity table writes + 3 inventory aspect writes) + 3 aspect updates = 9 writes total. On a 1 WCU table, quest completion will throttle for nearly 10 seconds.

**Quest chain_next creates invisible dependencies.** The `chain_next` field means completing one quest automatically makes another available. But the chain is defined only in the quest data, not enforced anywhere. If quest "A" chains to quest "B" but quest "B" is not in the registry (deleted, renamed, or not yet created), the chain silently fails. There is no validation of chain integrity, no way to list all quest chains, and no tooling to detect broken chains. In a game with 50+ quests, chain maintenance becomes a manual bookkeeping nightmare.

**No mechanism for quest-scoped items.** The design mentions "soulbound" items in the Open Questions but provides no implementation. Without soulbound items, a player can accept a quest requiring a "magic key," find the key, drop it, and another player can pick it up. The second player has the key but not the quest. The first player can never complete the quest because the key is gone. Quest items need special handling that does not exist yet.

**Step Functions cost for timed quests.** While the current design does not explicitly use timed quests, the `chain_next` mechanism and quest availability checks happen through NPC greetings. If quest timers are added later (as is common in MMO quest design), each timer would be another Step Functions execution. This is a future cost landmine.

**Scaling concern: active_quests is unbounded.** The `active_quests` dict in the Quest aspect data grows with every accepted quest. If a player accepts 20 quests, every objective check must iterate all 20 quests' objectives. The DynamoDB item also grows -- with complex quest definitions including objectives and progress tracking, 20 active quests could push the aspect data toward the 400KB item size limit, especially if quest descriptions are verbose.

## Overview

The Quest aspect gives entities the ability to accept, track, and complete quests. Quests are multi-step objectives (go to a location, collect items, talk to an NPC, defeat an entity) with rewards on completion. Quest definitions are data-driven, stored as JSON schemas. NPCs serve as quest-givers via dialogue. The journal tracks active and completed quests per entity, providing a persistent record of progress.

## Design Principles

**Quests are data, not code.** Each quest is a JSON definition with objectives, requirements, and rewards. Adding a new quest means adding a data entry. The Quest aspect's objective-checking logic is generic -- it evaluates conditions against the entity's current state.

**Objective auto-detection.** When a player moves to a location, picks up an item, or talks to an NPC, the Quest aspect checks if any active quest objectives were fulfilled. This happens reactively via events, not polling.

**Each aspect owns its data.** Quest progress (active quests, completed quests, objective states) lives in the Quest aspect's record. Quest definitions live in a registry. NPC quest-giver assignments live on the NPC aspect.

**Explicit cross-aspect access.** To check if an objective like "collect 3 wood" is met, the Quest aspect reads `self.entity.aspect("Inventory")` and scans for items with the "wood" tag. The dependency is visible.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| active_quests | dict | {} | Map of quest_id -> quest progress state |
| completed_quests | list | [] | List of completed quest IDs |

### Quest Progress State

```python
{
    "quest_id": "find_the_hermit",
    "started_at": 1234567890,
    "objectives": {
        "reach_hermit_cave": {"completed": False},
        "talk_to_hermit": {"completed": False}
    }
}
```

### Quest Definition Registry

```python
QUESTS = {
    "find_the_hermit": {
        "name": "Find the Hermit",
        "description": "A strange hermit lives in the mountain caves. Find them and learn their secrets.",
        "giver_behavior": "guard",  # NPC type that offers this quest
        "prerequisites": [],
        "objectives": [
            {
                "id": "reach_hermit_cave",
                "type": "reach_location",
                "description": "Travel to the mountain cave.",
                "target_biome": "cave",
                "order": 1
            },
            {
                "id": "talk_to_hermit",
                "type": "talk_to_npc",
                "description": "Speak with the hermit.",
                "target_npc_behavior": "hermit",
                "order": 2
            }
        ],
        "rewards": {
            "xp": 50,
            "items": [
                {"name": "ancient map", "description": "A tattered map showing hidden paths.", "tags": ["map", "quest_item"]}
            ],
            "recipes": ["healing_poultice"]
        },
        "chain_next": "hermits_task"  # Next quest in chain, offered on completion
    },
    "gather_supplies": {
        "name": "Gather Supplies",
        "description": "The guard needs wood and stone for fortifications.",
        "giver_behavior": "guard",
        "prerequisites": [],
        "objectives": [
            {
                "id": "collect_wood",
                "type": "collect_item",
                "description": "Collect 3 pieces of wood.",
                "target_tag": "wood",
                "target_count": 3,
                "order": 1
            },
            {
                "id": "collect_stone",
                "type": "collect_item",
                "description": "Collect 2 pieces of stone.",
                "target_tag": "stone",
                "target_count": 2,
                "order": 1
            },
            {
                "id": "return_to_guard",
                "type": "talk_to_npc",
                "description": "Return to the guard with the supplies.",
                "target_npc_behavior": "guard",
                "order": 2
            }
        ],
        "rewards": {
            "xp": 30,
            "items": [],
            "reputation": {"guards": 10}
        },
        "chain_next": null
    }
}
```

### Objective Types

| Type | Condition | Auto-detected? |
|------|-----------|----------------|
| `reach_location` | Entity location matches target biome or UUID | Yes, on move |
| `collect_item` | Inventory contains N items with target tag | Yes, on take |
| `talk_to_npc` | Entity interacts with NPC of target behavior | Yes, on NPC greeting |
| `defeat_entity` | Target entity killed (tracked via combat events) | Yes, on kill |
| `craft_item` | Item with target tag crafted | Yes, on craft |

## Commands

### `journal`

```python
@player_command
def journal(self) -> dict:
    """View active quests and their progress."""
```

**Return format:**
```python
{
    "type": "journal",
    "active_quests": [
        {
            "quest_id": "find_the_hermit",
            "name": "Find the Hermit",
            "objectives": [
                {"id": "reach_hermit_cave", "description": "Travel to the mountain cave.", "completed": False},
                {"id": "talk_to_hermit", "description": "Speak with the hermit.", "completed": False}
            ],
            "progress": "0/2 objectives complete"
        }
    ],
    "completed_count": 3
}
```

### `quest <quest_id>`

```python
@player_command
def quest(self, quest_id: str) -> dict:
    """View detailed info about a specific quest."""
```

**Return format:**
```python
{
    "type": "quest_detail",
    "quest_id": "find_the_hermit",
    "name": "Find the Hermit",
    "description": "A strange hermit lives in the mountain caves...",
    "objectives": [...],
    "rewards": {"xp": 50, "items": ["ancient map"]}
}
```

### `abandon <quest_id>`

```python
@player_command
def abandon(self, quest_id: str) -> dict:
    """Abandon an active quest."""
```

Removes the quest from `active_quests`. Does not add to `completed_quests`. The quest can be re-accepted from the original quest-giver.

## Cross-Aspect Interactions

### Quest + NPC (quest-givers)

NPCs with certain behaviors offer quests during dialogue:

```python
# In NPC._greet_player() or dialogue handler:
if self.data.get("quest_giver"):
    available_quests = self._get_available_quests(player)
    if available_quests:
        greeting += f" I have a task for you, if you're interested."
        player.push_event({
            "type": "quest_available",
            "npc_name": self.entity.name,
            "quests": available_quests
        })
```

Quest acceptance happens through dialogue (see 09-dialogue-trees.md) or a direct `accept <quest_id>` command.

### Quest + Inventory (collection objectives)

When checking `collect_item` objectives:

```python
def _check_collect_objective(self, objective: dict) -> bool:
    target_tag = objective["target_tag"]
    target_count = objective["target_count"]
    count = 0
    for item_uuid in self.entity.contents:
        try:
            item = Entity(uuid=item_uuid)
            item_inv = item.aspect("Inventory")
            if target_tag in item_inv.data.get("tags", []):
                count += 1
        except (KeyError, ValueError):
            continue
    return count >= target_count
```

### Quest + Land (location objectives)

When the entity moves (via `Land.move()`), the Quest aspect checks `reach_location` objectives:

```python
@callable
def on_location_change(self, new_location: str, biome: str = "") -> dict:
    """Check if any active quest objectives are fulfilled by this location."""
    for quest_id, progress in self.data.get("active_quests", {}).items():
        quest_def = QUESTS.get(quest_id)
        if not quest_def:
            continue
        for obj in quest_def["objectives"]:
            if obj["type"] == "reach_location" and not progress["objectives"][obj["id"]]["completed"]:
                if biome and obj.get("target_biome") == biome:
                    progress["objectives"][obj["id"]]["completed"] = True
                    self.entity.push_event({
                        "type": "objective_complete",
                        "quest": quest_def["name"],
                        "objective": obj["description"]
                    })
    self._check_quest_completion()
    self._save()
```

### Quest + Combat (defeat objectives)

When the entity kills a target, Combat broadcasts a kill event. The Quest aspect listens for `defeat_entity` objectives.

### Quest + Crafting (craft objectives)

After a successful craft, the Crafting aspect can trigger Quest objective checks for `craft_item` type objectives.

## Event Flow

### Quest Acceptance

```
NPC greets player with quest_available event
Player sends: {"command": "accept", "data": {"quest_id": "find_the_hermit"}}
  -> Quest.accept(quest_id="find_the_hermit")
    -> Validate quest exists, not already active/completed, prerequisites met
    -> Add to active_quests with empty objective progress
    -> push_event(quest_accepted)
```

### Objective Auto-Detection

```
Player moves to a new location:
  Land.move() completes
    -> SNS event to Quest aspect: on_location_change(new_location, biome)
      -> Check reach_location objectives
      -> If matched: mark objective complete, push_event(objective_complete)
      -> If all objectives complete: trigger quest completion
```

### Quest Completion

```
Quest._check_quest_completion()
  -> All objectives marked complete?
  -> Yes:
    -> Remove from active_quests
    -> Add quest_id to completed_quests
    -> Award rewards:
      -> XP to Combat aspect (if present)
      -> Items created via Inventory.create_item()
      -> Recipes added to Crafting.known_recipes (if present)
      -> Reputation to Faction aspect (if present)
    -> push_event(quest_complete with reward summary)
    -> If chain_next: make next quest available from same NPC
```

## NPC Integration

### Quest-giver NPCs

Any NPC can be a quest-giver by setting `quest_giver: True` in its NPC aspect data. The NPC's behavior type determines which quests it offers (guards offer guard quests, merchants offer trade quests, etc.).

```python
# NPC data for a quest-giver:
{
    "behavior": "guard",
    "quest_giver": True,
    "offered_quests": ["gather_supplies", "patrol_the_perimeter"]
}
```

### NPC dialogue integration

Quest dialogue follows this pattern:
1. NPC greets player
2. NPC mentions available quest
3. Player asks about quest (dialogue option)
4. NPC describes quest
5. Player accepts or declines
6. On return with completed objectives, NPC congratulates and gives rewards

### NPC as quest targets

Some objectives require talking to specific NPCs. The `talk_to_npc` objective is fulfilled when the NPC's `_greet_player()` fires and the player has an active quest targeting that NPC type.

## AI Agent Considerations

### Quest planning

AI agents can use `journal` to track active quests and plan their route:

1. Call `journal` to see active objectives
2. For `reach_location` objectives: plan navigation route
3. For `collect_item` objectives: find locations with matching terrain
4. For `talk_to_npc` objectives: find locations with matching NPC types
5. Execute objectives in order, checking `journal` periodically

### Auto-acceptance

An AI agent could automatically accept all available quests from NPCs, maintaining a priority queue based on reward value and estimated difficulty.

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/quest.py` | Quest aspect class with quest registry |
| `backend/aspects/tests/test_quest.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/serverless.yml` | Add `quest` Lambda with SNS filter for `Quest` aspect |
| `backend/aspects/npc.py` | Add quest-giver logic to `_greet_player()` |
| `backend/aspects/land.py` | Trigger `on_location_change` after move |

### Implementation order

1. Define quest registry as module-level dict with 3-5 starter quests
2. Create `quest.py` with Quest class, journal, quest, accept, abandon commands
3. Add objective auto-detection for reach_location and collect_item types
4. Integrate with NPC quest-giver dialogue
5. Add quest completion and reward distribution
6. Write tests (accept, objective tracking, completion, rewards, abandonment)

## Open Questions

1. **Quest instance vs template?** Current design: quests are templates, progress is tracked per-entity. Should quests have instance-specific variations (random targets, scaled difficulty)?

2. **Should quest items be special?** Quest items (keys, maps, etc.) could be marked "soulbound" -- cannot be dropped or traded. Prevents quest progress transfer between players.

3. **Repeatable quests?** Some quests (daily tasks, supply runs) could be repeatable with a cooldown. Add a `repeatable` flag and `cooldown_seconds` to the quest definition.

4. **Quest discovery.** Currently NPCs offer quests on greeting. Should there be exploration-based quest discovery (finding a note, reading a sign)?

5. **Multi-player quests.** Can multiple players work on the same quest simultaneously? Current design: each player has independent quest state. Shared objectives (group kill, collective gathering) would need additional coordination logic.
