# Faction/Reputation System

## What This Brings to the World

A faction and reputation system transforms a world of interchangeable NPCs into one where player choices have lasting consequences. Without factions, every guard is the same guard, every merchant sells the same way, and killing an NPC has no repercussions beyond that single encounter. With factions, the world develops political geography -- regions belong to groups, NPCs have loyalties, and the player's history follows them from room to room. Killing a Forest Ranger in one part of the map means Mountain Guards three biomes away treat the player differently, because alliances and rivalries create a web of consequence.

This is a strong fit for a serverless MUD because reputation is fundamentally a per-player state that changes infrequently. A player's faction scores update only on specific events (quest completion, NPC kill, trade) rather than every tick. This means the Faction aspect is read-heavy and write-light, which is the ideal DynamoDB access pattern. The data is small (a dict of faction_id to integer scores), fits easily in a single aspect record, and never approaches DynamoDB's 400KB item limit.

However, the system has a significant dependency problem. Factions alone -- without Quest, Combat, and NPC systems fully implemented -- deliver almost nothing to the player. The `reputation` command shows a list of scores, but those scores cannot change without combat kills or quest completions. The `faction` command shows faction details, but those details are static registry data. Until the systems that trigger reputation changes are built, Faction is an empty scaffold. This makes it a poor candidate for early implementation despite its architectural cleanliness.

## Critical Analysis

**Reputation cascade logic is inconsistent and one-directional.** The `_adjust_reputation` method cascades from the modified faction to its allies and rivals: helping forest_rangers gives mountain_guard (ally) +5, and hurts shadow_cult (rival) -5. But the cascade only follows the relationships defined on the *source* faction, not on the *target* faction. Mountain_guard lists desert_nomads as a rival, but killing a desert_nomad does not cascade to mountain_guard because the cascade starts from desert_nomads' faction definition, not from every faction that lists desert_nomads. This means the relationship graph is asymmetric in ways that are not obvious from reading the faction registry. If forest_rangers list shadow_cult as a rival but shadow_cult does not list forest_rangers as a rival, the cascade only flows in one direction. This will confuse players who expect reciprocal relationships.

**NPC faction checking adds a DynamoDB read to every NPC greeting.** The `_greet_player` code loads the player's Faction aspect (`player.aspect("Faction")`) to check reputation before deciding how to interact. NPC greetings fire on the NPC tick whenever a player is present at the NPC's location. With the default 30-second tick interval and 10 faction NPCs in a settlement, that is 20 faction aspect reads per minute per player present. For a settlement with 5 players and 10 faction NPCs, that is 100 faction reads per minute -- roughly 1.7 reads per second, which approaches the 1 RCU provisioned limit just for faction checks at a single location. This cost is on top of the existing NPC tick reads (loading entity, loading NPC aspect, checking for players via contents GSI).

**"Attack on sight" at hostile reputation is extremely punishing with no recovery path.** A player who kills one guard receives -20 reputation with that faction. Two kills bring the player to -40, and a third pushes past the -50 hostile threshold. Once hostile, guards attack the player on sight, making it impossible to enter faction territory to take quests that would improve reputation. The design mentions no recovery mechanism -- no neutral-ground NPCs, no reputation decay, no amnesty quests accessible from outside the territory. A player who stumbles into hostile reputation is permanently locked out of that faction's content unless they find indirect ways to improve standing (completing quests from allied factions, if those quests even grant reputation with the hostile faction). This is a soft permadeath for faction content.

**No way to discover an NPC's faction before interaction.** The `look` command shows NPCs in the room but does not indicate their faction membership. A player walking into an unfamiliar area has no way to know that the NPCs there belong to a faction they are hostile with until the NPCs attack. There is no "sense" command, no visible faction indicators in room descriptions, and no faction territory markers on rooms. Players will feel ambushed rather than challenged. At minimum, NPC descriptions should include faction affiliation (e.g., "a Forest Ranger guard stands here") and room descriptions in faction territory should mention the controlling faction.

**Faction registry is a module-level dict -- same "data not code" contradiction as elsewhere.** The design states that "NPC faction membership is data, not class," but the faction definitions themselves are hardcoded in a Python dict. Adding a new faction requires a code deployment. This is the same tension present in the dialogue tree registry, blueprint registry, and dungeon template registry across other designs. The architecture would benefit from a consistent approach to registries -- either commit to code-level definitions (fast, type-safe, but requires deployment) or move to DynamoDB-stored definitions (dynamic, but adds read costs and complexity).

