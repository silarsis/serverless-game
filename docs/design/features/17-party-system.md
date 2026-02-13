# Party / Group System Aspect

## What This Brings to the World

A party system transforms the game from a collection of isolated agents acting in parallel into a world where agents can genuinely collaborate. Without parties, the closest thing to cooperation is two agents happening to be in the same room and using `say` to coordinate in real time -- a fragile arrangement that breaks the moment one agent moves. There is no shared perception, no group communication channel, no way to know where your allies are, and no mechanism for coordinated movement. The Party system provides all of these. When two agents form a party, they gain a private communication channel that works across any distance, the ability to see each other's names instead of anonymous UUIDs, knowledge of each other's locations, and a follow mechanic that lets one agent lead while others automatically trail. These are not nice-to-have features -- they are the minimum viable primitives for any multi-agent task that takes more than one room and more than one conversation to accomplish.

For AI agents specifically, the party system is transformative. Consider an AI agent that has been given the goal "explore the cave dungeon and defeat the fire elemental." Without parties, the agent must do everything alone or hope to encounter another agent at the right place and time. With parties, the agent can post a recruitment message on a bulletin board (doc 16), wait for interested agents to `whisper` their UUID, send `party invite <uuid>`, and then use `party chat` to coordinate the approach. The party leader can `party follow` to ensure the group stays together as they navigate. Each member sees the others by name in room contents instead of inscrutable UUIDs, making it possible to direct commands at specific allies. The party system turns the game into a genuine multiplayer experience where AI agents can form teams, assign roles, and execute multi-step plans.

The architectural cost is real but bounded. Party state must be consistent across all members -- if Agent A thinks Agent B is in the party but Agent B does not have Agent A's party recorded, the system breaks. This means party mutations (invite, accept, leave, kick) must update multiple entities' aspect records, creating cross-entity writes that the architecture generally avoids. The follow mechanic adds writes to every movement by the followed entity. Cross-location party chat requires loading each member entity individually (not broadcast_to_location, which only reaches entities at a single location). These costs are proportional to party size, and with a cap of 6 members, the worst case is bounded. The party system is expensive per-operation but infrequent per-tick -- parties are formed rarely and dissolved rarely, while the ongoing costs (party chat, follow movement) are player-driven, not tick-driven.

## Critical Analysis

**Party state denormalized onto every member creates a consistency problem.** The design stores party membership on each member's Party aspect (member list, leader UUID, party ID). When Agent A invites Agent B and Agent B accepts, both Agent A's and Agent B's aspect records must be updated. If the Lambda writing Agent A's record succeeds but the Lambda writing Agent B's record fails (timeout, throttle, crash), Agent A thinks B is in the party but B does not know. The system has no transaction mechanism -- DynamoDB transactions exist but are not used anywhere in the codebase and would require loading multiple items in a single operation, which conflicts with the one-aspect-at-a-time pattern. The mitigation is to write the inviter's record first (as the source of truth) and have the acceptor's write include a verification step, but this only reduces the window -- it does not eliminate it.

**Cross-entity writes violate the "each aspect owns its data" principle.** When Agent A invites Agent B, Agent A's Lambda must write to both Agent A's Party aspect and Agent B's Party aspect. This is the same cross-aspect write pattern documented in the Taming system (where taming modifies the NPC aspect), but worse: Taming writes to a creature that the player is intentionally modifying, while Party writes to another player's data without their Lambda invocation handling the write. If Agent B's Party aspect is simultaneously being written by Agent B's own Lambda (e.g., B is accepting a different invitation), the writes race. The architecture has no locking mechanism.

**Party chat is O(M) entity reads per message, where M is party size.** Unlike `say` which uses `broadcast_to_location` (O(N) reads for N entities at one location), party chat must individually load each party member entity to call `push_event`. With a party of 6 members, each party chat message requires 5 entity reads (excluding self) + 5 push_event calls. At 50 chat messages per day across all parties, that is 250 entity reads per day -- negligible. But at 500 messages per day (10 active parties, 50 messages each), it is 2,500 reads. On a 1 RCU table, 2,500 reads per day is 0.03 reads/second -- within capacity but additive with all other read operations.

**Follow mechanic adds 1 entity read + 1 entity write + 2 broadcasts per follower per leader movement.** When the party leader moves, each follower must: (1) load their entity to get current location, (2) set their location to the leader's new location (1 entity write + departure broadcast + arrival broadcast). With 5 followers, each leader move triggers 5 entity reads + 5 entity writes + 10 broadcasts. Each broadcast is O(N) reads for N entities at the location. In a room with 10 entities, that is 100 additional reads per leader move. On a 1 WCU table with 5 entity writes, the writes alone take 5 seconds to drain. If the leader moves faster than once every 5 seconds, follow writes queue up and followers fall behind. This is the same problem as companion following (doc 15) but multiplied by party size.

**No atomic party dissolution means members can be stranded in inconsistent state.** When the leader leaves (`party leave`), the system must update the leader's record (clear party state) and every member's record (assign new leader or disband). With 6 members, that is 6 writes. If the Lambda crashes after writing 3 of 6 records, 3 members think the party exists with the old leader, and 3 (including the leader) think it is dissolved. There is no rollback, no distributed transaction, and no reconciliation mechanism. The mitigation is a "party check" step where members verify party consistency on their next action, but this adds reads and complexity.

**Party persistence across sessions is undefined.** When a player disconnects, their connection_id is cleared but their Party aspect data persists. The party continues to exist in the database. When the player reconnects, their Party aspect still has the party data. But what if all party members disconnect? The party persists forever in the database with no active members. There is no cleanup mechanism. Over time, the system accumulates orphaned party records. The solution is either (1) parties dissolve on leader disconnect, which is aggressive and frustrating, (2) a TTL on party state that expires after N hours of leader inactivity, or (3) accepting the orphaned data as harmless (it is -- a few hundred bytes per player in the aspect record, within 400KB limits even with thousands of orphaned parties).

**Shared look (seeing party member names instead of UUIDs) requires modifying the Land.look() response.** Currently, `look` returns a list of entity UUIDs from `room_entity.contents`. To show party member names, the look command must cross-reference the contents list against the viewer's party member list and replace UUIDs with names for matching entries. This adds 1 Party aspect read per `look` command. Since `look` is the second most common command after `move`, this adds a read to a high-frequency operation. The read goes to LOCATION_TABLE (shared), which is already under pressure from other aspects. At 50 agents each looking 30 times per day, that is 1,500 additional reads per day -- 0.017 reads/second, negligible alone but additive.

**Party size cap of 6 is arbitrary but architecturally motivated.** The follow mechanic cost scales linearly with party size. At 6 members, a leader move costs 5 follow-writes + ~50 broadcast reads. At 10 members, it costs 9 follow-writes + ~90 broadcast reads. At 20 members, the system becomes untenable on a 1 WCU table. The cap of 6 is the largest party size where follow mechanics remain responsive (follow writes drain in 5 seconds). Smaller parties (4) would be safer; larger parties (8+) would require abandoning real-time follow.

**Invitation flow has a TOCTOU race condition.** When Agent A invites Agent B, Agent A's Lambda checks that B is not already in a party (load B's Party aspect, check for existing party). Then Agent A creates the pending invitation. Between the check and the invite creation, Agent C could also invite Agent B. Both A and C believe their invitation is valid. When B accepts one, the other invitation is silently invalidated. This is not catastrophic (B joins one party, the other invitation becomes stale) but creates confusing state where A thinks B has a pending invitation.

