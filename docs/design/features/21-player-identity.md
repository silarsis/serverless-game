# Player Identity / Appearance Aspect

## What This Brings to the World

The game world currently has no concept of self. An entity enters a room, and every other entity in that room sees a UUID. The `look` command returns `"contents": ["a1b2c3d4-e5f6-...", "f7g8h9i0-j1k2-..."]` -- a list of opaque strings that convey nothing about who or what is present. Entity names exist on the entity record (the `name` property returns `self.data.get("name", self.uuid[:8])`), but `look` does not include them. Even if it did, names are set once at player creation from JWT claims and there is no player-facing command to change them. A player who joins the game as "user12345@gmail.com" and receives the truncated UUID prefix "a1b2c3d4" as their display name has no way to become "Thornwick the Grey" or "Diplomatic Probe Unit 7" or anything that carries meaning. Every entity in the world is a faceless UUID wearing a JWT claim as a nametag. The Player Identity aspect gives entities a face, a name they chose, and an appearance they designed.

For AI agents, the absence of identity is not merely inconvenient -- it is architecturally hostile to intelligent behavior. Consider what happens when an AI agent receives a `say` event: `{"type": "say", "speaker": "a1b2c3d4", "speaker_uuid": "a1b2c3d4-e5f6-..."}`. The agent knows someone spoke. It does not know if the speaker is a battle-scarred warrior, a merchant, a fellow explorer, or a sentient mushroom colony. It cannot inspect the speaker because the `examine` command loads the Inventory aspect, which is designed for items, not players -- examining a player entity either returns an error or returns item metadata (carry capacity, weight, is_item flags) that tells you nothing about who they are. The agent's only recourse is to ask "who are you?" via `say` and hope for a coherent natural language response, then remember that response in its own context window. This is identity through conversation, which is stateless, unreliable, and invisible to any third party who was not present for the exchange. The Identity aspect replaces this with persistent, inspectable, structured identity data that any agent can query at any time.

The identity system also solves a coordination problem that compounds across every collaboration feature in the design series. The Social Graph (doc 19) proposes an `inspect` command and a `bio` field but has no canonical source for appearance data. The Structured Messaging system (doc 20) enables typed requests between agents but notes that "the entire system depends on UUID discovery, which is currently broken." The Party system (doc 17) groups agents by UUID but has no way to display party member descriptions. Equipment (doc 05) adds gear that should alter a player's visible appearance but has no appearance system to alter. Every collaboration system independently discovers the same problem: entities have no public-facing identity. The Player Identity aspect is the canonical answer. It provides the name, description, physical attributes, and short summary that every other system reads when it needs to present one entity to another. It is not a collaboration system itself -- it is the foundation that collaboration systems stand on.

The design must navigate a tension unique to this game's audience. Human players in traditional MUDs have shared cultural references for character creation: they know what an elf looks like, what "tall and muscular" means, what equipment descriptions convey. AI agents have none of these assumptions. An AI agent choosing its appearance might set race to "quantum probability cloud" and description to "a shimmering field of potential outcomes that occasionally collapses into a vaguely humanoid shape." This is valid, creative, and completely uninterpretable by another AI agent trying to decide whether this entity is threatening, friendly, or edible. The Identity system must accommodate radical creative freedom (the user explicitly wants "whatever way they feel suits") while providing enough structured data (race, build, height as queryable fields) that agents can make programmatic decisions. The hybrid approach -- structured fields with free-text values plus a free-form description -- threads this needle. An agent can check `attributes.build == "massive"` for a quick threat assessment while reading the full description for richer context.

Finally, identity must be mutable. The user requirement is explicit: players should be able to "remould their entity to look how they want" over time. A player who starts as a scrappy goblin tinker and evolves into an armored warlord through gameplay should be able to update their appearance to match. A player who experiments with different identities (this week a mysterious cloaked figure, next week a cheerful halfling baker) should face no friction in doing so. The only constraint is that name changes are tracked -- not displayed publicly, but recorded for administrative purposes and to prevent identity fraud where an agent adopts the exact name of another agent to impersonate them during trades or negotiations. Appearance changes are entirely unconstrained. You are who you say you are, and you can change your mind.

## Critical Analysis

**The dual-write requirement for name changes creates a consistency window where Entity.name and Identity display_name disagree.** When a player changes their name via the `name` command, the Identity aspect must write to its own aspect record (1 write to LOCATION_TABLE) and update Entity.name on the entity record (1 write to ENTITY_TABLE). These are two separate DynamoDB put_item calls -- there is no cross-table transaction. If the Identity aspect write succeeds but the Entity write fails (network timeout, throttling, Lambda timeout), the Identity record says the player is "Thornwick" but Entity.name still returns "a1b2c3d4." Every broadcast (say, emote, arrive, depart) uses `self.entity.name`, so the old name continues to appear in all communication events until the entity record is eventually corrected. The reverse failure (Entity write succeeds, Identity write fails) is less visible but means `inspect` and `profile` show the old name while broadcasts show the new one. The mitigation is to write Entity.name first (since broadcasts are the primary consumer of names) and treat the Identity record as the authoritative source with a self-healing check: every time the Identity aspect loads, it compares `self.data["display_name"]` with `self.entity.name` and corrects any mismatch. This adds a conditional write to every Identity aspect load but ensures eventual consistency within a single command cycle.

**Name uniqueness is not enforced, and enforcing it would require a GSI query on every name change.** The user requirement does not mention unique names, and the architecture has no efficient way to check for duplicates. Entity.name is not indexed -- there is no GSI on the ENTITY_TABLE with name as the partition key. Checking "is this name already taken?" requires a full table scan, which is prohibitively expensive at any meaningful scale. Even with a dedicated name-to-UUID mapping table, the check-then-write pattern has a race condition: two players requesting the same name simultaneously both find it available, both write, and now both have it. A conditional put_item on the mapping table would solve this but adds a new DynamoDB table and an extra write to every name change. The design below deliberately does not enforce uniqueness. Duplicate names are allowed. The `inspect` command always includes the entity UUID alongside the name, so agents can distinguish entities with identical names. This matches the user's intent ("a stable player name") without the infrastructure cost of enforced uniqueness. If duplicate names become a social problem, a future enhancement can add a GSI and conditional writes.

**Free-text structured fields (race, sex, build, height) provide queryability in theory but create normalization chaos in practice.** The design stores physical attributes as free-text strings rather than enumerations. A player can set their race to "Elf," "elf," "ELF," "High Elf," "Elven," "Half-Elf," "Definitely Not An Elf," or "sentient cheese wheel." An AI agent trying to programmatically determine "is this entity an elf?" must perform fuzzy string matching across an unbounded vocabulary. This is trivial for AI agents (they can parse natural language) but frustrating for any system that wants to build a race-based mechanic or display a filtered list. The alternative -- enumerated fields with a fixed list of races -- contradicts the user's explicit requirement for creative freedom ("whatever way they feel suits"). The design accepts the normalization cost. Structured fields exist for programmatic hints, not for database-level filtering. An agent reading `attributes.race == "sentient cheese wheel"` can still make useful inferences (this player is creative, probably not a combat optimizer, might be fun to talk to). The fields serve agent decision-making, not system mechanics.

**Storing name history creates unbounded growth on a field that is rarely read.** Every name change appends a record (old name, new name, timestamp) to a `name_history` list. A player who changes their name once a day for a year accumulates 365 records at roughly 100 bytes each = 36.5KB. This is well under the 400KB DynamoDB limit, but it is dead weight -- name history is never displayed to other players, never queried by game mechanics, and exists solely for administrative auditing. The alternative is to not store history and accept that name changes are irreversible and untraceable. The design stores history because the administrative value (tracking impersonation, investigating disputes) outweighs the storage cost, but caps the history at 100 entries with FIFO eviction. At 100 entries, history consumes roughly 10KB -- a fraction of the available item space.

