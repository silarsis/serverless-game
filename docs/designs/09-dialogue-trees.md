# Dialogue Trees for NPCs

## Overview

The Dialogue system adds structured conversations to NPCs. Players initiate dialogue with `talk <npc>`, then navigate a tree of responses via numbered choices. NPC knowledge varies by type -- merchants discuss trade, guards warn of dangers, hermits share lore. Dialogue state is tracked per player-NPC pair, allowing multi-step conversations. Dialogue unlocks quests, reveals map info, teaches spells/recipes, and enables trade. An LLM fallback handles unscripted conversation for NPCs that have it enabled.

## Design Principles

**Dialogue is data, not code.** Dialogue trees are JSON structures with nodes, choices, and conditions. Adding NPC dialogue means adding data entries. The dialogue engine evaluates conditions and presents choices generically.

**Stateful conversations.** The system tracks which dialogue node each player-NPC pair is at. This enables multi-turn conversations where NPCs remember what was discussed. State is stored on the NPC's aspect data (keyed by player UUID).

**Conditions gate choices.** Some dialogue options only appear if conditions are met (has an item, has faction standing, has completed a quest). Conditions are checked dynamically against the player's current state.

**Each aspect owns its data.** Dialogue trees and conversation state live on the NPC aspect. Quest triggers from dialogue go through the Quest aspect. Trade actions go through Inventory. The NPC aspect orchestrates but doesn't store cross-aspect data.

**LLM as fallback, not primary.** Structured dialogue trees handle known interactions reliably. The LLM handles off-script conversation -- when a player says something unexpected, the NPC uses an LLM to generate a contextual response. This is optional per NPC.

## Aspect Data

### NPC Aspect Extensions

Added to the NPC aspect's data (already in **LOCATION_TABLE**):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| dialogue_tree | str | "" | ID of this NPC's dialogue tree in the registry |
| conversation_state | dict | {} | Map of player_uuid -> current node ID |
| knowledge | list | [] | Topics this NPC knows about (for LLM fallback) |
| llm_enabled | bool | False | Whether this NPC uses LLM for unscripted conversation |

### Dialogue Tree Registry