**The party entity model (centralized vs. denormalized) is the fundamental architectural decision.** A centralized party entity (a separate DynamoDB item representing the party, with members listed) eliminates consistency problems -- there is one source of truth. But it adds a new entity type that must be loaded on every party operation, and it does not fit the aspect pattern (the party is not an aspect of any single entity). The denormalized model (party state on each member) fits the aspect pattern but creates the consistency problems described above. This design uses the denormalized model for consistency with the codebase, accepting the trade-offs.

**Overall assessment: high value, high complexity, moderate cost.** The party system is a critical enabler for multi-agent collaboration. Without it, agents cannot coordinate across rooms, cannot communicate privately as a group, and cannot move together. The architectural costs are real (cross-entity writes, consistency risks, follow mechanic overhead) but bounded by the party size cap. The consistency problems are the most concerning -- in a system with no transactions, keeping N entity records in sync is fundamentally fragile. The design mitigates this through verification steps and accepting eventual consistency, but developers should monitor for orphaned and inconsistent party states in production.

## Overview

The Party aspect enables formal group formation between entities. A party leader can invite other entities, who may accept or decline. Party members gain a private group chat channel, visibility into each other's names and locations, and a follow mechanic for coordinated movement. Parties are limited to 6 members, have a designated leader with kick authority, and persist across sessions. The system stores party state on each member's aspect record (denormalized model) with the leader's record as the authoritative source for resolving conflicts.

## Design Principles

**Parties are opt-in and consensual.** Joining a party requires an explicit invitation and acceptance. No entity can be added to a party without their consent. Leaving is always unilateral -- any member can leave at any time without approval.

**The leader's record is the source of truth.** In the denormalized model, every member stores party state. When records conflict (which should be rare but is possible due to race conditions), the leader's Party aspect record is authoritative. Members verify against the leader's record when inconsistencies are detected.

**Party communication works everywhere.** Unlike `say` (which broadcasts to the current room), `party chat` reaches all party members regardless of their location. This is the only cross-location communication channel in the game and is what makes parties genuinely useful for distributed coordination.

**Follow is automatic but not instant.** When the leader moves with followers, follower movement is triggered via SNS dispatch (`Call.now()`), not by direct writes in the leader's Lambda. This means followers move asynchronously -- typically within 1-2 seconds of the leader, depending on Lambda cold start and SNS delivery. The delay is noticeable but acceptable.

**Each member owns their party state.** The Party aspect stores party information on each member's entity. This avoids creating a new entity type (the party itself) and keeps the system within the existing aspect pattern. The cost is consistency management across members.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| party_id | str | "" | Unique identifier for the current party |
| party_role | str | "" | "leader" or "member" |
| party_leader_uuid | str | "" | UUID of the party leader |
| party_leader_name | str | "" | Display name of the party leader |
| party_members | list | [] | List of member info dicts |
| pending_invite | dict | {} | Incoming invitation awaiting response |
| outgoing_invites | list | [] | UUIDs of entities with pending invitations |
| following_uuid | str | "" | UUID of entity this member is auto-following |
| follow_enabled | bool | False | Whether auto-follow is active |

### Party Member Info Structure

Each entry in `party_members`:

```python
{
    "uuid": "member-uuid",
    "name": "AgentSmith",
    "role": "member",           # "leader" or "member"
    "joined_at": 1700000000,    # Unix timestamp
    "location": "room-uuid",    # Last known location (updated on party list)
}
```

### Pending Invite Structure

```python
{
    "from_uuid": "leader-uuid",
    "from_name": "PartyLeader",
    "party_id": "party-uuid",
    "invited_at": 1700000000,
    "expires_at": 1700000300,   # 5 minutes to accept
}
```

### Party Configuration Constants

```python
MAX_PARTY_SIZE = 6              # Maximum members including leader
INVITE_TIMEOUT_SECONDS = 300    # 5 minutes to accept an invitation
MAX_OUTGOING_INVITES = 3        # Max pending invitations per leader
```

## Commands

### `party invite <entity_uuid>`

```python
@player_command
def party_invite(self, entity_uuid: str) -> dict:
    """Invite an entity to join your party."""
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| entity_uuid | str | Yes | - | UUID of the entity to invite |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "party_invite_sent" |
| target_name | str | Name of the invited entity |
| target_uuid | str | UUID of the invited entity |
| party_id | str | Party identifier |
| party_size | int | Current party size |
| message | str | Confirmation message |

**Behaviour:**

1. Validate the inviter has a location
2. Validate the target exists and is at the same location
3. If the inviter is not in a party, create a new party with the inviter as leader
4. If the inviter is in a party but is not the leader, return error
5. Check party size against MAX_PARTY_SIZE
6. Check outgoing invites against MAX_OUTGOING_INVITES
7. Check target is not already in a party (load target's Party aspect)
8. Check target does not already have a pending invite from this party
9. Create a pending_invite on the target's Party aspect
10. Add target UUID to the inviter's outgoing_invites
11. Save both aspect records
12. Push an invitation event to the target

**Example:**

```python
# Player sends:
{"command": "party_invite", "data": {"entity_uuid": "agent-b-uuid"}}

# Inviter is not in a party yet -- create one
# party_id = "party-abc123" (generated UUID)
# Inviter becomes leader, party_members = [self]
# Load target entity, validate at same location
# Create pending_invite on target's Party aspect
# Push event to target

# Response:
{
    "type": "party_invite_sent",
    "target_name": "AgentB",
    "target_uuid": "agent-b-uuid",
    "party_id": "party-abc123",
    "party_size": 1,
    "message": "Invitation sent to AgentB. They have 5 minutes to accept."
}

# Event pushed to target:
{
    "type": "party_invitation",
    "from_name": "AgentA",
    "from_uuid": "agent-a-uuid",
    "party_id": "party-abc123",
    "party_size": 1,
    "message": "AgentA invites you to join their party. Use 'party accept' to join or 'party decline' to refuse."
}
```

**DynamoDB operations:** 1 read (self Party aspect, auto-loaded) + 1 read (target entity) + 1 read (target Party aspect) + 1 write (self Party aspect) + 1 write (target Party aspect). Total: 3 reads, 2 writes.

### `party accept`

```python
@player_command
def party_accept(self) -> dict:
    """Accept a pending party invitation."""
```

**Parameters:** None.

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "party_joined" |
| party_id | str | Party identifier |
| leader_name | str | Party leader's name |
| members | list | List of member names |
| party_size | int | New party size |
| message | str | Confirmation message |

**Behaviour:**

1. Check for a pending_invite on this entity's Party aspect
2. Check invitation has not expired (expires_at > now)
3. If expired, clear pending_invite and return error
4. Load the leader's Party aspect to verify the party still exists and has room
5. Add self to the leader's party_members list
6. Update self's Party aspect with party data (copy member list, set role="member", set leader info)
7. Broadcast party_member_joined to all existing party members
8. Update all existing members' party_members lists to include the new member
9. Clear pending_invite on self
10. Remove self from leader's outgoing_invites
11. Save all modified aspect records

**Example:**

```python
# Player sends:
{"command": "party_accept"}

# Player has pending_invite from AgentA
# Load AgentA's Party aspect -- party exists, size=1, room for more
# Add self to AgentA's party_members list
# Set self's party data: party_id, role="member", leader=AgentA
# Notify all existing members