**Dependency chain makes standalone value near zero.** The Faction aspect depends on: NPC system (for faction-gated greetings and combat), Quest system (for reputation rewards), and Combat system (for kill penalties). Without all three, the only player-facing feature is the `reputation` command, which returns an empty dict since no events have triggered reputation changes. Even the `faction` command just reads static registry data. This is the worst standalone-value-to-implementation-effort ratio of any aspect. It should be implemented only after NPC, Quest, and Combat are all functional.

**Step Functions cost is zero -- but hidden costs exist.** The Faction system does not use Call.after() or ticks, so there are no Step Functions costs. However, the hidden cost is in NPC ticks. Every NPC that checks faction reputation during its tick adds a DynamoDB read. Since NPC ticks are already running via Step Functions (at $0.00075 per 30-second tick per NPC), the faction check does not add new Step Functions executions but does add DynamoDB reads proportional to the number of players present at each NPC's location on each tick.

**Scaling concern: reputation dict grows unbounded.** The reputation dict stores faction_id to score for every faction the player has encountered. With 5 factions this is trivial, but if the game expands to 50+ factions (region-specific factions, player-created factions, event factions), the dict grows linearly. Since `_adjust_reputation` calls `self._save()` which does a full `put_item` replacing the entire aspect record, every reputation change writes the full dict. This is not a problem at 5 factions but becomes wasteful at scale. DynamoDB's `UpdateItem` with expression attributes would be more efficient but is not used anywhere in the codebase.

## Overview

The Faction aspect tracks an entity's standing with different factions in the game world. Factions are groups of NPCs tied to landmarks and regions. Player actions -- completing quests, defeating enemies, trading -- shift reputation up or down. Reputation gates NPC behavior: friendly factions offer quests and trade, hostile factions attack on sight. Territory control lets factions claim regions, and player choices between competing factions create meaningful consequences.

## Design Principles

**Reputation is per-entity, per-faction.** Each entity has a reputation score with each faction it has encountered. This lives in the Faction aspect's data. Factions themselves are not entities -- they are named groups defined in a registry.

**NPC faction membership is data, not class.** An NPC belongs to a faction by having `faction: "forest_rangers"` in its NPC aspect data. The NPC class does not change -- faction membership is just a property that modifies existing behavior (greet, attack, trade).

**Actions have consequences.** Killing a faction member reduces standing with that faction. Helping a faction improves standing. Some factions are opposed -- helping one automatically harms standing with its rival. This creates genuine player choice.

**Each aspect owns its data.** Faction stores reputation scores. NPC stores faction membership. Quest stores faction-related rewards. No cross-table writes -- each aspect reads from others.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| reputation | dict | {} | Map of faction_id -> reputation score |
| faction_membership | str | "" | Which faction this entity belongs to (for NPCs) |

### Reputation Scale

| Score | Standing | NPC Behavior |
|-------|----------|-------------|
| -100 to -50 | Hostile | Attack on sight |
| -49 to -10 | Unfriendly | Refuse interaction, warn player |
| -9 to 9 | Neutral | Standard behavior |
| 10 to 49 | Friendly | Offer quests, better trade prices |
| 50 to 100 | Honored | Exclusive quests, faction vendors, safe passage |

### Faction Registry

```python
FACTIONS = {
    "forest_rangers": {
        "name": "Forest Rangers",
        "description": "Protectors of the woodland territories.",
        "home_biomes": ["forest"],
        "rivals": ["shadow_cult"],
        "allies": ["mountain_guard"],
        "npc_behaviors": ["guard", "wanderer"],
    },
    "mountain_guard": {
        "name": "Mountain Guard",
        "description": "Stoic defenders of the highland passes.",
        "home_biomes": ["mountain_peak", "misty_highlands"],
        "rivals": ["desert_nomads"],
        "allies": ["forest_rangers"],
        "npc_behaviors": ["guard", "patrol"],
    },
    "desert_nomads": {
        "name": "Desert Nomads",
        "description": "Wandering traders of the arid wastes.",
        "home_biomes": ["desert"],
        "rivals": ["mountain_guard"],
        "allies": [],
        "npc_behaviors": ["merchant", "wanderer"],
    },
    "shadow_cult": {
        "name": "Shadow Cult",
        "description": "A secretive group operating in caves and dark places.",
        "home_biomes": ["cave", "swamp"],
        "rivals": ["forest_rangers"],
        "allies": [],
        "npc_behaviors": ["hermit"],
    },
    "settlement_folk": {
        "name": "Settlement Folk",
        "description": "Common people of the settlements and towns.",
        "home_biomes": ["plains"],
        "rivals": [],
        "allies": ["forest_rangers", "mountain_guard"],
        "npc_behaviors": ["merchant", "guard"],
    },
}
```