```python
DIALOGUE_TREES = {
    "guard_standard": {
        "root": {
            "text": "Halt, traveler. What brings you here?",
            "choices": [
                {
                    "label": "I'm just passing through.",
                    "next": "passing_through",
                },
                {
                    "label": "Any news from around here?",
                    "next": "news",
                },
                {
                    "label": "I need work. Got anything?",
                    "next": "quest_offer",
                    "condition": {"type": "no_active_quest", "quest_id": "gather_supplies"},
                },
                {
                    "label": "I've completed the task you gave me.",
                    "next": "quest_complete",
                    "condition": {"type": "quest_objectives_met", "quest_id": "gather_supplies"},
                },
                {
                    "label": "[Leave]",
                    "next": "_end",
                },
            ],
        },
        "passing_through": {
            "text": "Keep your nose clean and you'll have no trouble. The roads are safe near the settlement, but beyond that... watch yourself.",
            "choices": [
                {"label": "Thanks for the warning.", "next": "_end"},
                {"label": "What's out there?", "next": "dangers"},
            ],
        },
        "news": {
            "text": "Strange creatures have been spotted in the forest to the north. Some say they come from the caves beyond the mountains.",
            "choices": [
                {"label": "I'll investigate.", "next": "investigate"},
                {"label": "Sounds dangerous. I'll stay clear.", "next": "_end"},
            ],
        },
        "quest_offer": {
            "text": "Actually, yes. We need supplies -- wood and stone for fortifications. Bring me 3 wood and 2 stone, and I'll make it worth your while.",
            "choices": [
                {
                    "label": "Consider it done.",
                    "next": "_end",
                    "action": {"type": "accept_quest", "quest_id": "gather_supplies"},
                },
                {"label": "Not interested.", "next": "_end"},
            ],
        },
        "quest_complete": {
            "text": "Excellent work! These supplies will serve us well. Here, take this as thanks.",
            "choices": [
                {
                    "label": "Happy to help.",
                    "next": "_end",
                    "action": {"type": "complete_quest", "quest_id": "gather_supplies"},
                },
            ],
        },
        "dangers": {
            "text": "Goblins, mostly. Small, cowardly things alone -- but in packs they'll overwhelm you. And there are rumors of something worse deeper in the caves.",
            "choices": [
                {"label": "I can handle goblins.", "next": "_end"},
                {"label": "Thanks for the warning.", "next": "_end"},
            ],
        },
        "investigate": {
            "text": "Brave soul. Head north through the forest. If you find anything, report back.",
            "choices": [
                {
                    "label": "I'll head out now.",
                    "next": "_end",
                    "action": {"type": "reveal_location", "biome": "cave", "hint": "north through the forest"},
                },
            ],
        },
    },
    "merchant_standard": {
        "root": {
            "text": "Welcome, welcome! Take a look at my wares.",
            "choices": [
                {"label": "What do you have for sale?", "next": "browse"},
                {"label": "I'd like to sell something.", "next": "sell"},
                {"label": "Tell me about this area.", "next": "local_info"},
                {"label": "[Leave]", "next": "_end"},
            ],
        },
        "browse": {
            "text": "Here's what I have today:",
            "choices": [],
            "action": {"type": "show_trade_inventory"},
        },
        "sell": {
            "text": "Let me see what you've got.",
            "choices": [],
            "action": {"type": "show_player_sellable_items"},
        },
        "local_info": {
            "text": "This is a good spot for trade. Travelers come through regularly. If you're heading west, watch out for the swamp -- nasty place.",
            "choices": [
                {"label": "Thanks for the tip.", "next": "_end"},
                {"label": "Back to trading.", "next": "root"},
            ],
        },
    },
}
```

### Condition Types

| Condition Type | Parameters | Checks |
|----------------|-----------|--------|
| `no_active_quest` | quest_id | Player doesn't have this quest active |
| `has_active_quest` | quest_id | Player has this quest active |
| `quest_objectives_met` | quest_id | All objectives for this quest are complete |
| `has_item` | tag | Player has an item with this tag |
| `reputation_min` | faction_id, min_score | Player reputation >= threshold |
| `reputation_max` | faction_id, max_score | Player reputation <= threshold |
| `has_aspect` | aspect_name | Player entity has this aspect |

### Action Types

| Action Type | Parameters | Effect |
|-------------|-----------|--------|
| `accept_quest` | quest_id | Adds quest to player's active quests |
| `complete_quest` | quest_id | Triggers quest completion and rewards |
| `give_item` | name, description, properties | Creates item in player inventory |
| `teach_spell` | spell_id | Adds spell to player's known_spells |
| `teach_recipe` | recipe_id | Adds recipe to player's known_recipes |
| `reveal_location` | biome, hint | Gives player a hint about a location |
| `show_trade_inventory` | - | Lists NPC's items for sale |
| `reputation_change` | faction_id, amount | Adjusts player reputation |

## Commands

### `talk <target_uuid>`

```python
@player_command
def talk(self, target_uuid: str) -> dict:
    """Begin or continue a conversation with an NPC."""
```

**Behavior:**
1. Load target entity, verify it's an NPC at same location
2. Check conversation state for this player-NPC pair
3. If no state: start at "root" node
4. If existing state: resume at saved node
5. Evaluate conditions to filter available choices
6. Return dialogue text and available choices

**Return format:**
```python
{
    "type": "dialogue",
    "npc_name": "Town Guard",
    "npc_uuid": "guard-uuid",
    "text": "Halt, traveler. What brings you here?",
    "choices": [
        {"id": 1, "label": "I'm just passing through."},
        {"id": 2, "label": "Any news from around here?"},
        {"id": 3, "label": "I need work. Got anything?"},
        {"id": 4, "label": "[Leave]"}
    ]
}
```