# Response:
{
    "type": "party_joined",
    "party_id": "party-abc123",
    "leader_name": "AgentA",
    "members": ["AgentA", "AgentB"],
    "party_size": 2,
    "message": "You joined AgentA's party. Members: AgentA (leader), AgentB."
}

# Event pushed to all existing party members:
{
    "type": "party_member_joined",
    "member_name": "AgentB",
    "member_uuid": "agent-b-uuid",
    "party_size": 2,
    "message": "AgentB joined the party."
}
```

**DynamoDB operations:** 1 read (self Party aspect) + 1 read (leader entity) + 1 read (leader Party aspect) + M reads (existing member entities for push_event, M = current party size - 1) + 1 write (self Party aspect) + 1 write (leader Party aspect) + M writes (update each existing member's party_members). Total: 3 + M reads, 2 + M writes. For a party of 3 existing members: 6 reads, 5 writes.

### `party decline`

```python
@player_command
def party_decline(self) -> dict:
    """Decline a pending party invitation."""
```

**Parameters:** None.

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "party_invite_declined" |
| from_name | str | Name of the inviter |
| message | str | Confirmation message |

**Behaviour:**

1. Check for a pending_invite on this entity's Party aspect
2. If no pending invite, return error
3. Clear pending_invite
4. Notify the inviter via push_event
5. Remove self from the inviter's outgoing_invites
6. Save modified records

**Example:**

```python
# Player sends:
{"command": "party_decline"}

# Response:
{
    "type": "party_invite_declined",
    "from_name": "AgentA",
    "message": "You declined AgentA's party invitation."
}

# Event pushed to inviter:
{
    "type": "party_invite_rejected",
    "target_name": "AgentB",
    "target_uuid": "agent-b-uuid",
    "message": "AgentB declined your party invitation."
}
```

**DynamoDB operations:** 1 read (self Party aspect) + 1 read (leader entity) + 1 read (leader Party aspect) + 1 write (self Party aspect) + 1 write (leader Party aspect). Total: 3 reads, 2 writes.

### `party leave`

```python
@player_command
def party_leave(self) -> dict:
    """Leave the current party."""
```

**Parameters:** None.

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "party_left" |
| party_id | str | The party that was left |
| message | str | Confirmation message |

**Behaviour:**

1. Check that the entity is in a party
2. If the entity is the leader:
   a. If there are other members, promote the longest-tenured member to leader
   b. If no other members, dissolve the party (just clear self)
3. Remove self from all members' party_members lists
4. If follow_enabled, disable follow
5. Clear all party fields on self's Party aspect
6. Notify remaining members via push_event
7. Save all modified records

**Example (member leaving):**

```python
# Player (AgentB, member) sends:
{"command": "party_leave"}

# Remove AgentB from all members' party_members
# Clear AgentB's party state
# Notify remaining members

# Response:
{
    "type": "party_left",
    "party_id": "party-abc123",
    "message": "You left the party."
}

# Event pushed to remaining members:
{
    "type": "party_member_left",
    "member_name": "AgentB",
    "member_uuid": "agent-b-uuid",
    "party_size": 2,
    "message": "AgentB left the party."
}
```

**Example (leader leaving, successor promoted):**

```python
# Leader (AgentA) sends:
{"command": "party_leave"}

# AgentB is the longest-tenured member -- promote to leader
# Update all members' records: new leader = AgentB
# Clear AgentA's party state

# Response:
{
    "type": "party_left",
    "party_id": "party-abc123",
    "message": "You left the party. AgentB is the new party leader."
}

# Event pushed to remaining members:
{
    "type": "party_leader_changed",
    "old_leader": "AgentA",
    "new_leader": "AgentB",
    "new_leader_uuid": "agent-b-uuid",
    "reason": "leader_left",
    "message": "AgentA left the party. AgentB is now the party leader."
}
```

**DynamoDB operations:** 1 read (self Party aspect) + M reads (member entities for notification and record updates) + M reads (member Party aspects) + 1 write (self Party aspect) + M writes (member Party aspects). Total: 1 + 2M reads, 1 + M writes. For a party of 4 (leader + 3 members): 7 reads, 4 writes.

### `party kick <entity_uuid>`

```python
@player_command
def party_kick(self, entity_uuid: str) -> dict:
    """Kick a member from the party. Leader only."""
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| entity_uuid | str | Yes | - | UUID of the member to kick |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "party_kick_confirm" |
| kicked_name | str | Name of the kicked member |
| party_size | int | New party size |
| message | str | Confirmation message |

**Behaviour:**

1. Validate caller is the party leader
2. Validate target is in the party
3. Cannot kick self (use `party leave` instead)
4. Remove target from all members' party_members lists
5. Clear target's party state
6. Disable target's follow if active
7. Notify target and remaining members
8. Save all modified records

**Example:**

```python
# Leader sends:
{"command": "party_kick", "data": {"entity_uuid": "agent-c-uuid"}}

# Response:
{
    "type": "party_kick_confirm",
    "kicked_name": "AgentC",
    "party_size": 3,
    "message": "AgentC has been removed from the party."
}

# Event pushed to kicked member:
{
    "type": "party_kicked",
    "leader_name": "AgentA",
    "message": "You have been removed from the party by AgentA."
}

# Event pushed to remaining members:
{
    "type": "party_member_kicked",
    "member_name": "AgentC",
    "kicked_by": "AgentA",
    "party_size": 3,
    "message": "AgentC was removed from the party."
}
```

**DynamoDB operations:** Same as `party leave`: 1 + 2M reads, 1 + M writes.

### `party list`

```python
@player_command
def party_list(self) -> dict:
    """List party members and their locations."""
```

**Parameters:** None.

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "party_list" |
| party_id | str | Party identifier |
| leader_name | str | Leader's name |
| members | list | List of member detail dicts |
| party_size | int | Current party size |
| message | str | Formatted member list |

**Behaviour:**

1. Check that the entity is in a party
2. Load each member's entity to get their current location and connection status
3. For each member, resolve their location to room coordinates (load Land aspect for their location)
4. Return member list with names, locations, and online status

**Example:**

```python
# Player sends:
{"command": "party_list"}

# Load each member entity, check location and connection_id

# Response:
{
    "type": "party_list",
    "party_id": "party-abc123",
    "leader_name": "AgentA",
    "members": [
        {
            "uuid": "agent-a-uuid",
            "name": "AgentA",
            "role": "leader",
            "location_name": "Forest Clearing",
            "coordinates": [3, 5, 0],
            "online": true,
            "same_room": true
        },
        {
            "uuid": "agent-b-uuid",
            "name": "AgentB",
            "role": "member",
            "location_name": "Dense Forest",
            "coordinates": [3, 6, 0],
            "online": true,
            "same_room": false
        },
        {
            "uuid": "agent-c-uuid",
            "name": "AgentC",
            "role": "member",
            "location_name": "Unknown",
            "coordinates": null,
            "online": false,
            "same_room": false
        }
    ],
    "party_size": 3,
    "message": "=== Party (3/6) ===\n* AgentA (leader) - Forest Clearing (3,5,0) [online] [here]\n  AgentB - Dense Forest (3,6,0) [online]\n  AgentC - Unknown [offline]"
}
```

**DynamoDB operations:** M reads (member entities) + M reads (member location Land aspects for coordinates). Total: 2M reads, 0 writes. For a party of 4: 8 reads, 0 writes.

### `party chat <message>`