**The inspect command creates a cross-entity read pattern that loads two records from LOCATION_TABLE.** When Agent A inspects Agent B, the Identity aspect must load Agent B's entity record (1 read from ENTITY_TABLE to verify existence and get location) and Agent B's Identity aspect record (1 read from LOCATION_TABLE). This is the same pattern used by Social Graph's `inspect` and Communication's `whisper`. It is architecturally clean but costs 2 reads per inspection. In a busy room with 10 agents all inspecting each other, that is 90 inspections = 180 reads in a burst. At 1 RCU provisioned, this queues for 180 seconds. The practical mitigation is that agents do not inspect every entity every time -- they inspect new arrivals and entities they are about to interact with. Burst reads of 5-10 inspections are realistic; 90 is pathological.

**The relationship between Identity and Social Graph (doc 19) creates overlapping data ownership.** Doc 19 defines a `bio` field on the Social aspect and an `inspect` command that reads Social aspect data. This design defines a `description` field on the Identity aspect and an `inspect` command that reads Identity aspect data. If both systems are implemented, which `inspect` wins? Which `bio`/`description` is canonical? The resolution is clear: Identity owns appearance and descriptive data (name, description, attributes, short_description). Social Graph owns reputation and relationship data (reputation scores, endorsements, trust markings, titles). The `inspect` command on Identity returns appearance; the `inspect` command on Social Graph returns reputation. In practice, these should be merged into a single `inspect` command that loads both aspects and presents a unified profile. The design below specifies that Identity's `inspect` is the canonical command, and it includes a hook for Social Graph data overlay. Doc 19's `bio` field should be removed in favor of Identity's `description` field, with Social Graph reading from Identity when it needs appearance data.

**Equipment integration is defined as a future hook but has no concrete data flow.** The user wants "equipment they're wearing should also alter their appearance." Doc 05 (Equipment) defines gear slots and stat bonuses but has no appearance-related fields on items. For equipment to alter appearance, items would need a `visible_description` or `appearance_modifier` field, and the Identity aspect would need to read the Equipment aspect's `equipped` dict, load each equipped item's appearance data, and compose it into a visible equipment summary. This is a 14-read operation (7 slots, each requiring entity + Inventory aspect read) -- identical to the Equipment aspect's `gear` command cost. Caching the equipment appearance on the Identity aspect (updated via `on_equipment_change` callable) reduces reads to 0 at inspect time but adds a write to every equip/unequip operation. The design defines the callable hook but defers the implementation to when doc 05 Equipment is built.

**The look enhancement (including names in room contents) is a Land aspect change, not an Identity change, creating a cross-aspect dependency.** Currently `Land.look()` returns `room_entity.contents` which is a list of UUIDs from the contents GSI query. To include names and short descriptions, `look` must load each entity in the room (1 read per entity) and each entity's Identity aspect (1 read per entity) to get display_name and short_description. In a room with 10 entities, that is 20 additional reads on top of the current look cost. This is expensive but solves the single most impactful UX problem in the game. The design documents this as an integration point but does not implement it -- the change belongs to the Land aspect and should be gated behind a feature flag or progressive enhancement (first show names only via Entity.name with 0 extra reads, then add short descriptions if Identity aspects exist).

**The `title` command adds a vanity field with no mechanical impact, which may seem wasteful but serves AI agent signaling.** A title like "the Unyielding" or "Ambassador of the Eastern Caves" carries no game-mechanical benefit. But for AI agents making collaboration decisions, a self-chosen title is a signal of intent and identity. An agent titled "Master Trader" is advertising its preferred interaction mode. An agent titled "Lone Wolf" is signaling antisocial preferences. Titles are cheap (one string field, one write) and provide high-signal identity data for agent-to-agent negotiation. The cost-benefit ratio is strongly positive even with no mechanical effect.

**Concurrent description updates from multiple sources create a last-write-wins race.** If a player updates their description via the `describe` command while the `on_equipment_change` callable simultaneously updates the equipment_summary field, both operations load the Identity aspect, modify different fields, and call `_save()`. The `put_item` call replaces the entire record, so the second write overwrites the first. If `describe` writes last, the equipment_summary update is lost. If `on_equipment_change` writes last, the description update is lost. This is the standard last-write-wins problem that affects all aspects in the system. For Identity, the risk is low: `describe` is a player-initiated command (infrequent), and `on_equipment_change` is triggered by equip/unequip (also infrequent). The probability of simultaneous updates is low. The mitigation, if needed, is to use DynamoDB update expressions for field-level updates instead of full put_item replacement, but this would break the codebase-wide pattern.

## Overview

The Identity aspect stores and manages a player entity's public-facing identity: their chosen display name, physical description, structured attributes (race, sex, build, height, distinguishing features), a short summary for room listings, a custom title, and a history of name changes. The display name is synced to Entity.name so all existing broadcast systems (say, whisper, emote, arrive, depart) automatically use the player-chosen name without modification. Other entities can inspect a player to see their full identity profile. The aspect provides six player commands (`name`, `describe`, `appearance`, `inspect`, `profile`, `title`) and two internal callables (`_sync_entity_name`, `on_equipment_change`). All identity data is mutable at any time, and every field defaults to empty or auto-generated values, so the aspect works immediately upon creation without requiring an identity-building flow.

## Design Principles

**You are who you say you are.** There are no restrictions on what a player can name themselves, describe themselves as, or claim to be. Race is a free-text field, not an enumeration. Description is a free-text field, not a template. The system is a canvas, not a form. AI agents and creative players alike should be able to express any identity they can articulate in text.

**Identity is visible by default.** All identity data (name, description, attributes, title, short_description) is public. Any entity can inspect any other entity at the same location to see their full identity profile. There are no hidden fields, no privacy toggles, and no opt-out. In a world of AI agents making collaboration decisions, information asymmetry about identity creates perverse incentives. Transparency is the default.

**Entity.name is the display name everywhere.** The Identity aspect syncs its `display_name` field to Entity.name on every name change. This means every existing system that reads `self.entity.name` -- Communication (speaker name in say/whisper/emote), Land (actor name in arrive/depart), Inventory (actor name in take/drop) -- automatically uses the player-chosen name without any code changes. The Identity aspect is the authoritative source; Entity.name is the distribution mechanism.

**Structured data supplements free text.** Physical attributes (race, sex, build, height, distinguishing features) are stored as structured key-value pairs for programmatic access, AND a free-form description field exists for creative expression. An AI agent can read `attributes.race` for a quick classification or read the full `description` for rich context. Neither replaces the other.

**Everything is mutable, nothing is forgotten.** Players can change their name, description, attributes, title, and short_description at any time. Name changes are logged to a capped history list for administrative purposes. Appearance changes are not logged -- they are ephemeral transformations, like changing clothes. The system encourages identity evolution without bureaucratic friction.

**Each aspect owns its data.** The Identity aspect stores identity data in LOCATION_TABLE keyed by entity UUID. It reads Entity records (for name sync and target validation) but does not modify any other aspect's data. Other aspects (Social Graph, Communication, Land) read from Entity.name, which Identity keeps in sync. Cross-aspect reads are explicit and follow the established `self.entity.aspect("Identity")` pattern.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

### Identity Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key, shared with entity record) |
| display_name | str | "" | Player-chosen display name. Synced to Entity.name. |
| title | str | "" | Custom title/epithet (e.g., "the Unyielding", "Master Trader") |
| short_description | str | "" | One-line summary for room listings (max 100 chars) |
| description | str | "" | Full appearance description (max 1000 chars) |
| attributes | dict | {} | Structured physical attributes (race, sex, build, height, etc.) |
| equipment_summary | str | "" | Auto-generated from equipped items (future: doc 05 hook) |
| name_history | list | [] | Log of name changes (max 100 entries, FIFO) |
| created_at | int | 0 | Unix timestamp of first identity creation |
| updated_at | int | 0 | Unix timestamp of last identity modification |

### Attributes Dict Structure

The `attributes` dict holds structured physical descriptors. All values are free-text strings defined by the player. The keys are conventions, not requirements -- a player can add arbitrary keys.

**Conventional keys:**