### Rival/Ally Reputation Cascade

When reputation changes with a faction, allied and rival factions are affected:

```python
def _adjust_reputation(self, faction_id: str, amount: int):
    rep = self.data.get("reputation", {})

    # Direct change
    current = rep.get(faction_id, 0)
    rep[faction_id] = max(-100, min(100, current + amount))

    # Allied factions gain half the positive change
    faction_def = FACTIONS.get(faction_id, {})
    for ally in faction_def.get("allies", []):
        ally_current = rep.get(ally, 0)
        if amount > 0:
            rep[ally] = max(-100, min(100, ally_current + amount // 2))

    # Rival factions lose half the positive change (or gain half the negative)
    for rival in faction_def.get("rivals", []):
        rival_current = rep.get(rival, 0)
        rep[rival] = max(-100, min(100, rival_current - amount // 2))

    self.data["reputation"] = rep
    self._save()
```

## Commands

### `reputation`

```python
@player_command
def reputation(self) -> dict:
    """Show current standing with all known factions."""
```

**Return format:**
```python
{
    "type": "reputation",
    "factions": [
        {
            "id": "forest_rangers",
            "name": "Forest Rangers",
            "score": 25,
            "standing": "Friendly",
            "description": "Protectors of the woodland territories."
        },
        {
            "id": "shadow_cult",
            "name": "Shadow Cult",
            "score": -30,
            "standing": "Unfriendly"
        }
    ]
}
```

### `faction <faction_id>`

```python
@player_command
def faction(self, faction_id: str) -> dict:
    """View detailed info about a specific faction."""
```

**Return format:**
```python
{
    "type": "faction_detail",
    "id": "forest_rangers",
    "name": "Forest Rangers",
    "score": 25,
    "standing": "Friendly",
    "description": "Protectors of the woodland territories.",
    "allies": ["Mountain Guard"],
    "rivals": ["Shadow Cult"],
    "benefits": "Quest access, discounted trade, safe passage in forest territories."
}
```

## Cross-Aspect Interactions

### Faction + NPC (behavior gating)

NPCs check the player's faction reputation before interacting:

```python
# In NPC._greet_player():
def _greet_player(self, player: Entity):
    npc_faction = self.data.get("faction", "")
    if npc_faction:
        try:
            player_faction = player.aspect("Faction")
            rep = player_faction.data.get("reputation", {}).get(npc_faction, 0)

            if rep <= -50:
                # Hostile -- attack instead of greet
                if "Combat" in self.entity.data.get("aspects", []):
                    combat = self.entity.aspect("Combat")
                    combat.attack(target_uuid=player.uuid)
                return

            if rep <= -10:
                # Unfriendly -- dismiss
                player.push_event({
                    "type": "say",
                    "speaker": self.entity.name,
                    "message": "I have nothing to say to you."
                })
                return

            # Friendly and above: normal interaction + faction-specific dialogue
        except (ValueError, KeyError):
            pass  # No faction aspect = neutral
```

### Faction + Quest (reputation rewards)

Quest rewards can include reputation changes:

```python
# In Quest._complete_quest():
rewards = quest_def.get("rewards", {})
reputation_rewards = rewards.get("reputation", {})
if reputation_rewards:
    try:
        faction_aspect = self.entity.aspect("Faction")
        for faction_id, amount in reputation_rewards.items():
            faction_aspect._adjust_reputation(faction_id, amount)
    except (ValueError, KeyError):
        pass
```

### Faction + Combat (kill consequences)

Killing an NPC with a faction membership reduces standing:

```python
# After Combat._on_death() resolves:
# Check if killed entity had a faction
killed_entity = Entity(uuid=target_uuid)
try:
    killed_npc = killed_entity.aspect("NPC")
    killed_faction = killed_npc.data.get("faction", "")
    if killed_faction:
        try:
            killer_faction = self.entity.aspect("Faction")
            killer_faction._adjust_reputation(killed_faction, -20)
        except (ValueError, KeyError):
            pass
except (ValueError, KeyError):
    pass
```