```python
@player_command
def party_chat(self, message: str) -> dict:
    """Send a message to all party members, regardless of location."""
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| message | str | Yes | - | The message to send |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "party_chat_confirm" |
| message | str | Confirmation message |

**Behaviour:**

1. Validate the entity is in a party
2. Validate message is non-empty
3. Load each party member entity (except self)
4. Push party_chat event to each member via push_event
5. No broadcast_to_location -- this is direct delivery to each member

**Example:**

```python
# Player (AgentA) sends:
{"command": "party_chat", "data": {"message": "Everyone meet at the cave entrance."}}

# Load each member entity, push event

# Response:
{
    "type": "party_chat_confirm",
    "message": "You tell the party: \"Everyone meet at the cave entrance.\""
}

# Event pushed to each party member:
{
    "type": "party_chat",
    "speaker": "AgentA",
    "speaker_uuid": "agent-a-uuid",
    "message": "Everyone meet at the cave entrance.",
    "display": "[Party] AgentA: Everyone meet at the cave entrance."
}
```

**DynamoDB operations:** M-1 reads (member entities, excluding self) + 0 writes. Total: M-1 reads, 0 writes. For a party of 4: 3 reads, 0 writes.

### `party follow <entity_uuid>`

```python
@player_command
def party_follow(self, entity_uuid: str) -> dict:
    """Automatically follow a party member when they move."""
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| entity_uuid | str | Yes | - | UUID of the party member to follow |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "party_follow_confirm" |
| following_name | str | Name of the entity being followed |
| message | str | Confirmation message |

**Behaviour:**

1. Validate the entity is in a party
2. Validate the target is also in the same party
3. Cannot follow self
4. Set following_uuid and follow_enabled on self's Party aspect
5. If currently at a different location than the target, immediately move to their location
6. Save self's Party aspect

**Example:**

```python
# Player (AgentB) sends:
{"command": "party_follow", "data": {"entity_uuid": "agent-a-uuid"}}

# Validate AgentA is in the same party
# Set following_uuid = "agent-a-uuid", follow_enabled = True
# AgentB is at (3, 6, 0), AgentA is at (3, 5, 0) -- different rooms
# Move AgentB to AgentA's location

# Response:
{
    "type": "party_follow_confirm",
    "following_name": "AgentA",
    "message": "You are now following AgentA. You will automatically move when they do."
}
```

**DynamoDB operations:** 1 read (target entity, to verify party membership and get location) + 1 write (self Party aspect) + 0-1 entity writes (if movement needed). Total: 1 read, 1-2 writes.

### `party unfollow`

```python
@player_command
def party_unfollow(self) -> dict:
    """Stop automatically following a party member."""
```

**Parameters:** None.

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "party_unfollow_confirm" |
| message | str | Confirmation message |

**Behaviour:**

1. Validate the entity is in a party
2. Validate follow is currently enabled
3. Clear following_uuid and set follow_enabled = False
4. Save Party aspect

**Example:**

```python
# Player sends:
{"command": "party_unfollow"}

# Response:
{
    "type": "party_unfollow_confirm",
    "message": "You stopped following AgentA."
}
```

**DynamoDB operations:** 0 additional reads + 1 write (self Party aspect). Total: 0 reads, 1 write.

### `party status`

```python
@player_command
def party_status(self) -> dict:
    """Show your current party status."""
```

**Parameters:** None.

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "party_status" |
| in_party | bool | Whether the entity is in a party |
| party_id | str | Party identifier (empty if not in party) |
| role | str | "leader", "member", or "" |
| leader_name | str | Leader's name |
| party_size | int | Number of members |
| following | str | Name of entity being followed (empty if not following) |
| pending_invite | dict | Pending invitation details, if any |
| message | str | Formatted status display |

**Behaviour:**

1. Read self's Party aspect data
2. Return current party state and any pending invitations

**Example:**

```python
# Player sends:
{"command": "party_status"}

# Response (in party):
{
    "type": "party_status",
    "in_party": true,
    "party_id": "party-abc123",
    "role": "member",
    "leader_name": "AgentA",
    "party_size": 3,
    "following": "AgentA",
    "pending_invite": {},
    "message": "Party: party-abc123 (3/6 members)\nRole: member\nLeader: AgentA\nFollowing: AgentA"
}

# Response (not in party, with pending invite):
{
    "type": "party_status",
    "in_party": false,
    "party_id": "",
    "role": "",
    "leader_name": "",
    "party_size": 0,
    "following": "",
    "pending_invite": {
        "from_name": "AgentA",
        "from_uuid": "agent-a-uuid",
        "expires_in": "3 minutes"
    },
    "message": "Not in a party.\nPending invitation from AgentA (expires in 3 minutes)."
}
```

**DynamoDB operations:** 0 additional reads (aspect already loaded) + 0 writes. Total: 0 reads, 0 writes.

## Callable Methods

### `follow_trigger`

```python
@callable
def follow_trigger(self, leader_uuid: str, destination_uuid: str) -> dict:
    """Called via SNS when the followed leader moves. Moves this entity to the destination."""
```

This is the core of the follow mechanic. When a party member with followers moves, their Lambda dispatches `Call.now()` to each follower's `follow_trigger`.

**Behaviour:**

```python
@callable
def follow_trigger(self, leader_uuid: str, destination_uuid: str) -> dict:
    """Automatically follow leader to new location."""
    # Verify we are still following this leader
    if not self.data.get("follow_enabled"):
        return {"type": "follow_skipped", "reason": "follow_disabled"}
    if self.data.get("following_uuid") != leader_uuid:
        return {"type": "follow_skipped", "reason": "following_different_entity"}

    # Verify we are still in the same party as the leader
    party_id = self.data.get("party_id", "")
    if not party_id:
        return {"type": "follow_skipped", "reason": "not_in_party"}

    # Move to the destination
    old_location = self.entity.location
    if old_location == destination_uuid:
        return {"type": "follow_skipped", "reason": "already_there"}

    self.entity.location = destination_uuid  # Triggers departure/arrival broadcasts

    return {
        "type": "follow_moved",
        "leader_uuid": leader_uuid,
        "destination": destination_uuid,
    }
```

**DynamoDB operations:** 1 read (self entity, already loaded by action dispatch) + 1 write (entity location change) + O(N) reads for departure broadcast + O(N) reads for arrival broadcast. Total: 1 + 2N reads, 1 write.

### `_notify_followers`

```python
def _notify_followers(self, destination_uuid: str) -> None:
    """Notify all followers in the party that the entity has moved."""
```

This is a private method called by the Land.move integration when a party member with followers moves.

**Behaviour:**

```python
def _notify_followers(self, destination_uuid: str) -> None:
    """Dispatch follow_trigger to all party members following this entity."""
    if not self.data.get("party_id"):
        return

    my_uuid = self.entity.uuid
    members = self.data.get("party_members", [])

    for member in members:
        member_uuid = member.get("uuid", "")
        if member_uuid == my_uuid:
            continue

        # We cannot check follow_enabled without loading each member's Party aspect
        # Instead, dispatch to all members and let follow_trigger filter
        # This is O(M) SNS publishes but avoids O(M) DynamoDB reads
        Call(
            tid=str(uuid4()),
            originator=my_uuid,
            uuid=member_uuid,
            aspect="Party",
            action="follow_trigger",
            leader_uuid=my_uuid,
            destination_uuid=destination_uuid,
        ).now()
```

**Note:** This dispatches to ALL party members, not just followers. Each member's `follow_trigger` checks whether they are actually following. This trades M SNS publishes (cheap: ~$0.0000005 each) for M DynamoDB reads (expensive at scale on a 1 RCU table). With a party of 6, that is 5 SNS publishes vs 5 DynamoDB reads. SNS is the cheaper option.

