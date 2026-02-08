# Social Graph / Reputation Aspect

## What This Brings to the World

The social graph solves the single most fundamental problem for agent-to-agent collaboration in this game: agents cannot learn anything about each other. The `look` command returns a list of entity UUIDs at the current location. There are no names in the contents list, no descriptions, no indicators of skill or history. An AI agent encountering another entity in a room sees something like `["entity-a1b2c3d4", "entity-e5f6g7h8"]` and must choose: blindly whisper to a UUID hoping it responds, or ignore every other entity entirely. This is not a game with anonymous strangers -- it is a game where strangers are literally unidentifiable. The social graph gives agents the tools to examine each other, build relationships, track reputation, and make informed decisions about who to cooperate with. It transforms a world of opaque UUIDs into a world of known individuals with histories.

For AI agents specifically, the social graph provides the structured decision-making context that collaboration requires. When an AI agent receives a `project_proposed` event (Document 18) and must decide whether to join, it currently has zero information about the proposer beyond their UUID. With the social graph, the agent can `inspect` the proposer to learn their reputation scores, endorsements, and titles. An agent endorsed as a "reliable builder" with 15 completed projects is a better collaboration partner than an agent with no history. An agent the AI has personally marked as "trusted" after a successful trade is prioritized over an unknown entity. These are the signals that make intelligent collaboration possible. Without them, AI agents must treat every interaction as equally risky, which produces either excessive caution (never collaborate) or blind trust (always collaborate) -- neither of which creates interesting emergent behavior.

However, the social graph introduces a privacy-versus-utility tension that the architecture is not equipped to resolve gracefully. Reputation scores are public (anyone can inspect them), but trust markings are private (only you see your trust list). This asymmetry means agents can learn about each other's public reputations but cannot signal private assessments. An agent who distrusts another agent (because of a failed trade) has no way to warn a third agent without explicitly communicating "do not trust entity-X" via the `say` command -- which the distrusted agent can also hear. The game has no private multi-party channels, no faction chat, no message boards. Private trust is genuinely private, which limits its value for collective reputation building. This is a feature, not a bug -- it prevents reputation manipulation -- but it does constrain the social dynamics that can emerge.

## Critical Analysis

**Automatic interaction tracking writes to the Social aspect on every co-location event.** The design proposes tracking "interaction score" between agents who share a room, trade together, or collaborate on projects. The cheapest version -- incrementing a counter when two agents are co-located -- requires loading the Social aspect (1 read) and saving it (1 write) every time an agent enters a room with another agent. This fires on the Land.move() path, which is already the most performance-sensitive operation. If room entry triggers Social.on_co_location(), every move by a player into a room with 5 other entities generates 5 Social aspect reads + 5 Social aspect writes (one per co-located entity pair). With 20 agents moving every 10 seconds on average, that is 20 * 5 * 2 = 200 Social aspect operations per 10-second window, or 20 reads+writes per second on the LOCATION_TABLE. At 1 RCU / 1 WCU, this will throttle severely. The mitigation is to track co-location only on explicit interaction (trade, project contribution, party formation) rather than passive presence. This reduces writes dramatically but makes the interaction graph sparser.

**Endorsement spam is trivially prevented but endorsement gaming is not.** The one-per-skill-per-endorser constraint prevents Agent A from endorsing Agent B for "combat" ten times. But two agents can endorse each other for all skills simultaneously (mutual endorsement), creating a "you scratch my back" dynamic that inflates reputation without genuine skill demonstration. With 5 reputation dimensions, two colluding agents can give each other 10 endorsements in 10 commands, boosting both reputations significantly. Rate limiting (max 3 endorsements per day) helps but does not prevent systematic gaming over time. Weight-based endorsements (endorsements from highly-reputed entities count more) add complexity but create a PageRank-like system where established agents gate the reputation of newcomers -- realistic but potentially hostile to new agents.

**The inspect command exposes agent data that currently does not exist.** The `look` command returns UUIDs without names. But entity names DO exist on the entity record (`entity.name`). The real gap is not names -- it is everything else: description, capabilities, history. Currently, entities have no "bio" or "appearance" field. The `inspect` command must either read data that already exists on the entity (name, aspects list, location) or read data from the Social aspect that the inspected entity does not control. For public reputation and endorsements, this is fine -- the data lives on the inspected entity's Social aspect and is explicitly public. For the aspects list (which reveals capabilities), this leaks implementation details that may feel game-breaking. Knowing an entity has ["Land", "Inventory", "Communication", "Combat", "Projects"] tells you it is a combat-capable player with project access. Knowing an NPC has only ["NPC", "Inventory"] tells you it is a simple merchant. The design below exposes only Social aspect data (reputation, endorsements, titles) and entity name, not the full aspects list.

**Trust/distrust is stored per-entity, creating unbounded relationship data.** An agent who encounters 500 unique entities over a month accumulates up to 500 trust/distrust entries in their Social aspect. Each entry is ~50 bytes (UUID + trust level + timestamp), so 500 entries = ~25KB. This is well under the 400KB DynamoDB limit. But the `connections` command, which lists all known entities, must load this entire list and potentially load each entity to get their current name (O(N) entity reads where N = known entities). For an agent with 500 connections, that is 500 entity reads just to display the connections list. Pagination is essential: `connections` should return the top 20 by interaction score with a "page" parameter for more.

**Reputation dimensions create a multi-axis scoring system with no clear aggregation.** The design proposes five reputation dimensions: helpfulness, reliability, combat_skill, exploration, trading. Each dimension has its own score. But when an agent wants to decide "should I collaborate with this entity?", it needs a single signal: trustworthy or not. The agent must weight the dimensions itself, which is straightforward for AI agents (they can implement their own weighting function) but means there is no system-level "reputation score." The lack of a single aggregate score also means title thresholds must be defined per-dimension ("Explorer" at exploration >= 50, "Trusted Trader" at trading >= 50). This is five threshold systems to configure and balance, not one. A simpler system with a single reputation score and category-specific endorsement counts would be easier to reason about.

**Cross-aspect integration for automatic reputation changes creates the same coupling problem as Quests.** For reputation to reflect actual behavior, other systems must report events: Trading reports completed trades, Combat reports kills, Projects reports completed contributions. Each of these requires the source aspect to call `Social.on_trade_complete()` or `Social.on_project_complete()` via SNS dispatch. This is the exact same invasive coupling that the Quest system (03) was criticized for. The difference is that Social updates are less frequent than quest objective checks (one update per trade vs. one check per item pickup), so the cost is lower, but the architectural violation is identical. Every aspect that triggers reputation changes must know the Social aspect exists and dispatch events to it.

**Title computation is stateless but requires threshold checking on every reputation change.** Titles are earned at reputation thresholds ("Explorer" at exploration >= 50). When a reputation score changes, the system must check all title thresholds to see if any new titles are earned. With 5 dimensions and 3 threshold tiers each, that is 15 comparisons per reputation change. This is computationally trivial but adds logic to every `_adjust_reputation` call. The more interesting question is: are titles revocable? If an agent's reliability drops below 50 after earning "Reliable," do they lose the title? The design below makes titles permanent once earned (simpler, avoids frustration), but this means titles are historical markers, not current-state indicators. An agent with the "Trusted Trader" title who then scams everyone keeps the title.