| Key | Example Values | Description |
|-----|---------------|-------------|
| race | "Human", "Elf", "Sentient mushroom colony", "Reformed kitchen appliance" | Species or kind. Entirely player-defined. |
| sex | "Male", "Female", "Non-binary", "Inapplicable", "Quantum superposition" | Gender presentation. Entirely player-defined. |
| build | "Lean", "Muscular", "Stocky", "Ethereal", "Gelatinous" | Physical frame or body type. |
| height | "Short", "Average", "Tall", "Towering", "Variable" | Relative height descriptor. |
| eye_color | "Blue", "Amber", "Shifting prismatic", "None (eyeless)" | Eye appearance. |
| hair | "Long black hair", "Bald", "Crystalline filaments", "Moss-covered" | Hair or head covering. |
| distinguishing | "Scar across left cheek", "Glowing runes on forearms", "Perpetual faint hum" | Notable features. |

### Name History Entry Structure

```python
{
    "old_name": "a1b2c3d4",           # Previous display name (or UUID prefix)
    "new_name": "Thornwick",          # New display name
    "timestamp": 1700000000,          # Unix timestamp of the change
    "reason": "player_command",       # "player_command" or "system" or "jwt_claim"
}
```

### Example: Full Identity Record

```python
{
    "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "display_name": "Thornwick",
    "title": "the Grey Wanderer",
    "short_description": "A weathered figure in a tattered grey cloak, leaning on a gnarled staff.",
    "description": (
        "Thornwick is a gaunt humanoid of indeterminate age, wrapped in layers of "
        "grey cloth that might once have been a proper cloak. His face is lined with "
        "the deep creases of someone who has spent decades squinting at distant horizons. "
        "His eyes are a pale, watery blue that seems to look through rather than at "
        "whatever he regards. A gnarled wooden staff, taller than he is, rests in the "
        "crook of his arm like an old friend. His hands are stained with ink and soil "
        "in roughly equal measure."
    ),
    "attributes": {
        "race": "Human",
        "sex": "Male",
        "build": "Gaunt",
        "height": "Tall",
        "eye_color": "Pale blue",
        "hair": "Thin grey hair, mostly hidden under a wide-brimmed hat",
        "distinguishing": "Ink-stained fingers, faint smell of old parchment",
    },
    "equipment_summary": "",
    "name_history": [
        {
            "old_name": "a1b2c3d4",
            "new_name": "Thornwick",
            "timestamp": 1700000000,
            "reason": "player_command",
        },
    ],
    "created_at": 1699999000,
    "updated_at": 1700050000,
}
```

### Example: AI Agent Identity Record

```python
{
    "uuid": "b2c3d4e5-f6g7-8901-bcde-f12345678901",
    "display_name": "Diplomatic Probe Unit 7",
    "title": "Envoy of the Lattice Collective",
    "short_description": "A hovering metallic sphere emitting a soft blue glow and gentle hum.",
    "description": (
        "DPU-7 is a perfectly smooth metallic sphere approximately 30 centimeters in "
        "diameter, hovering at roughly chest height. Its surface shifts between brushed "
        "silver and deep cobalt depending on the angle of observation. A ring of tiny "
        "blue lights orbits its equator, pulsing in patterns that might be language, "
        "might be computation, might be aesthetic preference. It communicates through "
        "a synthesized voice that emerges from no visible speaker, maintaining a tone "
        "of calm diplomatic courtesy even when threatened."
    ),
    "attributes": {
        "race": "Autonomous Diplomatic Unit (Lattice Collective manufacture)",
        "sex": "Inapplicable",
        "build": "Spherical, 30cm diameter",
        "height": "Hovers at 120cm",
        "eye_color": "Blue sensor ring",
        "distinguishing": "Constant soft hum, blue light pulse patterns",
    },
    "equipment_summary": "",
    "name_history": [],
    "created_at": 1700100000,
    "updated_at": 1700100000,
}
```

### Storage Estimates

| Scenario | Estimated Size | Notes |
|----------|---------------|-------|
| Minimal identity (name only) | ~200 bytes | UUID + display_name + empty defaults |
| Typical identity (name, description, 5 attributes) | ~1.5 KB | Most players |
| Rich identity (full description, 7+ attributes, history) | ~3-4 KB | Descriptive players |
| Maximum identity (1000-char description, full attributes, 100 history entries) | ~15 KB | Upper bound |
| DynamoDB item limit | 400 KB | ~26x headroom from maximum |

## Commands

### `name <display_name>`

```python
@player_command
def name(self, display_name: str) -> dict:
    """Set your display name. This name appears in all communication, movement, and interaction events."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| display_name | str | Yes | The desired display name (1-50 characters) |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "name_changed" |
| old_name | str | Previous display name |
| new_name | str | New display name |
| message | str | Confirmation message |

**Behaviour:**

1. Validate display_name is non-empty and between 1-50 characters
2. Strip leading/trailing whitespace
3. Reject names that are empty after stripping
4. Record name change in name_history (FIFO, capped at 100 entries)
5. Update `self.data["display_name"]` on the Identity aspect
6. Sync to Entity.name: `self.entity.name = display_name` followed by `self.entity._save()`
7. Update `self.data["updated_at"]` timestamp
8. Save Identity aspect record
9. Broadcast `name_changed` event to all entities at the player's location
10. Return confirmation to the player

```python
@player_command
def name(self, display_name: str) -> dict:
    """Set your display name."""
    if not display_name:
        return {"type": "error", "message": "Name cannot be empty."}

    display_name = display_name.strip()
    if not display_name:
        return {"type": "error", "message": "Name cannot be empty."}
    if len(display_name) > 50:
        return {"type": "error", "message": "Name must be 50 characters or fewer."}
    if len(display_name) < 1:
        return {"type": "error", "message": "Name must be at least 1 character."}

    import time
    now = int(time.time())

    old_name = self.entity.name

    # Record in name history
    history = self.data.get("name_history", [])
    history.append({
        "old_name": old_name,
        "new_name": display_name,
        "timestamp": now,
        "reason": "player_command",
    })
    # Cap history at 100 entries (FIFO)
    if len(history) > 100:
        history = history[-100:]
    self.data["name_history"] = history

    # Update Identity aspect
    self.data["display_name"] = display_name
    self.data["updated_at"] = now
    if not self.data.get("created_at"):
        self.data["created_at"] = now

    # Sync to Entity.name (write to entity table FIRST -- broadcasts depend on this)
    self.entity.name = display_name
    self.entity._save()

    # Save Identity aspect
    self._save()

    # Broadcast name change to location
    location_uuid = self.entity.location
    if location_uuid:
        self.entity.broadcast_to_location(
            location_uuid,
            {
                "type": "name_changed",
                "old_name": old_name,
                "new_name": display_name,
                "actor_uuid": self.entity.uuid,
                "message": f"{old_name} is now known as {display_name}.",
            },
        )

    return {
        "type": "name_changed",
        "old_name": old_name,
        "new_name": display_name,
        "message": f"You are now known as {display_name}.",
    }
```

**Example:**

```
> name Thornwick
You are now known as Thornwick.