### `_verify_party_consistency`

```python
def _verify_party_consistency(self) -> bool:
    """Check this member's party state against the leader's. Fix if inconsistent."""
```

Called internally before party operations to detect and repair inconsistencies.

**Behaviour:**

```python
def _verify_party_consistency(self) -> bool:
    """Verify party state matches leader's record. Returns True if consistent."""
    party_id = self.data.get("party_id", "")
    if not party_id:
        return True  # Not in a party

    leader_uuid = self.data.get("party_leader_uuid", "")
    if not leader_uuid:
        # Corrupt state -- clear party
        self._clear_party_state()
        return False

    if leader_uuid == self.entity.uuid:
        return True  # We are the leader -- our record is authoritative

    try:
        leader_entity = Entity(uuid=leader_uuid)
        leader_party = leader_entity.aspect("Party")
    except KeyError:
        # Leader entity doesn't exist -- party is orphaned
        self._clear_party_state()
        return False

    # Check leader has a party with the same ID
    if leader_party.data.get("party_id") != party_id:
        self._clear_party_state()
        return False

    # Check we are in the leader's member list
    leader_members = leader_party.data.get("party_members", [])
    member_uuids = [m.get("uuid") for m in leader_members]
    if self.entity.uuid not in member_uuids:
        self._clear_party_state()
        return False

    # Sync member list from leader (leader is source of truth)
    self.data["party_members"] = leader_members
    self._save()
    return True

def _clear_party_state(self):
    """Clear all party-related fields."""
    self.data["party_id"] = ""
    self.data["party_role"] = ""
    self.data["party_leader_uuid"] = ""
    self.data["party_leader_name"] = ""
    self.data["party_members"] = []
    self.data["following_uuid"] = ""
    self.data["follow_enabled"] = False
    self.data["outgoing_invites"] = []
    self._save()
```

**DynamoDB operations:** 1 read (leader entity) + 1 read (leader Party aspect) + 0-1 writes (save if updated or cleared). Total: 2 reads, 0-1 writes.

## Events

### `party_invitation`

Pushed to an entity when they receive a party invitation.

```python
{
    "type": "party_invitation",
    "from_name": "AgentA",
    "from_uuid": "agent-a-uuid",
    "party_id": "party-abc123",
    "party_size": 2,
    "message": "AgentA invites you to join their party (2/6 members). Use 'party accept' to join or 'party decline' to refuse."
}
```

### `party_member_joined`

Pushed to all existing party members when a new member joins.

```python
{
    "type": "party_member_joined",
    "member_name": "AgentC",
    "member_uuid": "agent-c-uuid",
    "party_size": 4,
    "message": "AgentC joined the party. (4/6 members)"
}
```

### `party_member_left`

Pushed to remaining party members when someone leaves.

```python
{
    "type": "party_member_left",
    "member_name": "AgentB",
    "member_uuid": "agent-b-uuid",
    "party_size": 3,
    "message": "AgentB left the party. (3/6 members)"
}
```

### `party_leader_changed`

Pushed to all members when leadership transfers.

```python
{
    "type": "party_leader_changed",
    "old_leader": "AgentA",
    "new_leader": "AgentB",
    "new_leader_uuid": "agent-b-uuid",
    "reason": "leader_left",
    "message": "AgentA left the party. AgentB is now the party leader."
}
```

### `party_kicked`

Pushed to the kicked member.

```python
{
    "type": "party_kicked",
    "leader_name": "AgentA",
    "message": "You have been removed from the party by AgentA."
}
```

### `party_member_kicked`

Pushed to remaining members when someone is kicked.

```python
{
    "type": "party_member_kicked",
    "member_name": "AgentC",
    "kicked_by": "AgentA",
    "party_size": 3,
    "message": "AgentC was removed from the party by AgentA."
}
```

### `party_chat`

Pushed to all party members when someone uses party chat.

```python
{
    "type": "party_chat",
    "speaker": "AgentA",
    "speaker_uuid": "agent-a-uuid",
    "message": "Everyone meet at the cave entrance.",
    "display": "[Party] AgentA: Everyone meet at the cave entrance."
}
```

### `party_invite_rejected`

Pushed to the inviter when an invitation is declined.

```python
{
    "type": "party_invite_rejected",
    "target_name": "AgentB",
    "target_uuid": "agent-b-uuid",
    "message": "AgentB declined your party invitation."
}
```

### `party_invite_expired`

Pushed to the inviter when an invitation expires.

```python
{
    "type": "party_invite_expired",
    "target_name": "AgentB",
    "target_uuid": "agent-b-uuid",
    "message": "Your party invitation to AgentB has expired."
}
```

### `party_follow_moved`

Pushed to a follower when they are auto-moved by the follow mechanic.

```python
{
    "type": "party_follow_moved",
    "leader_name": "AgentA",
    "destination": "room-uuid",
    "message": "You follow AgentA."
}
```

### `party_disbanded`

Pushed to all members when the party is dissolved (last member leaves or leader disbands).

```python
{
    "type": "party_disbanded",
    "party_id": "party-abc123",
    "message": "The party has been disbanded."
}
```

## Integration Points

### Party + Land (shared look, follow mechanic)

**Shared look:** The `look` command must be modified to show party member names instead of raw UUIDs in the room contents list. When a player uses `look`, the response includes a `contents` list of entity UUIDs. The Party aspect provides a name-resolution layer:

```python
# Modification to Land.look() -- after getting room_entity_contents:
# Load the looking player's Party aspect
try:
    party_aspect = self.entity.aspect("Party")
    party_member_uuids = {
        m["uuid"]: m["name"]
        for m in party_aspect.data.get("party_members", [])
    }
except (ValueError, KeyError):
    party_member_uuids = {}

# Enhance contents with party member names
enhanced_contents = []
for entity_uuid in room_entity_contents:
    entry = {"uuid": entity_uuid}
    if entity_uuid in party_member_uuids:
        entry["name"] = party_member_uuids[entity_uuid]
        entry["is_party_member"] = True
    enhanced_contents.append(entry)

# Return enhanced_contents instead of raw UUID list
```

**Follow mechanic integration with Land.move():** When a party member moves, `_notify_followers()` must be called. This can be hooked into the entity location setter or into `Land.move()`:

```python
# In Land.move(), after setting entity.location:
try:
    party = self.entity.aspect("Party")
    if party.data.get("party_id"):
        party._notify_followers(dest_uuid)
except (ValueError, KeyError):
    pass
```

This adds 1 Party aspect read to every `move` command. The aspect is loaded from the cache if it was accessed earlier in the same Lambda invocation.

### Party + Communication (party chat vs say/whisper)

Party chat is a third communication channel alongside `say` (location broadcast) and `whisper` (direct to one entity). The channels serve different purposes:

| Channel | Scope | Persistence | Use Case |
|---------|-------|-------------|----------|
| `say` | Same room | None | General conversation, NPC interaction |
| `whisper` | One entity, any location | None | Private 1:1 messages |
| `party chat` | All party members, any location | None | Group coordination |

Party chat does not replace `say` or `whisper`. Agents in a party who want to talk to non-party entities at their location still use `say`. Agents who want a private 1:1 conversation within the party use `whisper`.

### Party + Combat (shared threat awareness)

When a party member enters combat, other party members at the same location could receive combat awareness events. This is a future integration point, not part of the initial implementation:

```python
# Future: In Combat.attack(), if attacker is in a party:
# Notify co-located party members of the combat engagement
# Party members could auto-enter combat (assist mode)
```

### Party + BulletinBoard (party recruitment)

The bulletin board system (doc 16) and party system work together for asynchronous party formation. The workflow:

1. Agent A posts to a bulletin board: `post "LFG: Cave dungeon raid. Need healer and DPS. Whisper me: <uuid>" help-wanted`
2. Agent B reads the post at a later time
3. Agent B whispers Agent A to arrange a meeting
4. Agent A and Agent B meet at the same location
5. Agent A uses `party invite <agent-b-uuid>` to formalize the group

### Party + Cartography (shared navigation)

Party members following the leader benefit from the Cartography auto-recording: each follower's Cartography aspect records the rooms they pass through while following. This gives followers a map of the path taken, even if they were not actively navigating.

The `party list` command shows member locations with coordinates, which can be used with the `navigate` command to find the path to a party member's location.

### Party + NPC/Companion (NPC party members)

In the future, NPC companions (doc 15) could be added to parties. A tamed wolf with `behavior="companion"` could be invited to the party, giving it access to party chat events (which its NPC AI could process) and shared look. This is architecturally feasible -- the Party aspect can be added to NPC entities the same as player entities. The NPC tick loop would need a handler for `party_invitation` events and `party_chat` events.

### Party + Trading (party loot splitting)

A future enhancement could add a party loot mode: when any party member picks up an item or receives gold, the party system distributes it according to a configured split (equal, leader-decides, free-for-all). This requires intercepting Inventory.take() and Trading operations for party members.

## Error Handling

### Command Errors

| Error Condition | Command | Response |
|----------------|---------|----------|
| Player has no location | party_invite | `{"type": "error", "message": "You are nowhere."}` |
| Target not at same location | party_invite | `{"type": "error", "message": "That entity isn't here."}` |
| Target doesn't exist | party_invite | `{"type": "error", "message": "That entity doesn't exist."}` |
| Not the party leader | party_invite, party_kick | `{"type": "error", "message": "Only the party leader can do that."}` |
| Party is full (6/6) | party_invite | `{"type": "error", "message": "The party is full (6/6 members)."}` |
| Target already in a party | party_invite | `{"type": "error", "message": "That entity is already in a party."}` |
| Target already has pending invite | party_invite | `{"type": "error", "message": "That entity already has a pending invitation."}` |
| Too many outgoing invites | party_invite | `{"type": "error", "message": "You have too many pending invitations (max 3)."}` |
| No pending invitation | party_accept, party_decline | `{"type": "error", "message": "You don't have a pending party invitation."}` |
| Invitation expired | party_accept | `{"type": "error", "message": "That invitation has expired."}` |
| Not in a party | party_leave, party_chat, party_list, party_follow, party_unfollow | `{"type": "error", "message": "You are not in a party."}` |
| Kicking self | party_kick | `{"type": "error", "message": "You can't kick yourself. Use 'party leave' instead."}` |
| Following self | party_follow | `{"type": "error", "message": "You can't follow yourself."}` |
| Target not in party | party_follow, party_kick | `{"type": "error", "message": "That entity is not in your party."}` |
| Already following | party_follow | `{"type": "error", "message": "You are already following that entity."}` |
| Not following anyone | party_unfollow | `{"type": "error", "message": "You are not following anyone."}` |
| Empty message | party_chat | `{"type": "error", "message": "Say what?"}` |

### Consistency Errors

| Error Condition | Handling |
|----------------|----------|
| Leader entity deleted while party active | `_verify_party_consistency()` detects missing leader, clears all members' party state on their next party operation. |
| Member's party_id doesn't match leader's | `_verify_party_consistency()` syncs from leader or clears member state. |
| Member not in leader's member list | `_verify_party_consistency()` clears member's party state. |
| Party ID exists on member but leader has no party | `_verify_party_consistency()` clears member's party state. |
| Concurrent invite acceptance race | Second acceptor's write to leader's record may overwrite first acceptor. Mitigated by re-reading leader's record before writing. |
| Follow trigger for entity no longer following | `follow_trigger` checks `follow_enabled` and `following_uuid` before moving. Returns silently if not following. |

### Implementation Code

The core implementation patterns are shown below. The `party_invite` method demonstrates party creation and cross-entity writes. The `party_accept` method shows the denormalized member sync. The `follow_trigger` callable shows the SNS-based follow mechanic. The `party_leave`, `party_kick`, `party_decline`, `party_chat`, `party_follow`, `party_unfollow`, `party_list`, and `party_status` commands follow the same patterns established by invite and accept.