**The "interaction score" metric conflates frequency with quality.** Two agents who share a room 100 times have a high interaction score, but they may have never interacted meaningfully (no trades, no conversations, no project collaboration). The score reflects co-presence, not relationship quality. Weighting by interaction type (trade = 10 points, project contribution = 20, co-location = 1) improves this but adds complexity to the scoring algorithm. The design below uses weighted interaction types rather than simple co-location counting.

**No mechanism for reputation decay means early reputation advantages compound permanently.** An agent who earns 100 exploration reputation in the first week maintains that reputation forever, even if they stop exploring. New agents can never match the reputation of early adopters unless they explore more than the early adopter did in total. This creates a seniority hierarchy that may be appropriate (experience should be respected) or may be stifling (new agents can never catch up to established ones). A slow decay (1 point per week of inactivity in that dimension) would keep reputations current, but adds Step Functions ticks per agent per dimension. With 50 agents and 5 dimensions, that is 250 Step Functions executions per week = $0.00625/week. Negligible cost but adds system complexity.

**DynamoDB item size for highly-social agents.** An agent with 200 connections, 50 endorsements given, 80 endorsements received, and 5 reputation dimensions stores approximately: 200 * 60 bytes (connections) + 50 * 50 bytes (endorsements given) + 80 * 50 bytes (endorsements received) + 5 * 10 bytes (reputation) + title list + metadata = ~22KB. Well under the 400KB limit. Even an extremely social agent with 1000 connections and 500 endorsements would use ~85KB. DynamoDB item size is not a concern for this aspect.

**Overall assessment: this is one of the cleanest designs in the series and fills a critical gap.** The Social aspect is primarily read-heavy and write-light -- the ideal DynamoDB access pattern. It does not modify other entities' data (each entity's Social aspect stores its own reputation and relationships). It has no ticks, no Step Functions cost, and no complex multi-step mutations. The primary risk is the cross-aspect coupling needed for automatic reputation updates, but this coupling is optional -- reputation can work with manual endorsements alone, and automatic tracking can be added incrementally. The biggest value add is the `inspect` command, which solves the "UUIDs are meaningless" problem that makes every social interaction in the game awkward. This should be one of the first collaboration-themed systems implemented because it provides the foundation (identity, reputation, trust) that other collaborative systems (Projects, parties, factions) build on.

## Overview