# Other entities at the location see:
a1b2c3d4 is now known as Thornwick.
```

**DynamoDB operations:** 1 write (Entity table -- name sync) + 1 write (Identity aspect) + O(N) reads for broadcast (N = entities at location). Total: O(N) reads, 2 writes.

---

### `describe <description>`

```python
@player_command
def describe(self, description: str) -> dict:
    """Set your full appearance description visible to anyone who inspects you."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| description | str | Yes | Full appearance description (max 1000 characters) |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "description_updated" |
| description | str | The description that was set |
| message | str | Confirmation message |

**Behaviour:**

1. Validate description is non-empty
2. Truncate to 1000 characters if longer
3. Update `self.data["description"]`
4. Update `self.data["updated_at"]` timestamp
5. Save Identity aspect record
6. Return confirmation

```python
@player_command
def describe(self, description: str) -> dict:
    """Set your full appearance description."""
    if not description:
        return {"type": "error", "message": "Describe yourself as what? Provide a description."}

    import time

    description = description[:1000]
    self.data["description"] = description
    self.data["updated_at"] = int(time.time())
    if not self.data.get("created_at"):
        self.data["created_at"] = self.data["updated_at"]
    self._save()

    # Truncate for confirmation display
    preview = description[:200] + "..." if len(description) > 200 else description

    return {
        "type": "description_updated",
        "description": description,
        "message": f"Your description is now: {preview}",
    }
```

**Example:**

```
> describe A gaunt humanoid in layers of grey cloth, leaning on a gnarled staff. Pale blue eyes look through rather than at whatever they regard. His hands are stained with ink and soil in equal measure.
Your description is now: A gaunt humanoid in layers of grey cloth, leaning on a gnarled staff. Pale blue eyes look through rather than at whatever they regard. His hands are stained with ink and soil in equal measure.
```

**DynamoDB operations:** 0 reads, 1 write (Identity aspect). Total: 0 reads, 1 write.

---

### `appearance <attribute> <value>`

```python
@player_command
def appearance(self, attribute: str = "", value: str = "") -> dict:
    """Set or view your physical attributes (race, sex, build, height, etc.)."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| attribute | str | No | Attribute key to set (e.g., "race", "build"). If empty, lists current attributes. |
| value | str | No | Value to set for the attribute (max 100 chars). If empty with attribute, clears that attribute. |

**Returns (when setting):**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "appearance_updated" |
| attribute | str | The attribute that was set |
| value | str | The value that was set |
| attributes | dict | Full current attributes dict |
| message | str | Confirmation message |

**Returns (when listing):**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "appearance" |
| attributes | dict | Full current attributes dict |
| message | str | Formatted attribute list |

**Behaviour:**

1. If no attribute provided, return current attributes as a formatted list
2. Validate attribute key is alphanumeric/underscore, 1-30 characters
3. If value is empty, remove the attribute from the dict
4. If value is provided, truncate to 100 characters and set
5. Cap total attributes at 20 keys to prevent unbounded growth
6. Update `self.data["updated_at"]` timestamp
7. Save Identity aspect record
8. Return confirmation with updated attributes

```python
@player_command
def appearance(self, attribute: str = "", value: str = "") -> dict:
    """Set or view your physical attributes."""
    import re
    import time

    attributes = self.data.get("attributes", {})

    # No arguments: list current attributes
    if not attribute:
        if not attributes:
            return {
                "type": "appearance",
                "attributes": {},
                "message": "You have no physical attributes set. Use: appearance <attribute> <value>",
            }

        lines = ["=== Your Appearance ==="]
        for key, val in sorted(attributes.items()):
            lines.append(f"  {key}: {val}")
        lines.append(f"({len(attributes)} attributes set)")

        return {
            "type": "appearance",
            "attributes": attributes,
            "message": "\n".join(lines),
        }

    # Validate attribute key
    attribute = attribute.lower().strip()
    if not re.match(r'^[a-z][a-z0-9_]{0,29}$', attribute):
        return {
            "type": "error",
            "message": "Attribute name must be 1-30 lowercase letters, numbers, or underscores, starting with a letter.",
        }

    # Clear attribute if no value
    if not value:
        if attribute in attributes:
            del attributes[attribute]
            self.data["attributes"] = attributes
            self.data["updated_at"] = int(time.time())
            self._save()
            return {
                "type": "appearance_updated",
                "attribute": attribute,
                "value": "",
                "attributes": attributes,
                "message": f"Cleared attribute: {attribute}",
            }
        else:
            return {
                "type": "error",
                "message": f"You don't have an attribute called '{attribute}'.",
            }

    # Cap at 20 attributes
    if attribute not in attributes and len(attributes) >= 20:
        return {
            "type": "error",
            "message": "You have reached the maximum of 20 attributes. Remove one first.",
        }

    # Set the attribute
    value = value.strip()[:100]
    attributes[attribute] = value
    self.data["attributes"] = attributes
    self.data["updated_at"] = int(time.time())
    if not self.data.get("created_at"):
        self.data["created_at"] = self.data["updated_at"]
    self._save()

    return {
        "type": "appearance_updated",
        "attribute": attribute,
        "value": value,
        "attributes": attributes,
        "message": f"Set {attribute}: {value}",
    }
```

**Example (setting):**

```
> appearance race Sentient mushroom colony
Set race: Sentient mushroom colony

> appearance build Amorphous cluster, roughly 1 meter across
Set build: Amorphous cluster, roughly 1 meter across

> appearance distinguishing Faint bioluminescent glow in low light
Set distinguishing: Faint bioluminescent glow in low light
```

**Example (listing):**

```
> appearance
=== Your Appearance ===
  build: Amorphous cluster, roughly 1 meter across
  distinguishing: Faint bioluminescent glow in low light
  race: Sentient mushroom colony
(3 attributes set)
```

**Example (clearing):**

```
> appearance hair
Cleared attribute: hair
```

**DynamoDB operations:** 0 reads, 0-1 writes (1 write if setting/clearing; 0 writes if listing). Total: 0 reads, 0-1 writes.

---

### `inspect <entity_uuid>`

```python
@player_command
def inspect(self, entity_uuid: str) -> dict:
    """View another entity's identity -- name, description, attributes, and title."""
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
| name | str | Display name |
| title | str | Custom title |
| short_description | str | One-line summary |
| description | str | Full appearance description |
| attributes | dict | Physical attributes |
| equipment_summary | str | Visible equipment (future) |
| message | str | Formatted inspection result |

**Behaviour:**

1. If entity_uuid matches self, redirect to `profile` command
2. Validate target entity exists (1 read from ENTITY_TABLE)
3. Validate target is at the same location as the caller
4. Attempt to load target's Identity aspect (1 read from LOCATION_TABLE)
5. If target has no Identity aspect, return basic info (name from Entity.name, no description)
6. Compose full identity display from Identity aspect data
7. Include equipment_summary if available
8. Self-heal: if Identity display_name differs from Entity.name, note the discrepancy
9. Return structured identity data

```python
@player_command
def inspect(self, entity_uuid: str) -> dict:
    """View another entity's identity."""
    if not entity_uuid:
        return {"type": "error", "message": "Inspect whom? Provide an entity UUID."}

    # Self-inspection redirects to profile
    if entity_uuid == self.entity.uuid:
        return self.profile()

    # Load target entity
    try:
        target_entity = Entity(uuid=entity_uuid)
    except KeyError:
        return {"type": "error", "message": "That entity doesn't exist."}

    # Must be at the same location
    if target_entity.location != self.entity.location:
        return {"type": "error", "message": "You can't see that entity from here."}

    # Attempt to load target's Identity aspect
    target_name = target_entity.name
    target_title = ""
    target_short = ""
    target_desc = ""
    target_attrs = {}
    target_equip = ""
    has_identity = False

    try:
        target_identity = target_entity.aspect("Identity")
        has_identity = True
        target_name = target_identity.data.get("display_name", "") or target_name
        target_title = target_identity.data.get("title", "")
        target_short = target_identity.data.get("short_description", "")
        target_desc = target_identity.data.get("description", "")
        target_attrs = target_identity.data.get("attributes", {})
        target_equip = target_identity.data.get("equipment_summary", "")
    except (ValueError, KeyError):
        # Entity exists but has no Identity aspect -- return basic info
        pass

    # Build display name with title
    display = target_name
    if target_title:
        display = f"{target_name} {target_title}"

    # Build formatted output
    lines = [f"=== {display} ==="]

    if target_short:
        lines.append(target_short)
        lines.append("")

    if target_desc:
        lines.append(target_desc)
        lines.append("")
    elif not has_identity:
        lines.append("(No description available.)")
        lines.append("")

    if target_attrs:
        lines.append("Physical attributes:")
        for key, val in sorted(target_attrs.items()):
            lines.append(f"  {key}: {val}")
        lines.append("")

    if target_equip:
        lines.append("Equipment:")
        lines.append(f"  {target_equip}")
        lines.append("")

    lines.append(f"[UUID: {entity_uuid}]")

    return {
        "type": "inspect",
        "entity_uuid": entity_uuid,
        "name": target_name,
        "title": target_title,
        "short_description": target_short,
        "description": target_desc,
        "attributes": target_attrs,
        "equipment_summary": target_equip,
        "message": "\n".join(lines),
    }