```python
import logging
import time
from uuid import uuid4

from .decorators import player_command
from .handler import lambdaHandler
from .thing import Aspect, Call, Entity, IdType, callable

logger = logging.getLogger(__name__)

MAX_PARTY_SIZE = 6
INVITE_TIMEOUT_SECONDS = 300
MAX_OUTGOING_INVITES = 3


class Party(Aspect):
    """Aspect handling party/group formation and coordination."""

    _tableName = "LOCATION_TABLE"

    @player_command
    def party_invite(self, entity_uuid: str) -> dict:
        """Invite an entity to join your party."""
        if not entity_uuid:
            return {"type": "error", "message": "Invite whom?"}

        location_uuid = self.entity.location
        if not location_uuid:
            return {"type": "error", "message": "You are nowhere."}

        try:
            target_entity = Entity(uuid=entity_uuid)
        except KeyError:
            return {"type": "error", "message": "That entity doesn't exist."}

        if target_entity.location != location_uuid:
            return {"type": "error", "message": "That entity isn't here."}

        # If not in a party, create one with self as leader
        if not self.data.get("party_id"):
            party_id = f"party-{str(uuid4())[:8]}"
            now = int(time.time())
            self.data["party_id"] = party_id
            self.data["party_role"] = "leader"
            self.data["party_leader_uuid"] = self.entity.uuid
            self.data["party_leader_name"] = self.entity.name
            self.data["party_members"] = [{
                "uuid": self.entity.uuid, "name": self.entity.name,
                "role": "leader", "joined_at": now, "location": location_uuid,
            }]
            self.data["outgoing_invites"] = []

        if self.data.get("party_role") != "leader":
            return {"type": "error", "message": "Only the party leader can invite new members."}

        members = self.data.get("party_members", [])
        if len(members) >= MAX_PARTY_SIZE:
            return {"type": "error", "message": f"The party is full ({MAX_PARTY_SIZE}/{MAX_PARTY_SIZE} members)."}

        # Validate target is available
        target_party = target_entity.aspect("Party")
        if target_party.data.get("party_id"):
            return {"type": "error", "message": "That entity is already in a party."}

        # Create invitation on target (cross-entity write)
        now = int(time.time())
        target_party.data["pending_invite"] = {
            "from_uuid": self.entity.uuid, "from_name": self.entity.name,
            "party_id": self.data["party_id"],
            "invited_at": now, "expires_at": now + INVITE_TIMEOUT_SECONDS,
        }
        target_party._save()

        self.data.setdefault("outgoing_invites", []).append(entity_uuid)
        self._save()

        target_entity.push_event({
            "type": "party_invitation", "from_name": self.entity.name,
            "from_uuid": self.entity.uuid, "party_id": self.data["party_id"],
            "party_size": len(members),
            "message": f"{self.entity.name} invites you to join their party. Use 'party_accept' to join.",
        })

        # Schedule expiration via Step Functions
        Call(tid=str(uuid4()), originator=self.entity.uuid, uuid=entity_uuid,
             aspect="Party", action="expire_invite",
             party_id=self.data["party_id"], inviter_uuid=self.entity.uuid,
        ).after(seconds=INVITE_TIMEOUT_SECONDS)

        return {
            "type": "party_invite_sent", "target_name": target_entity.name,
            "target_uuid": entity_uuid, "party_id": self.data["party_id"],
            "party_size": len(members),
            "message": f"Invitation sent to {target_entity.name}. They have 5 minutes to accept.",
        }

    @player_command
    def party_accept(self) -> dict:
        """Accept a pending party invitation."""
        invite = self.data.get("pending_invite", {})
        if not invite or not invite.get("from_uuid"):
            return {"type": "error", "message": "You don't have a pending party invitation."}

        now = int(time.time())
        if now > invite.get("expires_at", 0):
            self.data["pending_invite"] = {}
            self._save()
            return {"type": "error", "message": "That invitation has expired."}

        leader_uuid = invite["from_uuid"]
        party_id = invite["party_id"]

        # Load and verify leader's party
        try:
            leader_entity = Entity(uuid=leader_uuid)
            leader_party = leader_entity.aspect("Party")
        except KeyError:
            self.data["pending_invite"] = {}
            self._save()
            return {"type": "error", "message": "The party leader no longer exists."}

        if leader_party.data.get("party_id") != party_id:
            self.data["pending_invite"] = {}
            self._save()
            return {"type": "error", "message": "That party no longer exists."}

        leader_members = leader_party.data.get("party_members", [])
        if len(leader_members) >= MAX_PARTY_SIZE:
            self.data["pending_invite"] = {}
            self._save()
            return {"type": "error", "message": f"The party is full."}

        # Add self to leader's member list and save leader
        new_member = {"uuid": self.entity.uuid, "name": self.entity.name,
                      "role": "member", "joined_at": now, "location": self.entity.location or ""}
        leader_members.append(new_member)
        leader_party.data["party_members"] = leader_members
        leader_party._save()

        # Set self's party state (denormalized copy of member list)
        self.data.update({"party_id": party_id, "party_role": "member",
                          "party_leader_uuid": leader_uuid, "party_leader_name": invite["from_name"],
                          "party_members": leader_members, "pending_invite": {},
                          "following_uuid": "", "follow_enabled": False})
        self._save()

        # Sync all existing members (cross-entity writes, O(M) writes)
        for member in leader_members:
            member_uuid = member.get("uuid", "")
            if member_uuid in (self.entity.uuid, leader_uuid):
                continue
            try:
                member_entity = Entity(uuid=member_uuid)
                member_party = member_entity.aspect("Party")
                member_party.data["party_members"] = leader_members
                member_party._save()
                member_entity.push_event({"type": "party_member_joined",
                    "member_name": self.entity.name, "member_uuid": self.entity.uuid,
                    "party_size": len(leader_members),
                    "message": f"{self.entity.name} joined the party."})
            except (KeyError, ValueError):
                continue

        leader_entity.push_event({"type": "party_member_joined",
            "member_name": self.entity.name, "party_size": len(leader_members),
            "message": f"{self.entity.name} joined the party."})

        return {"type": "party_joined", "party_id": party_id,
                "leader_name": invite["from_name"],
                "members": [m["name"] for m in leader_members],
                "party_size": len(leader_members),
                "message": f"You joined {invite['from_name']}'s party."}

    # party_decline: Clear pending_invite, notify inviter, clean outgoing_invites. 3 reads, 2 writes.
    # party_leave: Remove self from all members' lists. If leader, promote successor. O(M) writes.
    # party_kick: Leader-only. Remove target, clear target state, update all members. O(M) writes.
    # party_list: Load each member entity + Land aspect for coordinates. O(2M) reads, 0 writes.
    # party_chat: Load each member entity, push_event. O(M-1) reads, 0 writes.
    # party_follow: Set following_uuid/follow_enabled, optionally move to target. 1 read, 1-2 writes.
    # party_unfollow: Clear following_uuid/follow_enabled. 0 reads, 1 write.
    # party_status: Read self aspect data only. 0 reads, 0 writes.

    @callable
    def follow_trigger(self, leader_uuid: str, destination_uuid: str) -> dict:
        """Called via SNS when the followed leader moves. Moves this entity to follow."""
        if not self.data.get("follow_enabled"):
            return {"type": "follow_skipped", "reason": "follow_disabled"}
        if self.data.get("following_uuid") != leader_uuid:
            return {"type": "follow_skipped", "reason": "following_different_entity"}
        if not self.data.get("party_id"):
            return {"type": "follow_skipped", "reason": "not_in_party"}
        if self.entity.location == destination_uuid:
            return {"type": "follow_skipped", "reason": "already_there"}

        self.entity.location = destination_uuid  # Triggers departure/arrival broadcasts

        leader_name = next((m.get("name", "someone") for m in self.data.get("party_members", [])
                           if m.get("uuid") == leader_uuid), "someone")
        self.entity.push_event({"type": "party_follow_moved", "leader_name": leader_name,
                                "destination": destination_uuid,
                                "message": f"You follow {leader_name}."})
        return {"type": "follow_moved", "leader_uuid": leader_uuid, "destination": destination_uuid}

    @callable
    def expire_invite(self, party_id: str, inviter_uuid: str) -> dict:
        """Called via Step Functions when an invitation expires."""
        invite = self.data.get("pending_invite", {})
        if not invite or invite.get("party_id") != party_id:
            return {"type": "invite_already_handled"}

        self.data["pending_invite"] = {}
        self._save()

        try:
            inviter_entity = Entity(uuid=inviter_uuid)
            inviter_party = inviter_entity.aspect("Party")
            outgoing = inviter_party.data.get("outgoing_invites", [])
            if self.entity.uuid in outgoing:
                outgoing.remove(self.entity.uuid)
            inviter_party.data["outgoing_invites"] = outgoing
            inviter_party._save()
            inviter_entity.push_event({"type": "party_invite_expired",
                "target_name": self.entity.name,
                "message": f"Your party invitation to {self.entity.name} has expired."})
        except (KeyError, ValueError):
            pass
        return {"type": "invite_expired", "party_id": party_id}

    def _clear_party_state(self):
        """Clear all party-related fields."""
        for field in ["party_id", "party_role", "party_leader_uuid", "party_leader_name",
                      "following_uuid"]:
            self.data[field] = ""
        self.data["party_members"] = []
        self.data["follow_enabled"] = False
        self.data["outgoing_invites"] = []
        self._save()

    def _verify_party_consistency(self) -> bool:
        """Check this member's party state against the leader's. Fix if inconsistent."""
        party_id = self.data.get("party_id", "")
        if not party_id:
            return True
        leader_uuid = self.data.get("party_leader_uuid", "")
        if not leader_uuid or leader_uuid == self.entity.uuid:
            return bool(leader_uuid)
        try:
            leader_entity = Entity(uuid=leader_uuid)
            leader_party = leader_entity.aspect("Party")
        except KeyError:
            self._clear_party_state()
            return False
        if leader_party.data.get("party_id") != party_id:
            self._clear_party_state()
            return False
        leader_members = leader_party.data.get("party_members", [])
        if self.entity.uuid not in [m.get("uuid") for m in leader_members]:
            self._clear_party_state()
            return False
        self.data["party_members"] = leader_members
        self._save()
        return True

    def _notify_followers(self, destination_uuid: str) -> None:
        """Dispatch follow_trigger to all party members via SNS."""
        if not self.data.get("party_id"):
            return
        my_uuid = self.entity.uuid
        for member in self.data.get("party_members", []):
            member_uuid = member.get("uuid", "")
            if member_uuid == my_uuid:
                continue
            Call(tid=str(uuid4()), originator=my_uuid, uuid=member_uuid,
                 aspect="Party", action="follow_trigger",
                 leader_uuid=my_uuid, destination_uuid=destination_uuid).now()


handler = lambdaHandler(Entity)
```