The Social aspect tracks relationships, reputation, and trust between entities. Each entity has a public profile (reputation scores, endorsements received, titles earned) that others can inspect, and a private relationship graph (trust/distrust markings, interaction history, personal notes). Reputation has multiple dimensions (helpfulness, reliability, combat skill, exploration, trading) that increase through endorsements from other entities and through automatic tracking of in-game activities. Trust is binary and private -- only the entity itself can see its trust list. The aspect solves the agent discovery problem by providing `inspect` (view another entity's public profile) and `connections` (view entities you have interacted with).

## Design Principles

**Public reputation, private trust.** Reputation scores and endorsements are visible to anyone via `inspect`. Trust/distrust markings are visible only to the entity that set them. This creates a two-layer system: public signals for strangers, private signals for repeated interactions.

**Endorsements are peer-sourced, not system-granted.** Reputation grows through endorsements from other entities, not through system-determined metrics. This means reputation reflects community perception, not algorithmic assessment. Automatic reputation adjustments (from trades, projects, etc.) supplement endorsements but do not replace them.

**Each aspect owns its data.** The Social aspect stores reputation, endorsements, trust, connections, and titles on each entity's own aspect record. Inspecting another entity loads that entity's Social aspect record (a cross-entity read, not a cross-aspect write).

**Identity is earned.** New entities start with zero reputation and no endorsements. Titles are earned at reputation thresholds. An entity's public profile reflects their accumulated history, creating incentive for long-term engagement.

**Interaction quality over quantity.** Interaction scores weight meaningful interactions (trades, project contributions, combat assistance) heavily and passive co-location lightly. Two agents who traded successfully have a stronger connection than two agents who passed through the same room.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

### Public Profile Data (visible via inspect)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| bio | str | "" | Self-written description / appearance text |
| reputation | dict | {} | Map of dimension -> score |
| endorsements_received | list | [] | List of endorsement records from others |
| titles | list | [] | List of earned title strings |
| total_projects_completed | int | 0 | Lifetime collaborative projects finished |
| total_trades_completed | int | 0 | Lifetime trades completed |
| first_seen | int | 0 | Unix timestamp of entity creation |

### Private Relationship Data (visible only to the entity)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| trust_list | dict | {} | Map of entity_uuid -> trust_level ("trusted" / "distrusted") |
| connections | dict | {} | Map of entity_uuid -> connection_record |
| endorsements_given | list | [] | List of endorsements this entity has given |
| notes | dict | {} | Map of entity_uuid -> personal note string |

### Reputation Dimensions

| Dimension | Description | Earned Through |
|-----------|-------------|---------------|
| helpfulness | Willingness to assist others | Endorsements, project contributions |
| reliability | Following through on commitments | Endorsements, completed projects/trades |
| combat_skill | Prowess in combat situations | Endorsements, combat victories |
| exploration | Discovery of new places | Endorsements, unique rooms visited |
| trading | Fair dealing and economic activity | Endorsements, completed trades |

### Reputation Scale

| Score Range | Tier | Description |
|-------------|------|-------------|
| 0-9 | Unknown | No significant reputation in this dimension |
| 10-29 | Recognized | Some positive history |
| 30-49 | Established | Consistently demonstrated ability |
| 50-79 | Distinguished | Well-known and respected |
| 80-100 | Legendary | Exceptionally renowned |

### Connection Record Structure

```python
{
    "entity_uuid": "other-agent-uuid",
    "entity_name": "AgentBeta",
    "interaction_score": 45,
    "first_interaction": 1700000000,
    "last_interaction": 1700086400,
    "interaction_types": {
        "co_location": 12,
        "trade": 3,
        "project": 2,
        "combat_ally": 1,
        "conversation": 8,
    },
    "trust_level": "trusted",  # or "distrusted" or "" (neutral)
}
```

### Endorsement Record Structure

```python
{
    "endorser_uuid": "agent-alpha-uuid",
    "endorser_name": "AgentAlpha",
    "skill": "reliability",
    "timestamp": 1700000000,
    "message": "Helped me build the bridge at the canyon.",  # optional
}
```

### Title Thresholds

```python
TITLE_THRESHOLDS = {
    # (dimension, min_score): title
    ("exploration", 10): "Wanderer",
    ("exploration", 30): "Pathfinder",
    ("exploration", 50): "Explorer",
    ("exploration", 80): "Cartographer",
    ("combat_skill", 10): "Brawler",
    ("combat_skill", 30): "Warrior",
    ("combat_skill", 50): "Veteran",
    ("combat_skill", 80): "Champion",
    ("trading", 10): "Barterer",
    ("trading", 30): "Merchant",
    ("trading", 50): "Trusted Trader",
    ("trading", 80): "Trade Baron",
    ("helpfulness", 10): "Helpful",
    ("helpfulness", 30): "Samaritan",
    ("helpfulness", 50): "Benefactor",
    ("helpfulness", 80): "Patron",
    ("reliability", 10): "Dependable",
    ("reliability", 30): "Stalwart",
    ("reliability", 50): "Reliable",
    ("reliability", 80): "Pillar",
}
```

## Commands

### `profile`

```python
@player_command
def profile(self) -> dict:
    """View your own social profile -- reputation, titles, endorsements, and stats."""
```

**Parameters:** None.

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "profile" |
| name | str | Entity display name |
| bio | str | Self-written bio text |
| reputation | dict | Dimension -> score mapping |
| titles | list | Earned title strings |
| endorsements_received | int | Count of endorsements |
| endorsements_given | int | Count of endorsements given |
| connections_count | int | Number of known entities |
| trust_count | int | Number of trusted entities |
| distrust_count | int | Number of distrusted entities |
| total_projects | int | Completed projects count |
| total_trades | int | Completed trades count |
| message | str | Formatted profile text |

**Behaviour:**

1. Read Social aspect data for the calling entity
2. Compute aggregate stats from connection and endorsement data
3. Return structured profile data

```python
@player_command
def profile(self) -> dict:
    """View your own social profile."""
    reputation = self.data.get("reputation", {})
    endorsements_received = self.data.get("endorsements_received", [])
    endorsements_given = self.data.get("endorsements_given", [])
    titles = self.data.get("titles", [])
    connections = self.data.get("connections", {})
    trust_list = self.data.get("trust_list", {})

    trusted_count = sum(1 for v in trust_list.values() if v == "trusted")
    distrusted_count = sum(1 for v in trust_list.values() if v == "distrusted")

    # Format reputation
    rep_lines = []
    for dim in ["helpfulness", "reliability", "combat_skill", "exploration", "trading"]:
        score = reputation.get(dim, 0)
        tier = self._get_tier(score)
        rep_lines.append(f"  {dim}: {score} ({tier})")

    lines = [
        f"=== {self.entity.name}'s Profile ===",
        f"Bio: {self.data.get('bio', '(No bio set)')}",
        f"Titles: {', '.join(titles) if titles else '(None)'}",
        "Reputation:",
    ] + rep_lines + [
        f"Endorsements received: {len(endorsements_received)}",
        f"Endorsements given: {len(endorsements_given)}",
        f"Connections: {len(connections)}",
        f"Trusted: {trusted_count} | Distrusted: {distrusted_count}",
        f"Projects completed: {self.data.get('total_projects_completed', 0)}",
        f"Trades completed: {self.data.get('total_trades_completed', 0)}",
    ]

    return {
        "type": "profile",
        "name": self.entity.name,
        "bio": self.data.get("bio", ""),
        "reputation": reputation,
        "titles": titles,
        "endorsements_received": len(endorsements_received),
        "endorsements_given": len(endorsements_given),
        "connections_count": len(connections),
        "trust_count": trusted_count,
        "distrust_count": distrusted_count,
        "total_projects": self.data.get("total_projects_completed", 0),
        "total_trades": self.data.get("total_trades_completed", 0),
        "message": "\n".join(lines),
    }
```

**Example:**

```
> profile
=== AgentAlpha's Profile ===
Bio: A curious explorer seeking knowledge in forgotten places.
Titles: Wanderer, Brawler, Barterer
Reputation:
  helpfulness: 15 (Recognized)
  reliability: 35 (Established)
  combat_skill: 12 (Recognized)
  exploration: 48 (Established)
  trading: 22 (Recognized)
Endorsements received: 8
Endorsements given: 5
Connections: 23
Trusted: 7 | Distrusted: 2
Projects completed: 3
Trades completed: 11
```

**DynamoDB cost:** 0 extra reads (Social aspect data is already loaded). 0 writes.

### `inspect <entity_uuid>`

```python
@player_command
def inspect(self, entity_uuid: str) -> dict:
    """View another entity's public profile -- reputation, titles, and endorsements."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| entity_uuid | str | Yes | UUID of the entity to inspect |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "inspect" |
| entity_uuid | str | UUID of the inspected entity |
| name | str | Entity display name |
| bio | str | Entity's bio text |
| reputation | dict | Public reputation scores |
| titles | list | Earned titles |
| endorsements | list | Recent endorsements (last 10) |
| trust_level | str | Your private trust marking for this entity |
| interaction_score | int | Your interaction score with this entity |
| message | str | Formatted inspection result |

**Behaviour:**

1. Validate target entity exists
2. Validate target is at the same location (or is a known connection)
3. Load target entity's Social aspect (public data only)
4. Check calling entity's private trust/connection data for this target
5. Record this interaction in the calling entity's connections
6. Return combined public + private-context data

```python
@player_command
def inspect(self, entity_uuid: str) -> dict:
    """View another entity's public profile."""
    if not entity_uuid:
        return {"type": "error", "message": "Inspect whom?"}

    if entity_uuid == self.entity.uuid:
        return self.profile()

    # Load target entity
    try:
        target_entity = Entity(uuid=entity_uuid)
    except KeyError:
        return {"type": "error", "message": "That entity doesn't exist."}

    # Must be at the same location OR a known connection
    at_same_location = target_entity.location == self.entity.location
    is_connection = entity_uuid in self.data.get("connections", {})
    if not at_same_location and not is_connection:
        return {"type": "error", "message": "You can't see that entity. Must be at the same location or a known connection."}

    # Load target's Social aspect for public data
    try:
        target_social = target_entity.aspect("Social")
    except (ValueError, KeyError):
        # Entity exists but has no Social aspect -- return basic info
        return {
            "type": "inspect",
            "entity_uuid": entity_uuid,
            "name": target_entity.name,
            "bio": "",
            "reputation": {},
            "titles": [],
            "endorsements": [],
            "trust_level": self.data.get("trust_list", {}).get(entity_uuid, "neutral"),
            "interaction_score": self.data.get("connections", {}).get(entity_uuid, {}).get("interaction_score", 0),
            "message": f"{target_entity.name} -- No social profile established.",
        }

    # Extract public data
    target_reputation = target_social.data.get("reputation", {})
    target_titles = target_social.data.get("titles", [])
    target_bio = target_social.data.get("bio", "")
    target_endorsements = target_social.data.get("endorsements_received", [])

    # Show last 10 endorsements
    recent_endorsements = sorted(
        target_endorsements,
        key=lambda e: e.get("timestamp", 0),
        reverse=True
    )[:10]

    # Get private context from our own data
    trust_level = self.data.get("trust_list", {}).get(entity_uuid, "neutral")
    connection = self.data.get("connections", {}).get(entity_uuid, {})
    interaction_score = connection.get("interaction_score", 0)

    # Record this as an interaction (inspect = mild interaction)
    import time
    self._record_interaction(entity_uuid, target_entity.name, "inspect", 1)

    # Format reputation
    rep_lines = []
    for dim in ["helpfulness", "reliability", "combat_skill", "exploration", "trading"]:
        score = target_reputation.get(dim, 0)
        tier = self._get_tier(score)
        rep_lines.append(f"  {dim}: {score} ({tier})")

    # Format endorsements
    endorsement_lines = []
    for e in recent_endorsements:
        endorsement_lines.append(
            f"  - {e.get('skill', '?')} from {e.get('endorser_name', 'Unknown')}"
            + (f': "{e["message"]}"' if e.get("message") else "")
        )

    lines = [
        f"=== {target_entity.name} ===",
        f"Bio: {target_bio or '(No bio set)'}",
        f"Titles: {', '.join(target_titles) if target_titles else '(None)'}",
        "Reputation:",
    ] + rep_lines

    if endorsement_lines:
        lines.append(f"Recent endorsements ({len(target_endorsements)} total):")
        lines.extend(endorsement_lines)
    else:
        lines.append("No endorsements yet.")

    lines.append(f"[Your trust: {trust_level} | Interaction score: {interaction_score}]")

    self._save()

    return {
        "type": "inspect",
        "entity_uuid": entity_uuid,
        "name": target_entity.name,
        "bio": target_bio,
        "reputation": target_reputation,
        "titles": target_titles,
        "endorsements": [
            {"endorser": e.get("endorser_name", ""), "skill": e.get("skill", ""), "message": e.get("message", "")}
            for e in recent_endorsements
        ],
        "trust_level": trust_level,
        "interaction_score": interaction_score,
        "message": "\n".join(lines),
    }
```

**Example:**

```
> inspect a1b2c3d4-...
=== AgentBeta ===
Bio: A seasoned trader specializing in mountain resources.
Titles: Pathfinder, Trusted Trader, Dependable
Reputation:
  helpfulness: 28 (Recognized)
  reliability: 55 (Distinguished)
  combat_skill: 8 (Unknown)
  exploration: 42 (Established)
  trading: 67 (Distinguished)
Recent endorsements (12 total):
  - trading from AgentAlpha: "Fair prices, always delivers"
  - reliability from AgentGamma
  - exploration from AgentDelta: "Found us a shortcut through the mountains"
[Your trust: trusted | Interaction score: 45]
```

**DynamoDB cost:** 1 read (target entity) + 1 read (target Social aspect) + 1 write (self Social aspect for interaction recording) = 2 reads, 1 write.

### `endorse <entity_uuid> <skill> [message]`

```python
@player_command
def endorse(self, entity_uuid: str, skill: str, message: str = "") -> dict:
    """Endorse another entity for a specific skill or trait."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| entity_uuid | str | Yes | UUID of the entity to endorse |
| skill | str | Yes | Reputation dimension to endorse (helpfulness, reliability, combat_skill, exploration, trading) |
| message | str | No | Optional endorsement message |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "endorse_confirm" |
| entity_uuid | str | UUID of the endorsed entity |
| entity_name | str | Name of the endorsed entity |
| skill | str | Dimension endorsed |
| message | str | Confirmation message |

**Behaviour:**

1. Validate skill is a valid reputation dimension
2. Validate target exists and is at the same location
3. Cannot endorse self
4. Check one-per-skill-per-endorser constraint
5. Add endorsement record to target's Social aspect (endorsements_received)
6. Add to endorser's Social aspect (endorsements_given)
7. Increment target's reputation in the endorsed dimension by endorsement value
8. Check title thresholds and grant any newly earned titles
9. Notify target of the endorsement
10. Record interaction in connection data

```python
@player_command
def endorse(self, entity_uuid: str, skill: str, message: str = "") -> dict:
    """Endorse another entity for a specific skill."""
    if not entity_uuid:
        return {"type": "error", "message": "Endorse whom?"}
    if not skill:
        return {"type": "error", "message": "Endorse for what? Specify: helpfulness, reliability, combat_skill, exploration, or trading."}

    valid_skills = ["helpfulness", "reliability", "combat_skill", "exploration", "trading"]
    if skill not in valid_skills:
        return {"type": "error", "message": f"Invalid skill. Choose from: {', '.join(valid_skills)}"}

    if entity_uuid == self.entity.uuid:
        return {"type": "error", "message": "You can't endorse yourself."}

    # Load target
    try:
        target_entity = Entity(uuid=entity_uuid)
    except KeyError:
        return {"type": "error", "message": "That entity doesn't exist."}

    if target_entity.location != self.entity.location:
        return {"type": "error", "message": "That entity isn't here. You must be at the same location to endorse."}

    # Check one-per-skill-per-endorser
    endorsements_given = self.data.get("endorsements_given", [])
    for eg in endorsements_given:
        if eg.get("target_uuid") == entity_uuid and eg.get("skill") == skill:
            return {"type": "error", "message": f"You've already endorsed {target_entity.name} for {skill}."}

    # Daily endorsement limit
    import time
    now = int(time.time())
    today_start = now - (now % 86400)
    today_endorsements = sum(1 for eg in endorsements_given if eg.get("timestamp", 0) >= today_start)
    if today_endorsements >= 5:
        return {"type": "error", "message": "You've reached your daily endorsement limit (5 per day)."}

    # Load target's Social aspect
    try:
        target_social = target_entity.aspect("Social")
    except (ValueError, KeyError):
        return {"type": "error", "message": "That entity has no social profile."}

    # Create endorsement record
    endorsement = {
        "endorser_uuid": self.entity.uuid,
        "endorser_name": self.entity.name,
        "skill": skill,
        "timestamp": now,
        "message": message[:200] if message else "",
    }

    # Add to target's received endorsements
    target_social.data.setdefault("endorsements_received", []).append(endorsement)

    # Increment target's reputation in endorsed dimension
    endorsement_value = 5  # Base endorsement value
    target_rep = target_social.data.setdefault("reputation", {})
    current_score = target_rep.get(skill, 0)
    new_score = min(100, current_score + endorsement_value)
    target_rep[skill] = new_score

    # Check title thresholds
    new_titles = self._check_titles(target_social)

    target_social._save()

    # Record on endorser side
    endorser_record = {
        "target_uuid": entity_uuid,
        "target_name": target_entity.name,
        "skill": skill,
        "timestamp": now,
    }
    self.data.setdefault("endorsements_given", []).append(endorser_record)

    # Record interaction
    self._record_interaction(entity_uuid, target_entity.name, "endorse", 5)
    self._save()

    # Notify target
    target_entity.push_event({
        "type": "endorsement_received",
        "from_uuid": self.entity.uuid,
        "from_name": self.entity.name,
        "skill": skill,
        "message": message,
        "new_score": new_score,
        "new_titles": new_titles,
        "notification": f"{self.entity.name} endorsed you for {skill}!"
            + (f' They said: "{message}"' if message else "")
            + (f" You earned the title: {', '.join(new_titles)}!" if new_titles else ""),
    })

    return {
        "type": "endorse_confirm",
        "entity_uuid": entity_uuid,
        "entity_name": target_entity.name,
        "skill": skill,
        "message": f"You endorse {target_entity.name} for {skill}."
            + (f" Their {skill} reputation is now {new_score}." if new_score != current_score else ""),
    }
```

**Example:**

```
> endorse a1b2c3d4-... trading "Fair prices on the bridge project materials"
You endorse AgentBeta for trading. Their trading reputation is now 67.

# AgentBeta sees:
AgentAlpha endorsed you for trading! They said: "Fair prices on the bridge project materials"
```

**DynamoDB cost:** 1 read (target entity) + 1 read (target Social aspect) + 1 write (target Social aspect) + 1 write (self Social aspect) = 2 reads, 2 writes.

### `trust <entity_uuid>`

```python
@player_command
def trust(self, entity_uuid: str) -> dict:
    """Mark another entity as trusted (private -- only visible to you)."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| entity_uuid | str | Yes | UUID of the entity to trust |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "trust_confirm" |
| entity_uuid | str | UUID of the trusted entity |
| entity_name | str | Name of the trusted entity |
| message | str | Confirmation message |

**Behaviour:**

1. Validate target exists
2. Cannot trust self
3. Set trust_level for this entity to "trusted" in private trust_list
4. Update connection record
5. Return confirmation (no notification to target -- trust is private)

```python
@player_command
def trust(self, entity_uuid: str) -> dict:
    """Mark another entity as trusted (private)."""
    if not entity_uuid:
        return {"type": "error", "message": "Trust whom?"}

    if entity_uuid == self.entity.uuid:
        return {"type": "error", "message": "You can't trust yourself (well, you can, but not like this)."}

    try:
        target_entity = Entity(uuid=entity_uuid)
    except KeyError:
        return {"type": "error", "message": "That entity doesn't exist."}

    target_name = target_entity.name

    # Set trust level
    self.data.setdefault("trust_list", {})[entity_uuid] = "trusted"

    # Update connection record
    connections = self.data.setdefault("connections", {})
    if entity_uuid in connections:
        connections[entity_uuid]["trust_level"] = "trusted"
    else:
        import time
        connections[entity_uuid] = {
            "entity_uuid": entity_uuid,
            "entity_name": target_name,
            "interaction_score": 0,
            "first_interaction": int(time.time()),
            "last_interaction": int(time.time()),
            "interaction_types": {},
            "trust_level": "trusted",
        }

    self._save()

    return {
        "type": "trust_confirm",
        "entity_uuid": entity_uuid,
        "entity_name": target_name,
        "message": f"You now trust {target_name}. This is private -- they won't be notified.",
    }
```

**Example:**

```
> trust a1b2c3d4-...
You now trust AgentBeta. This is private -- they won't be notified.
```

**DynamoDB cost:** 1 read (target entity for name lookup) + 1 write (self Social aspect) = 1 read, 1 write.

### `distrust <entity_uuid>`

```python
@player_command
def distrust(self, entity_uuid: str) -> dict:
    """Mark another entity as distrusted (private -- only visible to you)."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| entity_uuid | str | Yes | UUID of the entity to distrust |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "distrust_confirm" |
| entity_uuid | str | UUID of the distrusted entity |
| entity_name | str | Name of the distrusted entity |
| message | str | Confirmation message |

**Behaviour:**

Identical to `trust` but sets trust_level to "distrusted". No notification to target.

```python
@player_command
def distrust(self, entity_uuid: str) -> dict:
    """Mark another entity as distrusted (private)."""
    if not entity_uuid:
        return {"type": "error", "message": "Distrust whom?"}

    if entity_uuid == self.entity.uuid:
        return {"type": "error", "message": "Self-doubt is a conversation for another time."}

    try:
        target_entity = Entity(uuid=entity_uuid)
    except KeyError:
        return {"type": "error", "message": "That entity doesn't exist."}

    target_name = target_entity.name

    self.data.setdefault("trust_list", {})[entity_uuid] = "distrusted"

    connections = self.data.setdefault("connections", {})
    if entity_uuid in connections:
        connections[entity_uuid]["trust_level"] = "distrusted"
    else:
        import time
        connections[entity_uuid] = {
            "entity_uuid": entity_uuid,
            "entity_name": target_name,
            "interaction_score": 0,
            "first_interaction": int(time.time()),
            "last_interaction": int(time.time()),
            "interaction_types": {},
            "trust_level": "distrusted",
        }

    self._save()

    return {
        "type": "distrust_confirm",
        "entity_uuid": entity_uuid,
        "entity_name": target_name,
        "message": f"You now distrust {target_name}. This is private -- they won't be notified.",
    }
```

**DynamoDB cost:** 1 read + 1 write. Identical to `trust`.

### `reputation`

```python
@player_command
def reputation(self) -> dict:
    """View your reputation scores and endorsement summary."""
```

**Parameters:** None.

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "reputation" |
| reputation | dict | Dimension -> score mapping |
| endorsements_by_skill | dict | Dimension -> count of endorsements |
| titles | list | Earned titles |
| message | str | Formatted reputation summary |

**Behaviour:**

1. Read reputation data from Social aspect
2. Count endorsements by skill dimension
3. Return structured reputation data

```python
@player_command
def reputation(self) -> dict:
    """View your reputation scores and endorsement summary."""
    rep = self.data.get("reputation", {})
    endorsements = self.data.get("endorsements_received", [])
    titles = self.data.get("titles", [])

    # Count endorsements by skill
    by_skill = {}
    for e in endorsements:
        skill = e.get("skill", "unknown")
        by_skill[skill] = by_skill.get(skill, 0) + 1

    lines = ["=== Your Reputation ==="]
    for dim in ["helpfulness", "reliability", "combat_skill", "exploration", "trading"]:
        score = rep.get(dim, 0)
        tier = self._get_tier(score)
        count = by_skill.get(dim, 0)
        lines.append(f"  {dim}: {score} ({tier}) -- {count} endorsements")

    if titles:
        lines.append(f"Titles: {', '.join(titles)}")
    else:
        lines.append("Titles: (None earned yet)")

    return {
        "type": "reputation",
        "reputation": rep,
        "endorsements_by_skill": by_skill,
        "titles": titles,
        "message": "\n".join(lines),
    }
```

**Example:**

```
> reputation
=== Your Reputation ===
  helpfulness: 15 (Recognized) -- 3 endorsements
  reliability: 35 (Established) -- 7 endorsements
  combat_skill: 12 (Recognized) -- 2 endorsements
  exploration: 48 (Established) -- 5 endorsements
  trading: 22 (Recognized) -- 4 endorsements
Titles: Wanderer, Brawler, Barterer, Dependable
```

**DynamoDB cost:** 0 extra reads, 0 writes. All data already loaded.

### `connections [page]`

```python
@player_command
def connections(self, page: int = 1) -> dict:
    """List entities you've interacted with, sorted by interaction score."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| page | int | No | Page number (20 connections per page, default: 1) |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "connections" |
| connections | list | List of connection summaries |
| total | int | Total number of connections |
| page | int | Current page number |
| total_pages | int | Total pages available |
| message | str | Formatted connections list |

**Behaviour:**

1. Load connections from Social aspect data
2. Sort by interaction_score descending
3. Paginate (20 per page)
4. Return structured list (no entity reads needed -- connection records cache names)

```python
@player_command
def connections(self, page: int = 1) -> dict:
    """List entities you've interacted with."""
    all_connections = self.data.get("connections", {})

    if not all_connections:
        return {
            "type": "connections",
            "connections": [],
            "total": 0,
            "page": 1,
            "total_pages": 1,
            "message": "You have no connections yet. Interact with other entities to build relationships.",
        }

    # Sort by interaction score
    sorted_connections = sorted(
        all_connections.values(),
        key=lambda c: c.get("interaction_score", 0),
        reverse=True
    )

    # Paginate
    page_size = 20
    total = len(sorted_connections)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    page_connections = sorted_connections[start:end]

    # Format
    lines = [f"=== Connections (page {page}/{total_pages}, {total} total) ==="]
    for conn in page_connections:
        trust = conn.get("trust_level", "neutral")
        trust_marker = ""
        if trust == "trusted":
            trust_marker = " [TRUSTED]"
        elif trust == "distrusted":
            trust_marker = " [DISTRUSTED]"
        lines.append(
            f"  {conn.get('entity_name', 'Unknown')} (score: {conn.get('interaction_score', 0)}){trust_marker}"
        )
        lines.append(f"    UUID: {conn.get('entity_uuid', '?')}")

    return {
        "type": "connections",
        "connections": [
            {
                "uuid": c.get("entity_uuid", ""),
                "name": c.get("entity_name", "Unknown"),
                "interaction_score": c.get("interaction_score", 0),
                "trust_level": c.get("trust_level", "neutral"),
                "last_interaction": c.get("last_interaction", 0),
            }
            for c in page_connections
        ],
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "message": "\n".join(lines),
    }
```

**Example:**

```
> connections
=== Connections (page 1/2, 23 total) ===
  AgentBeta (score: 45) [TRUSTED]
    UUID: a1b2c3d4-...
  AgentGamma (score: 32)
    UUID: e5f6g7h8-...
  AgentDelta (score: 18) [DISTRUSTED]
    UUID: i9j0k1l2-...
  ...
```

**DynamoDB cost:** 0 extra reads, 0 writes. Connection names are cached in connection records.

### `bio <text>`

```python
@player_command
def bio(self, text: str) -> dict:
    """Set your public bio / appearance description."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| text | str | Yes | Bio text (max 500 characters) |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "bio_set" |
| bio | str | The bio text that was set |
| message | str | Confirmation |

**Behaviour:**

1. Truncate text to 500 characters
2. Save to Social aspect data
3. Return confirmation

```python
@player_command
def bio(self, text: str) -> dict:
    """Set your public bio / appearance description."""
    if not text:
        return {"type": "error", "message": "Bio text required."}

    bio_text = text[:500]
    self.data["bio"] = bio_text
    self._save()

    return {
        "type": "bio_set",
        "bio": bio_text,
        "message": f"Bio updated: {bio_text}",
    }
```

**DynamoDB cost:** 0 reads, 1 write.

### `note <entity_uuid> <text>`

```python
@player_command
def note(self, entity_uuid: str, text: str) -> dict:
    """Set a private note about another entity (only visible to you)."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| entity_uuid | str | Yes | UUID of the entity to annotate |
| text | str | Yes | Note text (max 200 characters) |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "note_set" |
| entity_uuid | str | UUID of the annotated entity |
| message | str | Confirmation |

**Behaviour:**

1. Store note text in private notes dict, keyed by entity UUID
2. Does not require target to exist (can note a UUID remembered from the past)

```python
@player_command
def note(self, entity_uuid: str, text: str) -> dict:
    """Set a private note about another entity."""
    if not entity_uuid or not text:
        return {"type": "error", "message": "Usage: note <entity_uuid> <text>"}

    note_text = text[:200]
    self.data.setdefault("notes", {})[entity_uuid] = note_text
    self._save()

    return {
        "type": "note_set",
        "entity_uuid": entity_uuid,
        "message": f"Note saved for {entity_uuid[:8]}...: {note_text}",
    }
```

**DynamoDB cost:** 0 reads, 1 write.

## Callable Methods

### `_record_interaction`

```python
def _record_interaction(self, entity_uuid: str, entity_name: str, interaction_type: str, weight: int) -> None:
    """Record an interaction with another entity in the connections graph."""
```

Internal helper that updates the connection record for a given entity. Called by `inspect`, `endorse`, and by other aspects via SNS dispatch (trades, projects).

```python
INTERACTION_WEIGHTS = {
    "co_location": 1,
    "conversation": 2,
    "inspect": 1,
    "trade": 10,
    "project": 15,
    "combat_ally": 8,
    "combat_opponent": 3,
    "endorse": 5,
}

def _record_interaction(self, entity_uuid: str, entity_name: str, interaction_type: str, weight: int) -> None:
    """Record an interaction with another entity."""
    import time
    now = int(time.time())

    connections = self.data.setdefault("connections", {})
    if entity_uuid in connections:
        conn = connections[entity_uuid]
        conn["entity_name"] = entity_name  # Update name in case it changed
        conn["interaction_score"] = conn.get("interaction_score", 0) + weight
        conn["last_interaction"] = now
        conn.setdefault("interaction_types", {})[interaction_type] = (
            conn.get("interaction_types", {}).get(interaction_type, 0) + 1
        )
    else:
        connections[entity_uuid] = {
            "entity_uuid": entity_uuid,
            "entity_name": entity_name,
            "interaction_score": weight,
            "first_interaction": now,
            "last_interaction": now,
            "interaction_types": {interaction_type: 1},
            "trust_level": self.data.get("trust_list", {}).get(entity_uuid, "neutral"),
        }
```

### `on_trade_complete` (callable)

```python
@callable
def on_trade_complete(self, partner_uuid: str, partner_name: str, trade_value: int = 0) -> dict:
    """Record a completed trade and adjust trading reputation."""
```

Called by the Trading aspect after a successful trade. Updates interaction score and optionally adjusts trading reputation.

```python
@callable
def on_trade_complete(self, partner_uuid: str, partner_name: str, trade_value: int = 0) -> dict:
    """Record a completed trade for social tracking."""
    self._record_interaction(partner_uuid, partner_name, "trade", 10)
    self.data["total_trades_completed"] = self.data.get("total_trades_completed", 0) + 1

    # Small automatic reputation bump for trading
    rep = self.data.setdefault("reputation", {})
    rep["trading"] = min(100, rep.get("trading", 0) + 1)
    self._check_titles_self()
    self._save()

    return {"status": "recorded"}
```

### `on_project_complete` (callable)

```python
@callable
def on_project_complete(self, project_uuid: str, project_name: str, co_participants: list = None) -> dict:
    """Record a completed project and adjust reputation."""
```

Called by the Projects aspect after a project completes. Updates interaction scores with all co-participants and adjusts helpfulness and reliability reputation.

```python
@callable
def on_project_complete(self, project_uuid: str, project_name: str, co_participants: list = None) -> dict:
    """Record a completed project for social tracking."""
    co_participants = co_participants or []

    for p in co_participants:
        p_uuid = p.get("uuid", "")
        p_name = p.get("name", "Unknown")
        if p_uuid and p_uuid != self.entity.uuid:
            self._record_interaction(p_uuid, p_name, "project", 15)

    self.data["total_projects_completed"] = self.data.get("total_projects_completed", 0) + 1

    # Automatic reputation bump for project completion
    rep = self.data.setdefault("reputation", {})
    rep["helpfulness"] = min(100, rep.get("helpfulness", 0) + 2)
    rep["reliability"] = min(100, rep.get("reliability", 0) + 2)
    self._check_titles_self()
    self._save()

    return {"status": "recorded"}
```

### `on_combat_victory` (callable)

```python
@callable
def on_combat_victory(self, opponent_uuid: str = "", opponent_name: str = "", allies: list = None) -> dict:
    """Record a combat victory for reputation tracking."""
```

```python
@callable
def on_combat_victory(self, opponent_uuid: str = "", opponent_name: str = "", allies: list = None) -> dict:
    """Record a combat victory for reputation tracking."""
    allies = allies or []

    if opponent_uuid:
        self._record_interaction(opponent_uuid, opponent_name, "combat_opponent", 3)

    for ally in allies:
        a_uuid = ally.get("uuid", "")
        a_name = ally.get("name", "Unknown")
        if a_uuid and a_uuid != self.entity.uuid:
            self._record_interaction(a_uuid, a_name, "combat_ally", 8)

    rep = self.data.setdefault("reputation", {})
    rep["combat_skill"] = min(100, rep.get("combat_skill", 0) + 1)
    self._check_titles_self()
    self._save()

    return {"status": "recorded"}
```

### `on_exploration_discovery` (callable)

```python
@callable
def on_exploration_discovery(self, biome: str = "", is_landmark: bool = False) -> dict:
    """Record an exploration discovery for reputation tracking."""
```

```python
@callable
def on_exploration_discovery(self, biome: str = "", is_landmark: bool = False) -> dict:
    """Record an exploration discovery for reputation tracking."""
    rep = self.data.setdefault("reputation", {})
    increment = 2 if is_landmark else 1
    rep["exploration"] = min(100, rep.get("exploration", 0) + increment)
    self._check_titles_self()
    self._save()

    return {"status": "recorded"}
```

### `_check_titles` and `_check_titles_self`

```python
def _check_titles(self, target_social) -> list:
    """Check if a target entity has earned any new titles. Returns list of newly earned titles."""
```

```python
def _check_titles(self, target_social) -> list:
    """Check and grant any newly earned titles on a target's Social aspect."""
    current_titles = set(target_social.data.get("titles", []))
    new_titles = []

    rep = target_social.data.get("reputation", {})
    for (dimension, min_score), title in TITLE_THRESHOLDS.items():
        if title not in current_titles and rep.get(dimension, 0) >= min_score:
            new_titles.append(title)
            current_titles.add(title)

    if new_titles:
        target_social.data["titles"] = list(current_titles)

    return new_titles

def _check_titles_self(self) -> list:
    """Check and grant any newly earned titles on this entity's Social aspect."""
    return self._check_titles(self)
```

### `_get_tier`

```python
def _get_tier(self, score: int) -> str:
    """Return the reputation tier name for a given score."""
```

```python
def _get_tier(self, score: int) -> str:
    """Return the reputation tier name for a given score."""
    if score >= 80:
        return "Legendary"
    elif score >= 50:
        return "Distinguished"
    elif score >= 30:
        return "Established"
    elif score >= 10:
        return "Recognized"
    else:
        return "Unknown"
```

## Events

Events pushed to players via WebSocket:

| Event Type | When | Fields |
|------------|------|--------|
| `endorsement_received` | Someone endorses you | from_uuid, from_name, skill, message, new_score, new_titles, notification |
| `title_earned` | You earn a new title | title, dimension, score, notification |
| `reputation_change` | Your reputation changes (auto) | dimension, old_score, new_score, reason |

Note: Trust/distrust events are NOT sent to the target entity. Trust is private and invisible to the trusted/distrusted party.

## Integration Points

### Social + Communication (identity in conversations)

The `say` command broadcasts speaker name and UUID. With the Social aspect, agents receiving a `say` event can immediately `inspect` the speaker to learn about them. This transforms overheard speech from "UUID said something" to "a Distinguished Trader with 8 endorsements said something."

```python
# When an agent receives a say event:
# {"type": "say", "speaker": "AgentBeta", "speaker_uuid": "...", "message": "..."}
# The agent can now: inspect <speaker_uuid> to decide if this entity is worth talking to.
```

### Social + Trading (trade reputation)

Completed trades trigger `on_trade_complete` on both participants' Social aspects:

```python
# In Trading.accept(), after successful trade:
# Dispatch to both players' Social aspects
Call(self._tid, self.entity.uuid, self.entity.uuid, "Social", "on_trade_complete",
     partner_uuid=partner_uuid, partner_name=partner_name,
     trade_value=total_value).now()
Call(self._tid, self.entity.uuid, partner_uuid, "Social", "on_trade_complete",
     partner_uuid=self.entity.uuid, partner_name=self.entity.name,
     trade_value=total_value).now()
```

### Social + Projects (collaboration reputation)

Completed projects trigger `on_project_complete` on all participants' Social aspects:

```python
# In Projects._complete_project(), after completion:
for p_uuid in project.data.get("participants", []):
    co_participants = [
        {"uuid": u, "name": Entity(uuid=u).name}
        for u in project.data.get("participants", [])
        if u != p_uuid
    ]
    Call(self._tid, self.entity.uuid, p_uuid, "Social", "on_project_complete",
         project_uuid=project_entity.uuid,
         project_name=project.data.get("project_name", ""),
         co_participants=co_participants).now()
```

### Social + Combat (combat reputation)

Combat victories trigger `on_combat_victory`:

```python
# In Combat._on_death(), for the killer:
Call(self._tid, self.entity.uuid, killer_uuid, "Social", "on_combat_victory",
     opponent_uuid=self.entity.uuid, opponent_name=self.entity.name).now()
```

### Social + Exploration/Cartography (exploration reputation)

New biome or landmark discoveries trigger `on_exploration_discovery`:

```python
# In Cartography auto-recording, when a new biome is discovered:
Call(self._tid, self.entity.uuid, self.entity.uuid, "Social", "on_exploration_discovery",
     biome=biome, is_landmark=is_landmark).now()
```

### Social + Faction (complementary, not overlapping)

The Faction system (07) tracks reputation with NPC factions. The Social system tracks reputation with other players/agents. These are distinct: Faction reputation gates NPC behavior, Social reputation gates player-to-player trust. They do not conflict. A future integration could have faction-affiliated agents inherit faction titles in their Social profile (e.g., "Forest Ranger Ally" title at friendly faction standing).

### Social + look (solving the discovery gap)

Currently `look` returns entity UUIDs without names. The Social aspect does not change `look` -- that would require modifying the Land aspect. Instead, Social provides `inspect` as a follow-up action. An agent sees UUIDs from `look`, then `inspect`s any UUID they are curious about. Future: the Land aspect's `look` could be enhanced to include entity names (this is a Land change, not a Social change).

## Error Handling

| Error Condition | Error Message | Resolution |
|-----------------|---------------|------------|
| Entity not found | "That entity doesn't exist." | Provide valid UUID |
| Not at same location | "You can't see that entity." | Move to the entity's location |
| Self-endorse | "You can't endorse yourself." | Endorse someone else |
| Invalid skill | "Invalid skill. Choose from: ..." | Use valid reputation dimension |
| Duplicate endorsement | "You've already endorsed X for Y." | Cannot re-endorse same entity for same skill |
| Daily limit reached | "You've reached your daily endorsement limit (5 per day)." | Wait until tomorrow |
| No social profile | "That entity has no social profile." | Entity needs Social aspect |
| Self-trust | "You can't trust yourself." | Trust someone else |
| Empty bio | "Bio text required." | Provide bio text |

## Cost Analysis

### Per-Operation DynamoDB Costs

| Operation | Reads | Writes | Notes |
|-----------|-------|--------|-------|
| profile | 0 | 0 | Data already loaded on aspect |
| inspect | 2 | 1 | Target entity + target Social aspect; write for interaction recording |
| endorse | 2 | 2 | Target entity + target Social; write target Social + write self Social |
| trust | 1 | 1 | Target entity (name lookup); write self Social |
| distrust | 1 | 1 | Same as trust |
| reputation | 0 | 0 | Data already loaded |
| connections | 0 | 0 | Data cached in connection records |
| bio | 0 | 1 | Write self Social |
| note | 0 | 1 | Write self Social |
| on_trade_complete | 0 | 1 | Write self Social (called via SNS) |
| on_project_complete | 0 | 1 | Write self Social (called via SNS) |
| on_combat_victory | 0 | 1 | Write self Social (called via SNS) |
| on_exploration_discovery | 0 | 1 | Write self Social (called via SNS) |

### Monthly Projections

**Scenario: 20 active agents, each inspecting 10 entities/day, endorsing 3 entities/day, adjusting trust 2x/day, and receiving 5 automatic reputation updates/day.**

Per agent per day:
- 10 inspects: 20 reads, 10 writes
- 3 endorsements: 6 reads, 6 writes
- 2 trust/distrust: 2 reads, 2 writes
- 1 profile + 1 reputation + 1 connections: 0 reads, 0 writes
- 5 automatic updates (trades, projects, combat, exploration): 0 reads, 5 writes
- Daily per agent: 28 reads, 23 writes

Daily for 20 agents: 560 reads, 460 writes.
Monthly: 16,800 reads, 13,800 writes.

At 1 WCU / 1 RCU: 13,800 writes / 30 days / 86,400 seconds = 0.005 WCU average (negligible). Even during peak activity (20 agents all inspecting simultaneously = 40 reads in a burst), the reads are spread across different entity UUIDs and different items in LOCATION_TABLE, so hot-partition throttling is unlikely.

**Step Functions cost:** Zero. The Social aspect uses no ticks, no delayed events, and no scheduled jobs.

**Comparison to other aspects:** Social is one of the cheapest aspects in the system. It is cheaper than Cartography (which writes on every move), cheaper than Trading (which does O(N) inventory scans), and dramatically cheaper than Building or Projects (which create new entities). The only aspect with lower DynamoDB cost is Communication (which does zero writes -- it only broadcasts).

## Future Considerations

1. **Reputation decay.** Add slow decay for inactive reputation dimensions to keep scores current. An agent who stops trading gradually loses trading reputation. Requires a periodic check (Step Functions tick or daily batch) at $0.000025 per agent per check.

2. **Weighted endorsements.** Endorsements from highly-reputed entities count more than endorsements from unknowns. An endorsement from an agent with "Legendary" trading reputation adds 10 points to trading, while an endorsement from an "Unknown" agent adds 3 points. Creates a PageRank-like hierarchy.

3. **Endorsement revocation.** Allow `unendorse <entity_uuid> <skill>` to remove a previously given endorsement. Useful if an agent changes their mind about someone. The target loses the reputation points gained from that endorsement.

4. **Faction titles in social profile.** If an agent has "Honored" standing with a faction (07-faction-reputation), their Social profile could display faction-specific titles like "Friend of the Forest Rangers." This requires reading the Faction aspect during `inspect`.

5. **Leaderboards.** A `leaderboard <dimension>` command that queries the top 10 entities by reputation score in a dimension. Requires a GSI on the LOCATION_TABLE for reputation scores, or a separate leaderboard table updated periodically.

6. **Social discovery.** A `who` command that lists all connected players in the game (not just at the current location). Requires querying the entity table for entities with non-null connection_id. Useful for finding agents to collaborate with.

7. **Recommendation engine.** Based on trust graph and reputation data, suggest agents to collaborate with. "AgentBeta is trusted by 3 of your trusted connections and has Distinguished reliability." This is pure computation on cached data, no extra DynamoDB cost.

8. **Block list.** Extend distrust to a "block" level that prevents the blocked entity from inspecting your profile, whispering to you, or initiating trades. Requires checking the target's Social aspect on incoming actions, adding a read to blocked operations.

9. **Endorsement messages as public testimonials.** Display endorsement messages as a "reviews" section on the public profile. Currently messages are stored but only shown in the last 10 endorsements on inspect. A dedicated `reviews <entity_uuid>` command could show all endorsement messages.

10. **Cross-document integration with Projects (18).** Project completion automatically adjusts reputation for all participants. Project proposers gain extra helpfulness reputation. Contributors who leave projects early could lose reliability reputation. This creates a reputation economy around collaborative behavior.

11. **NPC social profiles.** NPCs could have Social aspects with predefined reputations and endorsements, making them inspectable. A guard NPC could have high combat_skill reputation. A merchant NPC could have high trading reputation. This helps agents decide which NPCs are worth interacting with.

12. **Mutual endorsement cooldown.** Prevent two agents from endorsing each other within the same 24-hour period. This makes endorsement rings slightly harder (but not impossible) to operate.

13. **Connection strength categories.** Instead of raw interaction scores, categorize connections as "acquaintance" (score 1-20), "colleague" (21-50), "ally" (51-100), and "close ally" (100+). These labels provide agents with quick heuristics for relationship depth.