### Faction + Land (territory)

Faction territories are regions where their NPCs patrol. Being in a faction's territory with hostile standing triggers patrols to attack:

```python
# In NPC._guard() or _patrol(), when checking for players:
if player_reputation <= -50:
    # Chase and attack hostile player in our territory
    combat.attack(target_uuid=player.uuid)
```

### Faction + Equipment/Crafting (faction vendors)

Faction vendors sell exclusive items only to players with sufficient reputation:
- Friendly (10+): basic faction gear
- Honored (50+): exclusive weapons, armor, recipes

## Event Flow

### Reputation Change

```
Player kills a Forest Ranger NPC
  -> Combat._on_death() fires
  -> Check killed NPC's faction (forest_rangers)
  -> Adjust player reputation: forest_rangers -20
  -> Cascade: mountain_guard -10 (ally), shadow_cult +10 (rival)
  -> push_event(reputation_change) to player
```

### Faction-gated NPC Interaction

```
Player enters location with Mountain Guard NPC
  -> NPC._check_for_players() fires
  -> NPC checks player's mountain_guard reputation
  -> If hostile: NPC attacks
  -> If unfriendly: NPC dismisses
  -> If friendly: NPC offers quests
  -> If honored: NPC offers exclusive items
```

## NPC Integration

### Faction membership

NPCs are assigned factions during creation:

```python
npc.create(behavior="guard", name="Ranger Captain", faction="forest_rangers")
```

This is a new field in NPC data. NPCs without factions behave neutrally toward all players.

### Faction-specific dialogue

NPC greeting pools are extended with faction-aware lines:

```python
FACTION_GREETINGS = {
    "forest_rangers": {
        "friendly": ["Welcome, friend of the forest. How can we help?"],
        "neutral": ["Traveler. The forest is watched. Behave yourself."],
        "unfriendly": ["You're not welcome here. Move along."],
    }
}
```

### Faction patrols

Guard NPCs in faction territories actively patrol and enforce faction law. Hostile players are attacked. Friendly players are greeted warmly.

## AI Agent Considerations

### Faction strategy

AI agents can check `reputation` to plan faction interactions:
1. Track reputation across factions
2. Avoid hostile faction territories
3. Prioritize quests that improve standing with desired factions
4. Balance rival faction relationships (helping one hurts another)

### Faction-aware navigation

Before moving through a region, an AI agent should:
1. Check which faction controls the area (biome-based)
2. Check own reputation with that faction
3. If hostile, find an alternative route or prepare for combat

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/faction.py` | Faction aspect class with faction registry |
| `backend/aspects/tests/test_faction.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/serverless.yml` | Add `faction` Lambda with SNS filter for `Faction` aspect |
| `backend/aspects/npc.py` | Add faction-aware behavior to greeting and combat |
| `backend/aspects/quest.py` | Add reputation rewards to quest completion |
| `backend/aspects/combat.py` | Trigger reputation change on NPC kill |

### Implementation order

1. Define faction registry with 4-5 starter factions
2. Create `faction.py` with Faction class, reputation, faction commands
3. Implement reputation cascade (allies gain, rivals lose)
4. Modify NPC behavior for faction-gated interactions
5. Add reputation rewards to quest system
6. Add reputation penalty for killing faction NPCs
7. Write tests (reputation change, cascade, standing thresholds, NPC behavior)

## Open Questions

1. **Should factions be dynamic?** Current design: factions are hardcoded in a registry. Could factions be created by players or evolve over time? Start static, add dynamism later.

2. **Territory control mechanics.** How do factions "control" territory? Currently implicit (NPCs spawn in biomes). Explicit control (faction flag on locations, contestable by players) adds PvP depth but complexity.

3. **Reputation decay.** Should reputation drift toward neutral over time? This prevents permanent lock-out from factions but reduces consequence. Optional: slow decay for negative reputation only.

4. **Multi-faction membership.** Can players join a faction? Current design: players have reputation but not membership. Joining a faction could grant special abilities but restrict others.

5. **Faction wars.** Should factions fight each other? NPCs from rival factions could battle when they meet. Adds world dynamism but requires careful balancing to avoid NPC depletion.