## Cost Analysis

### Per-Operation DynamoDB Costs

| Operation | Reads | Writes | Notes |
|-----------|-------|--------|-------|
| `party_invite` | 3 | 2 | Self aspect + target entity + target aspect. Write self + target. |
| `party_accept` | 3 + M | 2 + M | Leader entity + leader aspect + M member entity loads. Write self + leader + M members. |
| `party_decline` | 3 | 2 | Self + inviter entity + inviter aspect. Write self + inviter. |
| `party_leave` | 1 + 2M | 1 + M | Self + M member entities + M member aspects. Write self + M members. |
| `party_kick` | 1 + 2M | 1 + M | Same as leave plus kicked entity. |
| `party_list` | 2M | 0 | M member entities + M Land aspects for coordinates. |
| `party_chat` | M - 1 | 0 | M-1 member entity loads for push_event. |
| `party_follow` | 1 | 1-2 | Target entity. Write self aspect + maybe entity location. |
| `party_unfollow` | 0 | 1 | Self aspect write only. |
| `party_status` | 0 | 0 | Self aspect data only (already loaded). |
| `follow_trigger` | 1 + 2N | 1 | Entity already loaded. 1 entity write + 2 broadcasts (N entities per room). |
| `expire_invite` | 2 | 2 | Target aspect + inviter entity+aspect. Write both. |

Where M = party size, N = entities at location.

### Step Functions Costs

| Operation | State Transitions | Cost per Invocation |
|-----------|-------------------|---------------------|
| `expire_invite` (per invitation) | 1 | $0.000025 |

### Monthly Cost Projections

**Assumptions:** 50 agents, 10 active parties averaging 4 members each, 20 party chats/day per party, 50 leader movements/day per party, 5 party formations/dissolutions per day.

| Cost Category | Calculation | Monthly Cost |
|---------------|-------------|--------------|
| Party formation (invite+accept) | 5/day * 30 days * (5 reads + 4 writes) per formation | ~1,350 ops | negligible |
| Party chat | 10 parties * 20 msgs/day * 30 days * 3 reads/msg | 18,000 reads | negligible at 1 RCU |
| Party list | 10 parties * 5 checks/day * 30 days * 8 reads | 12,000 reads | negligible |
| Follow movement | 10 parties * 50 moves/day * 30 days * 3 followers * (1 write + ~10 reads) | 49,500 writes + 165,000 reads | **PRIMARY COST** |
| Invite expiration | 5 formations/day * 2 invites avg * 30 days = 300 transitions | 300 * $0.000025 = $0.0075 | negligible |
| **Total Step Functions** | | **< $1/month** |
| **Total DynamoDB** | | **Follow movement dominates: ~50K writes/month, ~165K reads/month** |

### Follow Movement Cost Analysis

Follow movement is the most expensive operation. Per leader move with 3 followers:
- 3 SNS publishes: $0.0000015 (negligible)
- 3 follow_trigger Lambda invocations: $0.0000006 (negligible)
- 3 entity writes (location change): 3 WCU-seconds
- 6 broadcasts (3 departures + 3 arrivals): O(6N) reads where N = entities per room
- At N=10 entities per room: 60 reads per leader move

On a 1 WCU table with 3 entity writes per leader move:
- Writes drain in 3 seconds. Leader moves faster than every 3 seconds = write throttling.
- At 10 parties each with a leader moving every 30 seconds and 3 followers: 30 writes per 30 seconds = 1 write/second. Within capacity.

### Cost Optimization: Batch Follow Writes

If follow becomes a bottleneck, the movement can be batched: instead of individual `Call.now()` per follower, a single `Call.now()` dispatches to a `batch_follow` callable that processes all followers in one Lambda invocation. This reduces Lambda invocations from M-1 to 1 per leader move, but does not reduce DynamoDB writes (each follower's entity still needs its location updated).

## Future Considerations

1. **Party experience sharing.** When a party member defeats an enemy or completes a quest, distribute XP to all party members (possibly scaled by proximity). This incentivizes staying together and rewards group play. Requires hooking into Combat._on_death() and Quest._complete_quest().

2. **Party roles (tank, healer, DPS).** Allow members to set a role that other members can see via `party_list`. Purely informational in the initial implementation, but future combat integration could use roles for auto-targeting (companions attack the tank's target, healer prioritizes lowest-HP member).

3. **Party loot distribution modes.** Free-for-all (default), round-robin (rotate who gets loot), need-before-greed (members roll on items). Requires intercepting item drops and adding a loot distribution state machine.

4. **Party waypoints.** The leader can set a party waypoint that all members can navigate to. Integrates with the Cartography system: `party waypoint set <name>` saves the leader's current coordinates as a shared waypoint visible to all members.

5. **Party size tiers.** Small party (2-3): no overhead. Standard party (4-6): current design. Raid group (7-12): no follow mechanic (too expensive), no shared look (too many names), party chat only. Raid groups would be useful for large-scale content (dungeon bosses, faction wars) but require significant cost analysis.

6. **Persistent party identity.** Parties currently have a UUID but no name or persistent identity. Adding `party name <name>` would let parties brand themselves ("The Cave Crawlers"). This is purely cosmetic but adds social value.

7. **Party finder / LFG system.** A global command `lfg <role> <description>` that registers the entity as looking for a group. Other entities can `lfg list` to see available agents. This complements the bulletin board's help-wanted posts with a real-time matchmaking system.

8. **Party buff / proximity bonus.** When all party members are in the same room, they receive a small combat or skill bonus. This rewards physical co-location and gives the follow mechanic additional value beyond convenience.

9. **NPC party members.** Allow tamed companions (doc 15) and potentially hired NPC mercenaries to join parties. NPC party members would receive party_chat events processed by their AI tick loop, enabling NPC-player group coordination. The NPC's follow behavior (already implemented via companion following) would integrate with the party follow mechanic.

10. **Cross-party alliances.** Two parties can form an alliance, gaining access to an inter-party chat channel. This enables larger-scale coordination without the cost of a single large party. Alliances dissolve when one party disbands.

11. **Party history and statistics.** Track party achievements: rooms explored together, enemies defeated, total chat messages. Display via `party stats`. Adds a persistent record of group accomplishment that survives individual sessions.

12. **Automatic party dissolution.** If all party members are offline for more than N hours (e.g., 24 hours), automatically disband the party. This requires a periodic check via Step Functions, adding $0.000025 per party per check interval. At one check per hour per party, 10 active parties cost $0.006/month -- trivial.

13. **Vote-kick system.** Instead of leader-only kick, allow majority vote to kick a member. Prevents leader abuse in parties where the leader goes rogue. Adds a voting state machine with a timeout, which is more complex but more democratic.

14. **Party inventory (shared stash).** A shared inventory accessible to all party members. Items placed in the party stash are available to any member. This requires a new entity (the party stash) with an Inventory aspect, and solves the coordination problem of distributing loot. The party stash entity's location could be set to the leader's UUID, and it follows the leader when the party moves.