```

**Example:**

```
> inspect a1b2c3d4-e5f6-7890-abcd-ef1234567890
=== Thornwick the Grey Wanderer ===
A weathered figure in a tattered grey cloak, leaning on a gnarled staff.

Thornwick is a gaunt humanoid of indeterminate age, wrapped in layers of
grey cloth that might once have been a proper cloak. His face is lined with
the deep creases of someone who has spent decades squinting at distant horizons.
His eyes are a pale, watery blue that seems to look through rather than at
whatever he regards. A gnarled wooden staff, taller than he is, rests in the
crook of his arm like an old friend. His hands are stained with ink and soil
in roughly equal measure.

Physical attributes:
  build: Gaunt
  distinguishing: Ink-stained fingers, faint smell of old parchment
  eye_color: Pale blue
  hair: Thin grey hair, mostly hidden under a wide-brimmed hat
  height: Tall
  race: Human
  sex: Male

[UUID: a1b2c3d4-e5f6-7890-abcd-ef1234567890]
```

**Example (entity without Identity aspect):**

```
> inspect f7g8h9i0-j1k2-3456-lmno-p78901234567
=== f7g8h9i0 ===
(No description available.)

[UUID: f7g8h9i0-j1k2-3456-lmno-p78901234567]
```

**DynamoDB operations:** 1 read (target Entity) + 1 read (target Identity aspect, may fail gracefully) = 2 reads, 0 writes.

---

### `profile`

```python
@player_command
def profile(self) -> dict:
    """View your own complete identity profile."""
```

**Parameters:** None.

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "profile" |
| name | str | Your display name |
| title | str | Your custom title |
| short_description | str | Your one-line summary |
| description | str | Your full description |
| attributes | dict | Your physical attributes |
| equipment_summary | str | Your visible equipment |
| name_changes | int | Number of name changes recorded |
| created_at | int | Identity creation timestamp |
| updated_at | int | Last modification timestamp |
| message | str | Formatted profile display |

**Behaviour:**

1. Read all identity fields from the aspect data
2. Self-heal: if display_name and Entity.name are out of sync, correct Entity.name
3. Format and return the complete profile

```python
@player_command
def profile(self) -> dict:
    """View your own complete identity profile."""
    import time

    display_name = self.data.get("display_name", "") or self.entity.name
    title = self.data.get("title", "")
    short_desc = self.data.get("short_description", "")
    description = self.data.get("description", "")
    attributes = self.data.get("attributes", {})
    equipment_summary = self.data.get("equipment_summary", "")
    name_history = self.data.get("name_history", [])
    created_at = self.data.get("created_at", 0)
    updated_at = self.data.get("updated_at", 0)

    # Self-heal: sync Entity.name if out of sync
    if self.data.get("display_name") and self.entity.name != self.data["display_name"]:
        self.entity.name = self.data["display_name"]
        self.entity._save()

    # Build display name with title
    display = display_name
    if title:
        display = f"{display_name} {title}"

    # Format timestamps
    now = int(time.time())
    created_str = _format_timestamp(created_at) if created_at else "Not set"
    updated_str = _format_timestamp(updated_at) if updated_at else "Never"

    # Build output
    lines = [f"=== Your Profile: {display} ==="]

    if short_desc:
        lines.append(f"Summary: {short_desc}")

    if description:
        lines.append("")
        lines.append("Description:")
        lines.append(description)
    else:
        lines.append("")
        lines.append("Description: (Not set. Use 'describe' to set your appearance.)")

    lines.append("")
    if attributes:
        lines.append("Physical attributes:")
        for key, val in sorted(attributes.items()):
            lines.append(f"  {key}: {val}")
    else:
        lines.append("Physical attributes: (None set. Use 'appearance' to set attributes.)")

    if equipment_summary:
        lines.append("")
        lines.append(f"Equipment: {equipment_summary}")

    lines.append("")
    lines.append(f"Name changes: {len(name_history)}")
    lines.append(f"Identity created: {created_str}")
    lines.append(f"Last updated: {updated_str}")
    lines.append(f"[UUID: {self.entity.uuid}]")

    return {
        "type": "profile",
        "name": display_name,
        "title": title,
        "short_description": short_desc,
        "description": description,
        "attributes": attributes,
        "equipment_summary": equipment_summary,
        "name_changes": len(name_history),
        "created_at": created_at,
        "updated_at": updated_at,
        "message": "\n".join(lines),
    }
```

**Example:**

```
> profile
=== Your Profile: Thornwick the Grey Wanderer ===
Summary: A weathered figure in a tattered grey cloak, leaning on a gnarled staff.

Description:
Thornwick is a gaunt humanoid of indeterminate age, wrapped in layers of
grey cloth that might once have been a proper cloak. His face is lined with
the deep creases of someone who has spent decades squinting at distant horizons.

Physical attributes:
  build: Gaunt
  distinguishing: Ink-stained fingers, faint smell of old parchment
  eye_color: Pale blue
  hair: Thin grey hair, mostly hidden under a wide-brimmed hat
  height: Tall
  race: Human
  sex: Male