### `respond <choice_id>`

```python
@player_command
def respond(self, choice_id: int, npc_uuid: str = "") -> dict:
    """Select a dialogue choice in an active conversation."""
```

**Behavior:**
1. Look up current conversation state
2. Validate choice_id is valid for current node
3. Execute any action attached to the choice
4. Navigate to next node
5. If next is "_end": clear conversation state
6. Otherwise: save new node, return next dialogue

**Return format:** Same as `talk` for next node, or:
```python
{
    "type": "dialogue_end",
    "npc_name": "Town Guard",
    "message": "The guard nods and returns to patrol."
}
```

### `say <message>` (LLM fallback)

When a player uses `say` while in dialogue with an LLM-enabled NPC, the message is routed to the LLM:

```python
# In Communication.say(), check if player is in dialogue:
if player_in_dialogue_with_llm_npc:
    return npc._llm_respond(player_message)
```

The LLM receives context about the NPC's role, knowledge, location, and conversation history to generate an appropriate response.

## Cross-Aspect Interactions

### Dialogue + Quest (quest acceptance/completion)

Dialogue actions trigger Quest aspect methods:

```python
def _execute_action(self, action: dict, player: Entity):
    if action["type"] == "accept_quest":
        try:
            quest_aspect = player.aspect("Quest")
            quest_aspect.accept(quest_id=action["quest_id"])
        except (ValueError, KeyError):
            pass

    elif action["type"] == "complete_quest":
        try:
            quest_aspect = player.aspect("Quest")
            quest_aspect._complete_quest(quest_id=action["quest_id"])
        except (ValueError, KeyError):
            pass
```

### Dialogue + Inventory (trade)

The `show_trade_inventory` action presents the NPC's sellable items:

```python
def _show_trade_inventory(self, player: Entity) -> dict:
    # NPC's trade items are entities at the NPC's location or in its "inventory"
    trade_items = []
    for item_uuid in self.entity.contents:
        try:
            item = Entity(uuid=item_uuid)
            item_inv = item.aspect("Inventory")
            if item_inv.data.get("for_sale"):
                trade_items.append({
                    "uuid": item.uuid,
                    "name": item.name,
                    "price": item_inv.data.get("price", 0),
                    "description": item_inv.data.get("description", ""),
                })
        except (KeyError, ValueError):
            continue

    return {
        "type": "trade_inventory",
        "npc_name": self.entity.name,
        "items": trade_items,
    }
```

### Dialogue + Magic (spell teaching)

The `teach_spell` action adds a spell to the player's Magic aspect:

```python
if action["type"] == "teach_spell":
    try:
        magic = player.aspect("Magic")
        known = magic.data.get("known_spells", [])
        if action["spell_id"] not in known:
            known.append(action["spell_id"])
            magic.data["known_spells"] = known
            magic._save()
    except (ValueError, KeyError):
        pass
```

### Dialogue + Faction (reputation-gated dialogue)

Dialogue choices with `reputation_min` conditions only appear when the player has sufficient faction standing:

```python
def _evaluate_condition(self, condition: dict, player: Entity) -> bool:
    if condition["type"] == "reputation_min":
        try:
            faction = player.aspect("Faction")
            rep = faction.data.get("reputation", {}).get(condition["faction_id"], 0)
            return rep >= condition["min_score"]
        except (ValueError, KeyError):
            return False
```

## Event Flow

### Dialogue Sequence

```
Player sends: {"command": "talk", "data": {"target_uuid": "guard-uuid"}}
  -> Entity.receive_command routes to NPC.talk()
    -> Load NPC dialogue tree
    -> Check/create conversation state for this player
    -> Evaluate conditions on root node choices
    -> Return filtered choices to player

Player sends: {"command": "respond", "data": {"choice_id": 3}}
  -> NPC.respond(choice_id=3)
    -> Lookup choice at index 3 in current node
    -> Execute action (accept_quest)
    -> Navigate to next node ("quest_offer")
    -> Return next node text and choices
```

### LLM Fallback Flow

```
Player sends: {"command": "say", "data": {"message": "Tell me about the old ruins"}}
  -> Communication.say() detects active LLM dialogue
    -> NPC._llm_respond(message="Tell me about the old ruins")
      -> Build LLM prompt with NPC context, knowledge, location
      -> Call Suggestion aspect's LLM integration
      -> Return NPC's generated response
      -> Save conversation snippet to NPC's conversation history
```

## NPC Integration

### Dialogue tree assignment

NPCs are assigned dialogue trees during creation:

```python
npc.create(
    behavior="guard",
    name="Town Guard",
    dialogue_tree="guard_standard",
    knowledge=["local_area", "dangers", "settlement"],
    llm_enabled=False
)
```

### NPC type dialogue patterns

| Behavior | Dialogue Focus | Typical Actions |
|----------|---------------|----------------|
| guard | Warnings, quests, local info | accept_quest, reveal_location |
| merchant | Trade, prices, goods | show_trade_inventory, give_item |
| hermit | Lore, magic, secrets | teach_spell, teach_recipe |
| wanderer | Travel tales, map hints | reveal_location |

### NPC memory

Conversation state persists between encounters. A guard remembers they gave you a quest. A merchant remembers your last purchase. State is stored as `conversation_state[player_uuid]` in the NPC's data.

Memory is bounded -- only the last N interactions per player are kept (default: 10 entries).

## AI Agent Considerations

### Dialogue navigation

AI agents receive the same `dialogue` events as human players with structured choices:

```json
{
    "type": "dialogue",
    "choices": [
        {"id": 1, "label": "I'm just passing through."},
        {"id": 2, "label": "Any news from around here?"},
        {"id": 3, "label": "I need work. Got anything?"}
    ]
}
```

An AI agent can parse choice labels and select based on goals:
- Looking for quests: choose options mentioning "work" or "task"
- Looking for information: choose "news" or "tell me about"
- Trading: choose "buy" or "sell" options

### LLM-to-LLM conversation

When an AI agent (itself backed by an LLM) talks to an LLM-enabled NPC, we get LLM-to-LLM dialogue. This is fine architecturally -- both sides use the same interface. But it could generate unbounded conversation loops. Solution: limit NPC LLM responses to 3 per player per tick.

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/dialogue.py` | Dialogue engine (condition evaluation, tree traversal) |
| `backend/aspects/tests/test_dialogue.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/aspects/npc.py` | Add `talk`, `respond` player commands, dialogue tree field, conversation state |
| `backend/serverless.yml` | No new Lambda needed -- dialogue runs within NPC Lambda |

### Implementation order

1. Define dialogue tree registry with guard and merchant trees
2. Create dialogue engine (tree traversal, condition evaluation, action execution)
3. Add `talk` and `respond` commands to NPC aspect
4. Implement condition types (quest state, inventory, reputation)
5. Implement action types (quest accept/complete, give_item, teach)
6. Optional: add LLM fallback integration
7. Write tests (tree traversal, condition evaluation, action execution, conversation state)

## Open Questions

1. **Where do dialogue trees live?** Module-level dict for now. Could move to DynamoDB for dynamic creation. Could also use YAML files loaded at deploy time for easier editing.

2. **Should dialogue be a separate aspect or part of NPC?** Current design: dialogue logic lives in a utility module, commands live on NPC aspect. This avoids a new Lambda. If dialogue grows complex, extract to its own aspect.

3. **Trade economics.** What currency do merchants use? Gold coins (simple)? Barter system (item-for-item)? No currency system exists yet -- this needs design.

4. **Conversation timeout.** If a player walks away mid-dialogue, when does the conversation state reset? Options: reset on location change, reset after N ticks of inactivity, never reset (resume later).

5. **NPC-to-NPC dialogue.** Should NPCs talk to each other? Would add world flavor but requires scripting NPC conversations. Low priority but architecturally possible (NPC's tick triggers dialogue with nearby NPCs).