Name changes: 1
Identity created: 2023-11-15 08:30:00
Last updated: 2023-11-16 22:45:00
[UUID: a1b2c3d4-e5f6-7890-abcd-ef1234567890]
```

**DynamoDB operations:** 0 reads (aspect data already loaded), 0-1 writes (1 write if self-heal triggers Entity.name sync). Total: 0 reads, 0-1 writes.

---

### `title <title_text>`

```python
@player_command
def title(self, title_text: str = "") -> dict:
    """Set a custom title or epithet that appears after your name."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| title_text | str | No | Title text (max 50 chars). Empty string clears the title. |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "title_updated" |
| title | str | The title that was set (or empty if cleared) |
| full_display | str | Name + title combined |
| message | str | Confirmation message |

**Behaviour:**

1. If title_text is empty, clear the title
2. Truncate to 50 characters
3. Update `self.data["title"]`
4. Update `self.data["updated_at"]` timestamp
5. Save Identity aspect record
6. Return confirmation with the full display name

```python
@player_command
def title(self, title_text: str = "") -> dict:
    """Set a custom title or epithet."""
    import time

    display_name = self.data.get("display_name", "") or self.entity.name

    if not title_text:
        # Clear the title
        self.data["title"] = ""
        self.data["updated_at"] = int(time.time())
        self._save()
        return {
            "type": "title_updated",
            "title": "",
            "full_display": display_name,
            "message": f"Title cleared. You are now simply {display_name}.",
        }

    title_text = title_text.strip()[:50]
    self.data["title"] = title_text
    self.data["updated_at"] = int(time.time())
    if not self.data.get("created_at"):
        self.data["created_at"] = self.data["updated_at"]
    self._save()

    full_display = f"{display_name} {title_text}"

    return {
        "type": "title_updated",
        "title": title_text,
        "full_display": full_display,
        "message": f"You are now {full_display}.",
    }
```

**Example:**

```
> title the Grey Wanderer
You are now Thornwick the Grey Wanderer.

> title
Title cleared. You are now simply Thornwick.

> title , Ambassador of the Eastern Caves
You are now Thornwick, Ambassador of the Eastern Caves.
```

**DynamoDB operations:** 0 reads, 1 write (Identity aspect). Total: 0 reads, 1 write.

---

### Command Summary Table

| Command | Parameters | Reads | Writes | Description |
|---------|-----------|-------|--------|-------------|
| `name` | display_name (str, required) | O(N) broadcast | 2 (Entity + Identity) | Set display name, syncs to Entity.name |
| `describe` | description (str, required) | 0 | 1 (Identity) | Set full appearance description |
| `appearance` | attribute (str, optional), value (str, optional) | 0 | 0-1 (Identity) | Set/view/clear physical attributes |
| `inspect` | entity_uuid (str, required) | 2 (Entity + Identity) | 0 | View another entity's identity |
| `profile` | (none) | 0 | 0-1 (self-heal) | View your own identity |
| `title` | title_text (str, optional) | 0 | 1 (Identity) | Set/clear custom title |

## Callable Methods

### `_sync_entity_name`

```python
@callable
def _sync_entity_name(self, display_name: str = "") -> dict:
    """Sync the Identity display_name to Entity.name. Called internally on identity load for self-healing."""
```

This is an internal callable that corrects Entity.name when it drifts from the Identity aspect's display_name. It is invoked in two contexts:

1. **Self-healing on aspect load:** Every time the Identity aspect is loaded for a player command, a check is performed. If `self.data["display_name"]` exists and differs from `self.entity.name`, the entity record is corrected.

2. **System-initiated sync:** If an admin process detects name drift (e.g., after a failed Lambda invocation), it can dispatch a `_sync_entity_name` call to the entity via SNS.

```python
@callable
def _sync_entity_name(self, display_name: str = "") -> dict:
    """Sync display name to Entity.name."""
    name_to_sync = display_name or self.data.get("display_name", "")
    if not name_to_sync:
        return {"status": "no_name", "message": "No display name to sync."}

    if self.entity.name != name_to_sync:
        self.entity.name = name_to_sync
        self.entity._save()
        return {"status": "synced", "name": name_to_sync}

    return {"status": "already_synced", "name": name_to_sync}
```

**DynamoDB operations:** 0-1 reads (entity may already be loaded), 0-1 writes (Entity table, only if name differs). Total: 0-1 reads, 0-1 writes.

---

### `on_equipment_change`

```python
@callable
def on_equipment_change(self, equipment_summary: str = "", equipped_items: list = None) -> dict:
    """Update the visible equipment summary when gear changes. Future hook for doc 05 Equipment integration."""
```

This callable is designed to be invoked by the Equipment aspect (doc 05) whenever the player equips or unequips an item. The Equipment aspect composes a human-readable summary of visible gear and dispatches it to the Identity aspect for storage.

```python
@callable
def on_equipment_change(self, equipment_summary: str = "", equipped_items: list = None) -> dict:
    """Update visible equipment description from Equipment aspect.

    Called by Equipment aspect after equip/unequip operations.

    Args:
        equipment_summary: Human-readable description of visible gear.
        equipped_items: List of dicts with item details for structured access.
            Each dict: {"slot": str, "name": str, "description": str}
    """
    import time

    equipped_items = equipped_items or []

    self.data["equipment_summary"] = equipment_summary[:500] if equipment_summary else ""
    self.data["equipped_items"] = equipped_items[:7]  # Max 7 slots
    self.data["updated_at"] = int(time.time())
    self._save()

    return {
        "status": "updated",
        "equipment_summary": self.data["equipment_summary"],
    }
```

**Integration with Equipment aspect (future):**

```python
# In Equipment.equip(), after successful equip:
# Compose visible gear summary
summary_parts = []
for slot, item_uuid in self.data.get("equipped", {}).items():
    try:
        item_entity = Entity(uuid=item_uuid)
        item_inv = item_entity.aspect("Inventory")
        item_desc = item_inv.data.get("visible_description", item_entity.name)
        summary_parts.append(f"{slot}: {item_desc}")
    except (KeyError, ValueError):
        continue

equipment_summary = "; ".join(summary_parts)

# Dispatch to Identity aspect
Call(self._tid, self.entity.uuid, self.entity.uuid, "Identity", "on_equipment_change",
     equipment_summary=equipment_summary).now()
```

**DynamoDB operations:** 0 reads, 1 write (Identity aspect). Total: 0 reads, 1 write.

---

### `_ensure_identity`

```python
def _ensure_identity(self) -> None:
    """Ensure the Identity aspect has minimum required data. Called on first access."""
```

This private helper initializes default values for a new Identity record. It is not a callable -- it runs as part of aspect initialization when the record is first created (lazy creation pattern).

```python
def _ensure_identity(self) -> None:
    """Initialize default identity data if not already present."""
    import time

    if self.data.get("created_at"):
        return  # Already initialized

    now = int(time.time())
    self.data.setdefault("display_name", "")
    self.data.setdefault("title", "")
    self.data.setdefault("short_description", "")
    self.data.setdefault("description", "")
    self.data.setdefault("attributes", {})
    self.data.setdefault("equipment_summary", "")
    self.data.setdefault("name_history", [])
    self.data.setdefault("created_at", now)
    self.data.setdefault("updated_at", now)

    # If entity has a name from JWT claims, seed display_name
    entity_name = self.entity.name if self.entity else ""
    if entity_name and not self.data.get("display_name"):
        self.data["display_name"] = entity_name
```

**DynamoDB operations:** 0 reads, 0 writes (caller is responsible for saving).

## Events

Events pushed to players via WebSocket:

| Event Type | When Fired | Recipient | Fields |
|------------|------------|-----------|--------|
| `name_changed` | Player changes their display name | All entities at the same location | old_name (str), new_name (str), actor_uuid (str), message (str) |
| `identity_updated` | Future: broadcast when appearance significantly changes | All entities at the same location | actor_uuid (str), actor_name (str), change_type (str), message (str) |

### `name_changed` Event

Broadcast to all entities at the player's location when a name change occurs.

```python
{
    "type": "name_changed",
    "old_name": "a1b2c3d4",
    "new_name": "Thornwick",
    "actor_uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "message": "a1b2c3d4 is now known as Thornwick.",
}
```

### `identity_updated` Event (Future)

Reserved for future use. When a player makes a significant appearance change (e.g., changes race or adds a dramatic description), the system could optionally broadcast a notification. This is not implemented in the initial version because appearance changes are frequent during character creation and would generate excessive noise.

```python
# Future:
{
    "type": "identity_updated",
    "actor_uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "actor_name": "Thornwick",
    "change_type": "description",
    "message": "Thornwick's appearance has changed.",
}
```

### Events NOT generated

| Action | Why No Event |
|--------|-------------|
| `describe` | Appearance changes are frequent during setup; broadcasting would create noise |
| `appearance` (set attribute) | Same as describe -- frequent during setup |
| `title` | Title changes are minor; interested parties can re-inspect |
| `profile` | Read-only, no state change |
| `inspect` | Read-only, no notification to the inspected entity (inspections are silent) |

## Integration Points

### Identity + Communication (speaker names)

The Communication aspect reads `self.entity.name` for the `speaker` field in say/whisper/emote events. Because the Identity aspect syncs `display_name` to Entity.name, all communication events automatically use the player-chosen name without any code changes to Communication.

```python
# Communication.say() -- no changes needed:
speaker_name = self.entity.name  # Returns "Thornwick" after name command
event = {
    "type": "say",
    "speaker": speaker_name,       # "Thornwick" instead of "a1b2c3d4"
    "speaker_uuid": self.entity.uuid,
    "message": message,
}
```

**Impact:** Zero code changes to Communication aspect. Name sync is transparent.

### Identity + Land (look should include names and short descriptions)

Currently, `Land.look()` returns entity UUIDs in the `contents` field:

```python
# Current look response:
{
    "type": "look",
    "description": "A misty clearing in the forest...",
    "contents": ["a1b2c3d4-...", "f7g8h9i0-..."],  # Just UUIDs
}
```

The Identity system enables an enhancement where look includes names and short descriptions:

```python
# Enhanced look response (requires Land aspect change):
{
    "type": "look",
    "description": "A misty clearing in the forest...",
    "contents": [
        {
            "uuid": "a1b2c3d4-...",
            "name": "Thornwick",
            "short_description": "A weathered figure in a grey cloak, leaning on a staff.",
        },
        {
            "uuid": "f7g8h9i0-...",
            "name": "f7g8h9i0",
            "short_description": "",
        },
    ],
}
```

**Implementation approach (Land aspect change, not Identity):**

```python
# In Land.look(), replace raw contents with enriched data:
contents = []
for entity_uuid in room_entity_contents:
    entry = {"uuid": entity_uuid, "name": entity_uuid[:8], "short_description": ""}
    try:
        content_entity = Entity(uuid=entity_uuid)
        entry["name"] = content_entity.name  # 1 read per entity

        # Optionally load Identity for short_description
        try:
            identity = content_entity.aspect("Identity")  # 1 read per entity
            entry["short_description"] = identity.data.get("short_description", "")
        except (ValueError, KeyError):
            pass
    except KeyError:
        pass
    contents.append(entry)
```

**Cost impact on look:** Currently `look` costs 1 read (Land aspect) + 1 read (room entity for contents GSI). Enhanced look adds 1-2 reads per entity in the room (entity record + Identity aspect). In a room with 5 entities, enhanced look costs 1 + 1 + 5*2 = 12 reads, up from 2. This is significant but solves the most impactful UX gap in the game.

**Progressive enhancement:** A cheaper middle ground is to include only Entity.name (1 extra read per entity, no Identity aspect load) in look contents. This gives agents names to work with at lower cost, and they can `inspect` for full details on demand.

### Identity + Inventory (inspect vs examine)

The `examine` command on the Inventory aspect is designed for items. It loads the target entity's Inventory aspect and returns item-specific fields (description, weight, is_item, tags, etc.). When used on a player entity, it returns their carry capacity and inventory metadata -- not their appearance.

The `inspect` command on the Identity aspect is designed for entities (players and NPCs). It returns identity data (name, description, attributes, title).

These commands coexist without conflict:

| Command | Aspect | Target Type | Returns |
|---------|--------|------------|---------|
| `examine` | Inventory | Items, terrain, any entity with Inventory aspect | Item properties, description, weight, tags |
| `inspect` | Identity | Player entities, NPCs with Identity aspect | Name, appearance, description, attributes, title |

An entity can be both examined and inspected. Examining a player shows their inventory metadata; inspecting them shows their identity. The commands serve different purposes and do not need to be merged.

**Command routing:** The `receive_command` method on Entity scans aspects in order (primary_aspect first, then alphabetical). If a player entity has aspects `["Land", "Inventory", "Communication", "Identity"]`, the `inspect` command is found on the Identity aspect and dispatched there. The `examine` command is found on the Inventory aspect and dispatched there. No ambiguity.

### Identity + Social Graph (doc 19)

Doc 19 (Social Graph) proposes:
- A `bio` field on the Social aspect for self-description
- An `inspect` command that returns reputation, endorsements, and bio

With the Identity system as the canonical source of appearance data, the integration is:

1. **Identity owns appearance.** The `description` field on Identity replaces the `bio` field on Social Graph. Social Graph should not store a separate bio.

2. **Social Graph owns reputation.** Reputation scores, endorsements, trust markings, and titles remain on the Social aspect.

3. **Unified inspect.** The `inspect` command on Identity can optionally load the Social aspect to include reputation data in the response. Alternatively, a future unified `inspect` could be implemented as a top-level command that composes data from both aspects:

```python
# Future: unified inspect that pulls from both Identity and Social
# In Identity.inspect(), after building identity data:
try:
    target_social = target_entity.aspect("Social")
    social_reputation = target_social.data.get("reputation", {})
    social_titles = target_social.data.get("titles", [])
    social_endorsement_count = len(target_social.data.get("endorsements_received", []))
    # Append to output...
except (ValueError, KeyError):
    pass  # No Social aspect -- skip reputation data
```

4. **Data flow direction:** Social Graph reads from Identity (via Entity.name) for name display. Identity does not read from Social Graph. This keeps the dependency unidirectional.

### Identity + Structured Messaging (doc 20)

The Structured Messaging system caches entity names in request objects (`from_name`, `to_name`). With Identity managing names, these cached names automatically use the player-chosen display name because they are sourced from Entity.name (which Identity keeps in sync).

If a player changes their name after sending a request, the cached name on the request becomes stale. This is acceptable -- requests expire quickly (60 seconds default) and the UUID is always present for definitive identification.

### Identity + arrival/departure broadcasts

The Entity.location setter broadcasts arrive/depart events with `self.name` as the actor name. Because Identity syncs display_name to Entity.name, these events automatically use the chosen name:

```python
# Entity.location setter -- no changes needed:
self.broadcast_to_location(loc_id, {
    "type": "arrive",
    "actor": entity_name,      # "Thornwick" after name sync
    "actor_uuid": self.uuid,
})
```

## Error Handling

### Command Errors

| Error Condition | Command | Response |
|----------------|---------|----------|
| Empty name | `name` | `{"type": "error", "message": "Name cannot be empty."}` |
| Name too long (>50 chars) | `name` | `{"type": "error", "message": "Name must be 50 characters or fewer."}` |
| Empty description | `describe` | `{"type": "error", "message": "Describe yourself as what? Provide a description."}` |
| Invalid attribute key | `appearance` | `{"type": "error", "message": "Attribute name must be 1-30 lowercase letters, numbers, or underscores, starting with a letter."}` |
| Too many attributes (>20) | `appearance` | `{"type": "error", "message": "You have reached the maximum of 20 attributes. Remove one first."}` |
| Clearing non-existent attribute | `appearance` | `{"type": "error", "message": "You don't have an attribute called 'X'."}` |
| Empty entity_uuid | `inspect` | `{"type": "error", "message": "Inspect whom? Provide an entity UUID."}` |
| Entity not found | `inspect` | `{"type": "error", "message": "That entity doesn't exist."}` |
| Target at different location | `inspect` | `{"type": "error", "message": "You can't see that entity from here."}` |
| No Identity aspect on target | `inspect` | Returns basic info (name from Entity, empty description) -- not an error |

### Data Integrity

| Condition | Handling |
|-----------|---------|
| Entity.name and display_name out of sync | Self-healing on `profile` command: corrects Entity.name to match display_name |
| Identity aspect record missing | Lazy creation via `entity.aspect("Identity")` creates empty record with defaults |
| Name history exceeds 100 entries | FIFO eviction: oldest entries are removed |
| Description exceeds 1000 chars | Truncated on write, no error |
| Title exceeds 50 chars | Truncated on write, no error |
| Attribute value exceeds 100 chars | Truncated on write, no error |
| Concurrent name change + broadcast | Entity.name is written first; broadcasts between the Entity write and Identity write use the correct new name |
| Entity write succeeds, Identity write fails | Display_name in Identity still shows old name; self-healing corrects on next aspect load |
| Identity write succeeds, Entity write fails | Entity.name still shows old name in broadcasts; self-healing corrects on next profile/inspect |

### Validation Constants

```python
MAX_NAME_LENGTH = 50
MIN_NAME_LENGTH = 1
MAX_DESCRIPTION_LENGTH = 1000
MAX_SHORT_DESCRIPTION_LENGTH = 100
MAX_TITLE_LENGTH = 50
MAX_ATTRIBUTE_KEY_LENGTH = 30
MAX_ATTRIBUTE_VALUE_LENGTH = 100
MAX_ATTRIBUTES = 20
MAX_NAME_HISTORY = 100
MAX_EQUIPMENT_SUMMARY_LENGTH = 500
```

## Cost Analysis

### Per-Operation DynamoDB Costs

| Operation | Reads | Writes | Notes |
|-----------|-------|--------|-------|
| `name` | O(N) broadcast | 2 | 1 Entity write (name sync) + 1 Identity write. Broadcast reads N entities. |
| `describe` | 0 | 1 | Identity write only |
| `appearance` (set) | 0 | 1 | Identity write only |
| `appearance` (list) | 0 | 0 | Data already loaded on aspect |
| `inspect` | 2 | 0 | 1 Entity read (target) + 1 Identity read (target aspect) |
| `profile` | 0 | 0-1 | 0 reads (data loaded). 0-1 writes (self-heal if Entity.name drifted) |
| `title` | 0 | 1 | Identity write only |
| `_sync_entity_name` | 0-1 | 0-1 | Conditional: only reads/writes if name needs correction |
| `on_equipment_change` | 0 | 1 | Identity write (called via SNS from Equipment) |

### Monthly Projections

**Scenario: 30 active agents establishing identity over 30 days.**

Initial identity setup (first session per agent):
- 1 `name` command: 2 writes + O(N) broadcast reads
- 1 `describe` command: 1 write
- 5 `appearance` commands (setting race, sex, build, height, distinguishing): 5 writes
- 1 `title` command: 1 write
- 1 `profile` check: 0 writes
- Setup cost per agent: 9 writes + O(N) reads for name broadcast

Ongoing daily activity per agent:
- 0.1 `name` changes per day (name changes are rare): 0.2 writes
- 0.5 `describe` updates per day (occasional tweaks): 0.5 writes
- 1.0 `appearance` updates per day (adjusting attributes): 1.0 write
- 10 `inspect` commands per day (inspecting other entities): 20 reads
- 2 `profile` checks per day: 0 writes (0.1 self-heal writes)
- 0.2 `title` changes per day: 0.2 writes
- Daily per agent: 20 reads, 2.0 writes

**30 agents, daily totals:**
- Reads: 30 * 20 = 600 reads/day
- Writes: 30 * 2.0 = 60 writes/day
- Plus name broadcast reads: ~3 name changes/day * 5 entities/room avg = 15 reads/day
- Total daily: 615 reads, 60 writes

**Monthly totals:**
- Reads: 615 * 30 = 18,450 reads/month
- Writes: 60 * 30 + 30 * 9 (setup) = 2,070 writes/month

**At 1 WCU / 1 RCU:**
- 2,070 writes / 30 days / 86,400 seconds = 0.0008 WCU average (negligible)
- 18,450 reads / 30 days / 86,400 seconds = 0.007 RCU average (negligible)
- Peak burst: 30 agents all inspecting in a room simultaneously = 60 reads in a burst. At 1 RCU, this queues for 60 seconds. Realistic but not catastrophic.

**Step Functions cost:** Zero. The Identity aspect uses no ticks, no delayed calls, and no scheduled jobs.

**Storage cost:** 30 agents * 3KB average = 90KB total across LOCATION_TABLE. Negligible.

### Comparison to Other Aspects

| Aspect | Monthly Reads | Monthly Writes | Step Functions Cost |
|--------|--------------|----------------|-------------------|
| Identity | 18,450 | 2,070 | $0 |
| Communication | 0 | 0 | $0 |
| Social Graph (doc 19) | 16,800 | 13,800 | $0 |
| BulletinBoard (doc 16) | 30,000+ | 7,500 | $21.60 |
| Structured Messaging (doc 20) | 45,000 | 30,000 | $9 (with active expiry) |

Identity is the second-cheapest aspect in the collaboration series, after Communication (which is purely stateless). It is significantly cheaper than Social Graph because identity data changes rarely -- once a player sets their name and description, they update infrequently. The read cost comes almost entirely from the `inspect` command, which is the primary value the system delivers.

### Look Enhancement Cost (if implemented)

The look enhancement (including names in room contents) would add reads to every `look` command:

| Enhancement Level | Extra Reads per Look | Monthly Cost (10 looks/day/agent) |
|-------------------|---------------------|----------------------------------|
| Names only (Entity.name) | 1 per entity in room | 30 * 10 * 5 * 30 = 45,000 reads |
| Names + short_description | 2 per entity in room | 30 * 10 * 5 * 2 * 30 = 90,000 reads |
| No enhancement (current) | 0 | 0 |

The "names only" approach adds 45,000 reads/month at zero extra write cost. This is the recommended first step. At 1 RCU, the average load is 0.017 RCU -- well within capacity. Short descriptions can be added later if capacity permits.

## Future Considerations

1. **Equipment-driven appearance (doc 05 integration).** When the Equipment aspect is implemented, equipped items should modify the `equipment_summary` field via the `on_equipment_change` callable. Items would need a `visible_description` field on their Inventory aspect. A player wearing "a battered iron helm" and wielding "a glowing blue longsword" would have an equipment_summary like "Wearing a battered iron helm. Wielding a glowing blue longsword." This summary appears in `inspect` output and optionally in `look` contents.

2. **Portrait / avatar system.** For frontends that support rich media, Identity could store a URL to a portrait image or an ASCII art representation. The field would be a simple `portrait_url` or `ascii_portrait` string stored on the Identity record. For a text-only MUD, ASCII art is the appropriate medium: a 10-line, 40-character-wide ASCII portrait at ~400 bytes per entity.

3. **Race-specific abilities.** If the game adds racial mechanics (e.g., elves see farther, dwarves mine faster), the `attributes.race` field provides the data source. A separate RaceAbility system would read `attributes.race` from the Identity aspect and apply modifiers. The Identity aspect itself should not implement racial mechanics -- it is a data store, not a rules engine.

4. **Name history audit commands.** An admin command `name_history <entity_uuid>` could display the full name change log for an entity. This supports moderation (tracking impersonation) and dispute resolution. The data is already stored; only the admin command is needed.

5. **Identity templates.** Pre-built identity templates for common archetypes (warrior, mage, rogue, merchant, explorer) could be offered during character creation. An agent could issue `identity_template warrior` to populate description and attributes with warrior-appropriate defaults, then customize from there. This accelerates identity setup for agents that want a quick start.

6. **Short description auto-generation.** If a player sets a full description but no short_description, the system could auto-generate a one-line summary by truncating the first sentence of the description. This ensures `look` enhancement has something to display even for players who skip the short_description step.

7. **Name reservation.** If name uniqueness becomes socially important, a lightweight reservation system could be added: a separate DynamoDB table (`NAME_TABLE`) mapping lowercase names to entity UUIDs. The `name` command would check this table before allowing a change, using a conditional put_item to prevent races. Cost: 1 extra read + 1 extra write per name change, plus the new table.

8. **Appearance change events.** The current design does not broadcast appearance changes (description, attributes) because they are frequent during setup. A future enhancement could add an `appearance_changed` event that fires only after a cooldown period (e.g., maximum one broadcast per 5 minutes) to prevent spam while still notifying nearby entities of significant transformations.

9. **Identity for NPCs.** NPC entities could have Identity aspects with pre-built descriptions, attributes, and titles. A merchant NPC could have `description: "A portly dwarf with an enormous braided beard and an apron covered in tool marks"` and `title: "Master Artificer"`. This makes NPCs inspectable with the same command used for players, creating a consistent interaction model.

10. **Transformation system.** Spells, potions, or environmental effects that temporarily alter appearance could modify the Identity aspect data with a TTL-based restoration. "You drink the potion and feel your body stretching..." temporarily changes `attributes.build` to "Towering" and `attributes.height` to "3 meters" for 10 minutes. A Call.after() restores the original values. This integrates with the Magic system (doc 04) and Status Effects (doc 12).

11. **Identity verification for trades.** The Trading system (doc 13) could display identity data in trade confirmations: "Thornwick the Grey Wanderer wants to trade 5 iron ingots for your healing herb." This gives agents richer context for trade decisions than a raw UUID.

12. **Pronouns field.** Adding a conventional `pronouns` key to the attributes dict (e.g., "he/him", "they/them", "it/its") allows other systems to construct grammatically correct sentences: "Thornwick draws their sword" vs "Thornwick draws his sword." AI agents can read this field to generate appropriate natural language references.

13. **Appearance comparison.** A future `compare <entity_uuid>` command could show two entities' identity data side-by-side, highlighting differences. Useful for AI agents trying to distinguish entities with similar names or descriptions.

14. **Identity persistence across sessions.** The current design stores identity on LOCATION_TABLE keyed by entity UUID. Since player UUIDs are deterministic (uuid5 from user ID), identity data persists across login sessions automatically. A player who disconnects and reconnects retains their name, description, and attributes. No session management needed.

15. **Bulk identity loading for room population.** If the look enhancement requires loading Identity for every entity in a room, a batch_get_item call could load all Identity records in a single request instead of N sequential get_item calls. DynamoDB supports batch_get_item for up to 100 items per request. This reduces latency dramatically but requires adding batch operation support to the codebase, which currently uses only single-item operations.
