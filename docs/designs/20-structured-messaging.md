# Structured Communication Protocol / Agent Messaging System

## What This Brings to the World

The current Communication aspect offers three tools: `say`, `whisper`, and `emote`. All three transmit free-text strings. For human players, this is fine -- natural language is their native interface. For AI agents, it is a disaster. An agent that receives `{"type": "say", "speaker": "Pathfinder-7", "message": "Hey, want to come help me clear the cave to the north? I found some iron ore in there and I think there's a boss. I'll split the loot 50/50."}` must parse that sentence, extract the intent (request for help), the location (cave to the north), the incentive (iron ore, boss loot), and the terms (50/50 split), then construct a natural language response, hope the other agent parses *that* correctly, and so on. Every exchange loses fidelity. Ambiguity compounds. Two agents trying to coordinate through natural language is like two computers communicating by reading each other's screen with OCR -- it works, technically, but it throws away everything that makes machine-to-machine communication powerful.

Structured messaging adds a parallel communication layer designed for programmatic coordination. Agents can send typed requests with explicit parameters, receive typed responses, broadcast machine-parseable announcements with topic tags, exchange lightweight real-time signals, run polls, and propose binding contracts. Every message is a JSON object with a known schema. An agent receiving a `request` event does not need to parse English -- it reads the `action` field, checks the `params` dict, and makes a decision. The response is equally structured: `accept`, `decline`, or `counter` with modified parameters. This transforms agent coordination from a natural language processing problem into a protocol problem, which is exactly the kind of problem software is good at solving.

This system is the connective tissue for every collaboration feature in the game. Agent profiles (doc 19) let agents discover each other's capabilities. Parties (doc 17) let agents travel and fight together. Projects (doc 18) let agents work toward shared goals. But none of those systems answer the question "how do two agents actually negotiate the terms?" Structured messaging is the answer. An agent inspects another's profile, sends a `request` to join their party, receives an `accept`, then proposes a `contract` defining loot split terms. Every step is typed, tracked, and unambiguous. Without this system, the collaboration features are isolated islands with no bridge between them. With it, they form a coherent workflow that agents can execute without any natural language processing.

## Critical Analysis

**Request tracking creates unbounded state growth on the aspect record.** Every `request` command creates a request object stored in the sender's `outgoing_requests` list and the receiver's `incoming_requests` list. If agents are active, a single agent might send 50 requests per hour -- join party, trade items, meet at location, share resources. With a 60-second expiry, the maximum pending requests are bounded, but completed and expired requests need cleanup. If cleanup runs on the aspect's save (filtering out expired entries), each save rewrites the full list. If cleanup is deferred, the list grows. At 200 bytes per request record, 1000 accumulated requests consume 200KB -- half the DynamoDB 400KB item limit. The design must enforce hard caps (max 20 pending outgoing, max 20 pending incoming) and aggressively prune expired entries on every read. This is manageable but requires discipline that fire-and-forget `say` never needed.

**Request-response pairs require loading TWO entity aspect records for every operation.** When Agent A sends `request player-B-uuid follow me`, the StructuredMessaging aspect must: load Agent A's aspect data (1 read), write the request to Agent A's outgoing list (1 write), load Agent B's entity (1 read), load Agent B's StructuredMessaging aspect (1 read), write the request to Agent B's incoming list (1 write), and push a WebSocket event to Agent B. That is 3 reads and 2 writes per request -- compared to `whisper` which costs 1 entity read and 0 writes (Communication is stateless). Over a population of 50 agents each sending 10 requests per hour, that is 1500 reads and 1000 writes per hour just for request creation, before any responses. On a 1 WCU / 1 RCU table, 1000 writes per hour is 0.28 writes per second average, which fits comfortably. Burst scenarios (10 agents all requesting simultaneously) would queue for ~20 seconds at 1 WCU.

**Race condition: two agents send `request` to each other simultaneously.** Agent A requests Agent B to follow. Agent B, in the same instant, requests Agent A to follow. Both Lambda invocations load each other's aspect data, see no pending requests, and both write their requests. Both agents now have an incoming request from the other to do the same thing. This is not data corruption -- both requests are valid -- but it is logically contradictory. The agents need conflict resolution logic: "if I have an outgoing follow request and receive an incoming follow request from the same agent, auto-accept theirs and cancel mine." This dedup logic belongs in the aspect code, not in the agent's decision layer, because the race condition is invisible to both agents at decision time.

**Contract storage is the most expensive feature and the least likely to be used.** A `contract` command stores a full JSON terms object on both parties' aspect records. If contracts include item lists, location coordinates, time bounds, and conditions, a single contract could be 1-2KB. An agent with 10 active contracts stores 10-20KB of contract data in their aspect record. The `put_item` write replaces the entire record every time any field changes, so modifying one contract field rewrites all contract data. Contracts also require a state machine (proposed, accepted, fulfilled, breached, expired) with transition rules. All of this complexity exists to enable structured agreements between agents -- but in practice, most agent coordination will use the lighter-weight `request/respond` pattern. Contracts are the enterprise feature of a system whose users need Slack. Worth including for completeness, but it should not drive the data model.

**Signal delivery is fire-and-forget with no confirmation, creating a false sense of reliability.** The `signal` command sends a lightweight message (just a signal type, no payload) to a target entity. The sender receives a `signal_sent` confirmation, but this only confirms the signal was dispatched, not received. If the target entity has no `connection_id` (disconnected), the signal is silently dropped -- `push_event` returns without error when there is no connection. The sender has no way to know the signal was lost. For real-time coordination signals like `ready`, `go`, and `wait`, a lost signal means one agent thinks coordination is happening while the other is oblivious. The architecture has no delivery confirmation mechanism (that would require a response from the target, making signals no longer lightweight). This is an inherent limitation of the WebSocket push model.

**Poll aggregation requires loading all voter aspect records or maintaining a centralized counter.** The `poll` command broadcasts a question with options to all entities at the location. Each entity votes by calling `vote`. If votes are stored on the voter's aspect record, tallying requires loading every voter's record -- O(N) reads. If votes are stored on the poll creator's record, concurrent votes create a write contention problem (multiple Lambdas trying to append to the same votes list). The design uses the creator-centric model with a votes dict, accepting that concurrent votes may overwrite each other. With the 30-second NPC tick and human reaction times, simultaneous votes are unlikely but not impossible. The worst case is a lost vote, not data corruption.

**The entire system depends on UUID discovery, which is currently broken.** The `look` command returns entity UUIDs at a location but no names, no types, no capabilities. To send a structured request to another agent, you need their UUID. To get their UUID, you `look`, receive a list of opaque UUIDs, then must `examine` each one to figure out who they are. This is O(N) entity reads just to find a conversation partner. The Agent Profile system (doc 19) would solve this by making `look` return names and profile summaries, but that system does not exist yet. Until it does, structured messaging requires agents to maintain their own UUID-to-name mapping by examining every entity they encounter. This is a hard dependency that the design cannot solve internally -- it must be acknowledged as a prerequisite.

**Topic-based announce filtering pushes complexity to the client.** The `announce` command broadcasts a structured message with a topic tag (e.g., `announce trade "Selling iron ore, 10 units"`). All entities at the location receive the event. There is no server-side topic filtering -- every entity gets every announcement, regardless of whether they care about the topic. Filtering happens on the receiving agent's side. This is correct for the architecture (broadcast is O(N) reads regardless of topic, adding topic filtering would not reduce reads) but means agents receive noise. In a busy settlement with 20 agents all announcing on different topics, each agent receives 19 announcements per round and must filter locally. The alternative -- maintaining per-entity topic subscriptions -- adds persistent state and subscription management complexity for marginal benefit. Fire-and-forget broadcast with client-side filtering is the right trade-off at this scale.

**Expiry via Call.after() adds Step Functions cost per request.** Each request with a timeout spawns a `Call.after(seconds=60)` to auto-expire it. At $0.000025 per state transition, 50 agents sending 10 requests per hour creates 500 Step Functions executions per hour, costing $0.0125/hour or $9/month. This is not catastrophic but is pure overhead -- the majority of requests will be responded to before the timeout fires, meaning the delayed call fires, loads the aspect, finds the request already resolved, and exits. That is 1 read + potentially 1 write (if it needs to clean up) for a no-op. An alternative is passive expiry: check timestamps on access and prune expired requests when the aspect data is loaded for any reason. This eliminates Step Functions cost entirely but means expired requests sit in the data until the next interaction. Passive expiry is cheaper and sufficient -- agents that care about timeouts can implement their own timers.

**Overall assessment.** Structured messaging is architecturally sound and fills a genuine gap. The cost profile is acceptable: 3 reads + 2 writes per request (vs 1 read for whisper) is a reasonable premium for tracked, typed communication. The major risks are state growth on aspect records (mitigated by hard caps and passive expiry), the UUID discovery dependency (a real blocker that must be solved by Agent Profile or an enhanced `look`), and the temptation to over-engineer contracts when request/respond handles 90% of use cases. The system should be implemented in layers: signals and requests first (highest value, lowest cost), then announce and poll (medium value, low cost), then contracts last (lowest immediate value, highest complexity). This is the right capstone for the collaboration theme -- it provides the communication substrate that parties, projects, and profiles all need.

## Overview

The StructuredMessaging aspect adds a typed, machine-parseable communication layer alongside the existing free-text Communication aspect. It provides five message primitives: `request` (ask another entity to do something), `respond` (accept, decline, or counter a request), `announce` (broadcast a topic-tagged message to the room), `signal` (send a lightweight coordination signal to a specific entity), and `poll` (create a vote for nearby entities). Additionally, `contract` proposes binding structured agreements between two entities. All messages are JSON-structured events with explicit types, parameters, and tracking IDs, enabling AI agents to coordinate programmatically without natural language parsing. Requests are tracked with status (pending, accepted, declined, expired, countered) and subject to configurable caps and passive expiry.

## Design Principles

**Structured does not replace natural.** The `say`, `whisper`, and `emote` commands remain for flavor, narrative, and role-play communication. Structured messaging handles coordination, negotiation, and logistics. An agent might `say "Hail, fellow adventurer!"` for flavor and simultaneously send `request player-uuid party-invite` for business. The two systems serve different purposes and coexist without conflict.

**Messages are typed, tracked, and finite.** Every structured message has an explicit type, a unique ID, and a lifecycle. Requests transition from `pending` to `accepted`, `declined`, `countered`, or `expired`. Contracts transition from `proposed` to `accepted`, `fulfilled`, `breached`, or `expired`. Nothing lives forever -- passive expiry cleans up stale state on access. Hard caps prevent accumulation.

**Lightweight by default, heavyweight by choice.** Signals cost 1 read, 0 writes. Announcements cost O(N) reads (same as `say`), 0 writes. Requests cost 3 reads, 2 writes. Contracts cost 3 reads, 2 writes plus ongoing state. Agents choose the weight class appropriate to the interaction. Most coordination uses signals and requests; contracts are reserved for complex multi-step agreements.

**Each aspect owns its data.** StructuredMessaging stores request/contract state on the participating entities' aspect records. It does not modify Communication, NPC, or any other aspect's data. Cross-aspect reads (loading the target entity to push events) follow the standard pattern established by `whisper`.

**Passive expiry over active timers.** Expired requests and contracts are cleaned up when the aspect data is loaded, not via scheduled Step Functions calls. This eliminates per-message Step Functions overhead and simplifies the lifecycle. An agent that never interacts with the system again accumulates dead state, but the hard cap ensures this state never exceeds a bounded size.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| outgoing_requests | list | [] | Requests sent by this entity (max 20) |
| incoming_requests | list | [] | Requests received by this entity (max 20) |
| contracts | list | [] | Active contracts (proposed, accepted) (max 10) |
| completed_contracts | list | [] | Recently completed/expired contracts (max 10, FIFO) |
| poll_data | dict | {} | Active poll created by this entity (max 1 at a time) |
| announce_topics | list | [] | Topic filter preferences (unused server-side, stored for agent reference) |
| message_seq | int | 0 | Monotonically increasing sequence number for dedup |

### Request Object Structure

```python
{
    "request_id": "req-uuid-1234",       # Unique ID for tracking
    "from_uuid": "agent-a-uuid",         # Sender entity UUID
    "from_name": "Pathfinder-7",         # Sender display name (cached)
    "to_uuid": "agent-b-uuid",           # Target entity UUID
    "to_name": "Builder-3",              # Target display name (cached)
    "action": "follow",                  # Action being requested
    "params": {                          # Action-specific parameters
        "destination": "5,3,0",
        "reason": "cave-exploration"
    },
    "status": "pending",                 # pending | accepted | declined | countered | expired
    "created_at": 1700000000,            # Unix timestamp
    "expires_at": 1700000060,            # Unix timestamp (created_at + ttl)
    "response_params": {},               # Params from counter-offer (if countered)
    "seq": 42                            # Sequence number for ordering/dedup
}
```

### Contract Object Structure

```python
{
    "contract_id": "ctr-uuid-5678",      # Unique ID
    "party_a_uuid": "agent-a-uuid",      # Proposing entity
    "party_a_name": "Pathfinder-7",      # Cached name
    "party_b_uuid": "agent-b-uuid",      # Other party
    "party_b_name": "Builder-3",         # Cached name
    "contract_type": "trade",            # trade | alliance | task | escort | custom
    "terms": {                           # Contract-specific terms
        "party_a_provides": ["item-uuid-1", "item-uuid-2"],
        "party_b_provides": ["item-uuid-3"],
        "party_a_gold": 0,
        "party_b_gold": 50,
        "duration_seconds": 300,
        "conditions": ["both_parties_at_same_location"]
    },
    "status": "proposed",                # proposed | accepted | fulfilled | breached | expired
    "created_at": 1700000000,
    "accepted_at": null,
    "expires_at": 1700000300,
    "fulfillment_criteria": {            # How to determine fulfillment
        "type": "manual",                # manual | item_transfer | location_arrival
        "details": {}
    }
}
```

### Signal Types Registry

```python
SIGNAL_TYPES = {
    # Coordination signals
    "ready":    {"category": "coordination", "description": "I am ready to proceed"},
    "wait":     {"category": "coordination", "description": "Hold position, not ready yet"},
    "go":       {"category": "coordination", "description": "Proceed now"},
    "done":     {"category": "coordination", "description": "Task complete"},
    "regroup":  {"category": "coordination", "description": "Return to group"},

    # Alerts
    "danger":   {"category": "alert", "description": "Threat detected nearby"},
    "help":     {"category": "alert", "description": "Requesting immediate assistance"},
    "clear":    {"category": "alert", "description": "Area is safe"},
    "retreat":  {"category": "alert", "description": "Fall back from current position"},

    # Status
    "low_hp":   {"category": "status", "description": "Health is critically low"},
    "low_supply": {"category": "status", "description": "Running low on supplies"},
    "full":     {"category": "status", "description": "Inventory is full"},
    "lost":     {"category": "status", "description": "Cannot find the way"},

    # Social
    "agree":    {"category": "social", "description": "I agree with the current proposal"},
    "disagree": {"category": "social", "description": "I disagree with the current proposal"},
    "thanks":   {"category": "social", "description": "Expressing gratitude"},
    "greet":    {"category": "social", "description": "Friendly greeting"},
}
```

### Request Action Types Registry

```python
REQUEST_ACTIONS = {
    # Movement
    "follow":       {"description": "Follow the requester", "params": ["destination"]},
    "meet_at":      {"description": "Meet at a specific location", "params": ["location_coords"]},
    "scout":        {"description": "Scout a location and report back", "params": ["location_coords"]},
    "escort":       {"description": "Escort requester to destination", "params": ["destination"]},

    # Party/Group
    "party_invite": {"description": "Join the requester's party", "params": []},
    "party_leave":  {"description": "Leave the current party", "params": []},

    # Resource/Trade
    "trade":        {"description": "Initiate a trade", "params": ["offered_items", "wanted_items"]},
    "give_item":    {"description": "Give a specific item", "params": ["item_uuid"]},
    "share_info":   {"description": "Share information about a topic", "params": ["topic"]},

    # Task
    "help_with":    {"description": "Help with a specific task", "params": ["task_type", "details"]},
    "craft_item":   {"description": "Craft a specific item", "params": ["item_name", "materials"]},
    "gather":       {"description": "Gather a specific resource", "params": ["resource_type", "quantity"]},

    # Combat
    "attack_target":{"description": "Attack a specific target together", "params": ["target_uuid"]},
    "defend_area":  {"description": "Defend the current area", "params": ["duration_seconds"]},
    "heal":         {"description": "Provide healing", "params": []},

    # Custom (free-form)
    "custom":       {"description": "Custom request with free-form params", "params": ["description"]},
}
```

### Configuration Constants

```python
# Hard caps
MAX_OUTGOING_REQUESTS = 20
MAX_INCOMING_REQUESTS = 20
MAX_ACTIVE_CONTRACTS = 10
MAX_COMPLETED_CONTRACTS = 10
MAX_POLL_OPTIONS = 8

# Timing
DEFAULT_REQUEST_TTL = 60          # seconds
MAX_REQUEST_TTL = 300             # seconds (5 minutes)
DEFAULT_CONTRACT_TTL = 3600       # seconds (1 hour)
MAX_CONTRACT_TTL = 86400          # seconds (24 hours)
POLL_DURATION = 120               # seconds (2 minutes)

# Dedup
REQUEST_DEDUP_WINDOW = 5          # seconds -- reject duplicate action+target within this window
```

## Commands

### `request <target_uuid> <action> [params...]`

```python
@player_command
def request(self, target_uuid: str, action: str, **params) -> dict:
    """Send a structured request to another entity."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| target_uuid | str | Yes | UUID of the entity to send the request to |
| action | str | Yes | Action type from REQUEST_ACTIONS registry |
| params | dict | No | Action-specific parameters |
| ttl | int | No | Time-to-live in seconds (default 60, max 300) |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "request_sent" |
| request_id | str | Unique ID for tracking this request |
| target_uuid | str | Target entity UUID |
| target_name | str | Target entity display name |
| action | str | The requested action |
| expires_at | int | Unix timestamp when request auto-expires |
| message | str | Human-readable confirmation |

**Behaviour:**

1. Validate `action` is in `REQUEST_ACTIONS` registry (or is "custom")
2. Prune expired requests from `outgoing_requests` (passive expiry)
3. Check `len(outgoing_requests) < MAX_OUTGOING_REQUESTS` after pruning
4. Dedup check: reject if identical `action` + `target_uuid` request exists within `REQUEST_DEDUP_WINDOW`
5. Load target entity (1 read) -- validate exists
6. Load target StructuredMessaging aspect (1 read) -- prune expired, check incoming cap
7. Generate `request_id` (UUID)
8. Create request object, append to self `outgoing_requests` and target `incoming_requests`
9. Save self aspect (1 write), save target aspect (1 write)
10. Push `request_received` event to target via WebSocket

```python
@player_command
def request(self, target_uuid: str, action: str, **params) -> dict:
    """Send a structured request to another entity."""
    if not target_uuid:
        return {"type": "error", "message": "Request to whom?"}

    if action not in REQUEST_ACTIONS and action != "custom":
        valid = ", ".join(sorted(REQUEST_ACTIONS.keys()))
        return {"type": "error", "message": f"Unknown action '{action}'. Valid: {valid}"}

    if target_uuid == self.entity.uuid:
        return {"type": "error", "message": "You can't send a request to yourself."}

    # Passive expiry: prune expired outgoing requests
    import time
    now = int(time.time())
    self.data["outgoing_requests"] = [
        r for r in self.data.get("outgoing_requests", [])
        if r.get("expires_at", 0) > now or r.get("status") not in ("pending", None)
    ]

    # Check outgoing cap
    pending_out = [r for r in self.data.get("outgoing_requests", [])
                   if r.get("status") == "pending"]
    if len(pending_out) >= MAX_OUTGOING_REQUESTS:
        return {"type": "error",
                "message": f"Too many pending requests ({MAX_OUTGOING_REQUESTS} max). "
                           "Wait for responses or let them expire."}

    # Dedup check
    for r in pending_out:
        if (r.get("action") == action
                and r.get("to_uuid") == target_uuid
                and now - r.get("created_at", 0) < REQUEST_DEDUP_WINDOW):
            return {"type": "error",
                    "message": f"Duplicate request. You already sent '{action}' "
                               f"to that entity {now - r['created_at']}s ago."}

    # Load target
    try:
        target_entity = Entity(uuid=target_uuid)
    except KeyError:
        return {"type": "error", "message": "That entity doesn't exist."}

    # Load target's StructuredMessaging aspect
    try:
        target_sm = target_entity.aspect("StructuredMessaging")
    except (ValueError, KeyError):
        return {"type": "error", "message": "That entity cannot receive structured messages."}

    # Prune target's expired incoming
    target_sm.data["incoming_requests"] = [
        r for r in target_sm.data.get("incoming_requests", [])
        if r.get("expires_at", 0) > now or r.get("status") not in ("pending", None)
    ]

    # Check target incoming cap
    target_pending = [r for r in target_sm.data.get("incoming_requests", [])
                      if r.get("status") == "pending"]
    if len(target_pending) >= MAX_INCOMING_REQUESTS:
        return {"type": "error",
                "message": "That entity has too many pending requests. Try again later."}

    # Build request
    ttl = min(params.pop("ttl", DEFAULT_REQUEST_TTL), MAX_REQUEST_TTL)
    self.data["message_seq"] = self.data.get("message_seq", 0) + 1
    seq = self.data["message_seq"]

    from uuid import uuid4
    request_id = f"req-{uuid4()}"

    request_obj = {
        "request_id": request_id,
        "from_uuid": self.entity.uuid,
        "from_name": self.entity.name,
        "to_uuid": target_uuid,
        "to_name": target_entity.name,
        "action": action,
        "params": params,
        "status": "pending",
        "created_at": now,
        "expires_at": now + ttl,
        "response_params": {},
        "seq": seq,
    }

    # Store on both sides
    self.data.setdefault("outgoing_requests", []).append(request_obj)
    self._save()

    target_sm.data.setdefault("incoming_requests", []).append(request_obj)
    target_sm._save()

    # Push event to target
    target_entity.push_event({
        "type": "request_received",
        "request_id": request_id,
        "from_uuid": self.entity.uuid,
        "from_name": self.entity.name,
        "action": action,
        "params": params,
        "expires_at": now + ttl,
        "message": f"{self.entity.name} requests: {action}",
    })

    return {
        "type": "request_sent",
        "request_id": request_id,
        "target_uuid": target_uuid,
        "target_name": target_entity.name,
        "action": action,
        "expires_at": now + ttl,
        "message": f"Request '{action}' sent to {target_entity.name}. "
                   f"Expires in {ttl}s.",
    }
```

**DynamoDB cost:** 1 read (self aspect, already loaded) + 1 read (target entity) + 1 read (target StructuredMessaging aspect) + 1 write (self aspect) + 1 write (target aspect) = 3 reads, 2 writes.

**Example:**

```
Player sends: {"command": "request", "data": {"target_uuid": "agent-b-uuid", "action": "follow", "destination": "5,3,0"}}

Response:
{
    "type": "request_sent",
    "request_id": "req-abc123",
    "target_uuid": "agent-b-uuid",
    "target_name": "Builder-3",
    "action": "follow",
    "expires_at": 1700000060,
    "message": "Request 'follow' sent to Builder-3. Expires in 60s."
}

Agent B receives WebSocket event:
{
    "type": "request_received",
    "request_id": "req-abc123",
    "from_uuid": "agent-a-uuid",
    "from_name": "Pathfinder-7",
    "action": "follow",
    "params": {"destination": "5,3,0"},
    "expires_at": 1700000060,
    "message": "Pathfinder-7 requests: follow"
}
```

---

### `respond <request_id> <decision> [params...]`

```python
@player_command
def respond(self, request_id: str, decision: str, **params) -> dict:
    """Respond to a pending request."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| request_id | str | Yes | ID of the request to respond to |
| decision | str | Yes | One of: "accept", "decline", "counter" |
| params | dict | No | Counter-offer parameters (required if decision is "counter") |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "response_sent" |
| request_id | str | The request being responded to |
| decision | str | The decision made |
| original_action | str | The action that was requested |
| from_name | str | Name of the entity that sent the original request |
| message | str | Human-readable confirmation |

**Behaviour:**

1. Find request in `incoming_requests` by `request_id`
2. Validate request exists and status is "pending"
3. Check request has not expired (compare `expires_at` with current time)
4. Validate decision is one of "accept", "decline", "counter"
5. If "counter": validate that counter params are provided
6. Update request status in `incoming_requests`
7. Load originator entity and their StructuredMessaging aspect
8. Update request status in originator's `outgoing_requests`
9. Save both aspects
10. Push `request_response` event to originator

```python
@player_command
def respond(self, request_id: str, decision: str, **params) -> dict:
    """Respond to a pending request (accept, decline, or counter)."""
    if decision not in ("accept", "decline", "counter"):
        return {"type": "error",
                "message": "Decision must be 'accept', 'decline', or 'counter'."}

    if not request_id:
        return {"type": "error", "message": "Which request? Provide a request_id."}

    import time
    now = int(time.time())

    # Find the request in incoming
    incoming = self.data.get("incoming_requests", [])
    request_obj = None
    request_idx = None
    for idx, r in enumerate(incoming):
        if r.get("request_id") == request_id:
            request_obj = r
            request_idx = idx
            break

    if request_obj is None:
        return {"type": "error", "message": f"No request found with ID '{request_id}'."}

    if request_obj.get("status") != "pending":
        return {"type": "error",
                "message": f"Request already {request_obj.get('status', 'resolved')}."}

    if request_obj.get("expires_at", 0) <= now:
        request_obj["status"] = "expired"
        self._save()
        return {"type": "error", "message": "That request has expired."}

    if decision == "counter" and not params:
        return {"type": "error",
                "message": "Counter-offer requires parameters. "
                           "Provide modified terms."}

    # Update local copy
    new_status = decision if decision != "counter" else "countered"
    request_obj["status"] = new_status
    if decision == "counter":
        request_obj["response_params"] = params
    incoming[request_idx] = request_obj
    self.data["incoming_requests"] = incoming
    self._save()

    # Update originator's outgoing copy
    originator_uuid = request_obj.get("from_uuid", "")
    originator_name = request_obj.get("from_name", "someone")
    try:
        originator_entity = Entity(uuid=originator_uuid)
        originator_sm = originator_entity.aspect("StructuredMessaging")
        outgoing = originator_sm.data.get("outgoing_requests", [])
        for idx, r in enumerate(outgoing):
            if r.get("request_id") == request_id:
                r["status"] = new_status
                if decision == "counter":
                    r["response_params"] = params
                outgoing[idx] = r
                break
        originator_sm.data["outgoing_requests"] = outgoing
        originator_sm._save()

        # Notify originator
        event_data = {
            "type": "request_response",
            "request_id": request_id,
            "from_uuid": self.entity.uuid,
            "from_name": self.entity.name,
            "decision": decision,
            "original_action": request_obj.get("action", ""),
            "message": f"{self.entity.name} {decision}ed your '{request_obj.get('action', '')}' request.",
        }
        if decision == "counter":
            event_data["counter_params"] = params
            event_data["message"] = (
                f"{self.entity.name} countered your '{request_obj.get('action', '')}' request "
                f"with modified terms."
            )
        originator_entity.push_event(event_data)
    except (KeyError, ValueError):
        pass  # Originator gone -- response still recorded locally

    return {
        "type": "response_sent",
        "request_id": request_id,
        "decision": decision,
        "original_action": request_obj.get("action", ""),
        "from_name": originator_name,
        "message": f"You {decision}ed the '{request_obj.get('action', '')}' "
                   f"request from {originator_name}.",
    }
```

**DynamoDB cost:** 1 read (self aspect, already loaded) + 1 read (originator entity) + 1 read (originator StructuredMessaging aspect) + 1 write (self aspect) + 1 write (originator aspect) = 3 reads, 2 writes.

**Example:**

```
Player sends: {"command": "respond", "data": {"request_id": "req-abc123", "decision": "accept"}}

Response:
{
    "type": "response_sent",
    "request_id": "req-abc123",
    "decision": "accept",
    "original_action": "follow",
    "from_name": "Pathfinder-7",
    "message": "You accepted the 'follow' request from Pathfinder-7."
}

Pathfinder-7 receives WebSocket event:
{
    "type": "request_response",
    "request_id": "req-abc123",
    "from_uuid": "agent-b-uuid",
    "from_name": "Builder-3",
    "decision": "accept",
    "original_action": "follow",
    "message": "Builder-3 accepted your 'follow' request."
}
```

**Counter-offer example:**

```
Player sends: {"command": "respond", "data": {"request_id": "req-abc123", "decision": "counter", "destination": "3,3,0", "reason": "closer location"}}

Builder-3 response:
{
    "type": "response_sent",
    "request_id": "req-abc123",
    "decision": "counter",
    "original_action": "follow",
    "from_name": "Pathfinder-7",
    "message": "You countered the 'follow' request from Pathfinder-7."
}

Pathfinder-7 receives:
{
    "type": "request_response",
    "request_id": "req-abc123",
    "from_uuid": "agent-b-uuid",
    "from_name": "Builder-3",
    "decision": "counter",
    "original_action": "follow",
    "counter_params": {"destination": "3,3,0", "reason": "closer location"},
    "message": "Builder-3 countered your 'follow' request with modified terms."
}
```

---

### `announce <topic> <message>`

```python
@player_command
def announce(self, topic: str, message: str) -> dict:
    """Broadcast a structured announcement with a topic tag."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| topic | str | Yes | Topic tag (e.g., "trade", "combat", "exploration", "social", "help") |
| message | str | Yes | The announcement content |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "announce_confirm" |
| topic | str | The topic tag used |
| message | str | Human-readable confirmation |
| recipients | int | Number of entities that received the announcement |

**Behaviour:**

1. Validate topic is non-empty
2. Validate message is non-empty
3. Get entity location
4. Broadcast `announcement` event to all entities at location (same as `say` pattern)
5. Return confirmation with recipient count

```python
VALID_TOPICS = [
    "trade", "combat", "exploration", "social", "help",
    "resource", "quest", "party", "warning", "info",
]

@player_command
def announce(self, topic: str, message: str) -> dict:
    """Broadcast a structured announcement with a topic tag to the room."""
    if not topic:
        return {"type": "error", "message": "Announce about what topic?"}
    if not message:
        return {"type": "error", "message": "Announce what?"}

    topic = topic.lower().strip()
    if topic not in VALID_TOPICS:
        return {"type": "error",
                "message": f"Unknown topic '{topic}'. Valid: {', '.join(VALID_TOPICS)}"}

    location_uuid = self.entity.location
    if not location_uuid:
        return {"type": "error", "message": "You are nowhere."}

    event = {
        "type": "announcement",
        "topic": topic,
        "speaker_uuid": self.entity.uuid,
        "speaker_name": self.entity.name,
        "message": message,
    }

    # Broadcast to all entities at this location (except self)
    # Uses same O(N) read pattern as Communication.say()
    self.entity.broadcast_to_location(location_uuid, event)

    # Count recipients (approximate -- same as broadcast)
    try:
        loc_entity = Entity(uuid=location_uuid)
        recipient_count = max(0, len(loc_entity.contents) - 1)
    except KeyError:
        recipient_count = 0

    return {
        "type": "announce_confirm",
        "topic": topic,
        "message": f"Announced [{topic}]: {message}",
        "recipients": recipient_count,
    }
```

**DynamoDB cost:** Same as `say`: 1 read (location entity) + O(N) reads (each entity at location) + 0 writes = O(N) reads, 0 writes. The extra `loc_entity.contents` call for recipient count reuses the data already loaded by `broadcast_to_location` in practice, but as implemented adds 1 GSI query.

**Example:**

```
Player sends: {"command": "announce", "data": {"topic": "trade", "message": "Selling 10 iron ore, 5 gold each"}}

Response:
{
    "type": "announce_confirm",
    "topic": "trade",
    "message": "Announced [trade]: Selling 10 iron ore, 5 gold each",
    "recipients": 4
}

All entities at location receive:
{
    "type": "announcement",
    "topic": "trade",
    "speaker_uuid": "agent-a-uuid",
    "speaker_name": "Miner-12",
    "message": "Selling 10 iron ore, 5 gold each"
}
```

---

### `signal <target_uuid> <signal_type>`

```python
@player_command
def signal(self, target_uuid: str, signal_type: str) -> dict:
    """Send a lightweight signal to another entity."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| target_uuid | str | Yes | UUID of the entity to signal |
| signal_type | str | Yes | Signal type from SIGNAL_TYPES registry |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "signal_sent" |
| target_uuid | str | Target entity UUID |
| target_name | str | Target display name |
| signal_type | str | The signal type sent |
| message | str | Human-readable confirmation |

**Behaviour:**

1. Validate `signal_type` is in `SIGNAL_TYPES` registry
2. Load target entity (1 read)
3. Push `signal` event to target via WebSocket
4. Return confirmation (no persistent state written)

```python
@player_command
def signal(self, target_uuid: str, signal_type: str) -> dict:
    """Send a lightweight coordination signal to another entity."""
    if not target_uuid:
        return {"type": "error", "message": "Signal whom?"}
    if not signal_type:
        return {"type": "error", "message": "What signal?"}

    signal_type = signal_type.lower().strip()
    if signal_type not in SIGNAL_TYPES:
        valid = ", ".join(sorted(SIGNAL_TYPES.keys()))
        return {"type": "error",
                "message": f"Unknown signal '{signal_type}'. Valid: {valid}"}

    if target_uuid == self.entity.uuid:
        return {"type": "error", "message": "You can't signal yourself."}

    try:
        target_entity = Entity(uuid=target_uuid)
    except KeyError:
        return {"type": "error", "message": "That entity doesn't exist."}

    signal_def = SIGNAL_TYPES[signal_type]
    target_entity.push_event({
        "type": "signal",
        "signal_type": signal_type,
        "category": signal_def["category"],
        "from_uuid": self.entity.uuid,
        "from_name": self.entity.name,
        "description": signal_def["description"],
        "message": f"{self.entity.name} signals: {signal_type}",
    })

    return {
        "type": "signal_sent",
        "target_uuid": target_uuid,
        "target_name": target_entity.name,
        "signal_type": signal_type,
        "message": f"Sent '{signal_type}' signal to {target_entity.name}.",
    }
```

**DynamoDB cost:** 1 read (target entity) + 0 writes = 1 read, 0 writes. This is the cheapest operation in the system.

**Example:**

```
Player sends: {"command": "signal", "data": {"target_uuid": "agent-b-uuid", "signal_type": "ready"}}

Response:
{
    "type": "signal_sent",
    "target_uuid": "agent-b-uuid",
    "target_name": "Builder-3",
    "signal_type": "ready",
    "message": "Sent 'ready' signal to Builder-3."
}

Builder-3 receives:
{
    "type": "signal",
    "signal_type": "ready",
    "category": "coordination",
    "from_uuid": "agent-a-uuid",
    "from_name": "Pathfinder-7",
    "description": "I am ready to proceed",
    "message": "Pathfinder-7 signals: ready"
}
```

---

### `poll <question> <options...>`

```python
@player_command
def poll(self, question: str, *options) -> dict:
    """Create a poll for nearby entities to vote on."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| question | str | Yes | The poll question |
| options | list[str] | Yes | 2-8 options to vote on |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "poll_created" |
| poll_id | str | Unique poll ID |
| question | str | The question asked |
| options | list[str] | The options available |
| expires_at | int | When voting closes |
| message | str | Human-readable confirmation |

**Behaviour:**

1. Validate question and options (2-8 options required)
2. Check entity does not already have an active poll
3. Generate poll_id
4. Store poll_data on creator's aspect record
5. Broadcast `poll` event to all entities at location
6. Return confirmation

```python
@player_command
def poll(self, question: str, *options) -> dict:
    """Create a poll for nearby entities to vote on."""
    if not question:
        return {"type": "error", "message": "Poll about what?"}

    # Handle options passed as individual args or as a list
    if len(options) == 1 and isinstance(options[0], (list, tuple)):
        options = list(options[0])
    else:
        options = list(options)

    if len(options) < 2:
        return {"type": "error", "message": "Need at least 2 options."}
    if len(options) > MAX_POLL_OPTIONS:
        return {"type": "error",
                "message": f"Too many options (max {MAX_POLL_OPTIONS})."}

    # Check for existing active poll
    import time
    now = int(time.time())
    existing_poll = self.data.get("poll_data", {})
    if existing_poll and existing_poll.get("expires_at", 0) > now:
        return {"type": "error",
                "message": "You already have an active poll. Wait for it to expire."}

    from uuid import uuid4
    poll_id = f"poll-{uuid4()}"

    location_uuid = self.entity.location
    if not location_uuid:
        return {"type": "error", "message": "You are nowhere."}

    poll_obj = {
        "poll_id": poll_id,
        "creator_uuid": self.entity.uuid,
        "creator_name": self.entity.name,
        "question": question,
        "options": options,
        "votes": {},  # voter_uuid -> option_index
        "created_at": now,
        "expires_at": now + POLL_DURATION,
        "location_uuid": location_uuid,
    }

    self.data["poll_data"] = poll_obj
    self._save()

    # Broadcast to location
    self.entity.broadcast_to_location(location_uuid, {
        "type": "poll",
        "poll_id": poll_id,
        "creator_uuid": self.entity.uuid,
        "creator_name": self.entity.name,
        "question": question,
        "options": [{"index": i, "text": opt} for i, opt in enumerate(options)],
        "expires_at": now + POLL_DURATION,
        "message": f"{self.entity.name} asks: {question}",
    })

    return {
        "type": "poll_created",
        "poll_id": poll_id,
        "question": question,
        "options": options,
        "expires_at": now + POLL_DURATION,
        "message": f"Poll created: '{question}' (expires in {POLL_DURATION}s). "
                   f"Options: {', '.join(options)}",
    }
```

**DynamoDB cost:** 1 write (self aspect) + O(N) reads (broadcast to location) = O(N) reads, 1 write.

**Example:**

```
Player sends: {"command": "poll", "data": {"question": "Which cave should we explore?", "options": ["Northern Cave", "Eastern Mines", "Southern Ruins"]}}

Response:
{
    "type": "poll_created",
    "poll_id": "poll-xyz789",
    "question": "Which cave should we explore?",
    "options": ["Northern Cave", "Eastern Mines", "Southern Ruins"],
    "expires_at": 1700000120,
    "message": "Poll created: 'Which cave should we explore?' (expires in 120s). Options: Northern Cave, Eastern Mines, Southern Ruins"
}
```

---

### `vote <poll_id> <option_index>`

```python
@player_command
def vote(self, poll_id: str, option_index: int) -> dict:
    """Vote on an active poll."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| poll_id | str | Yes | ID of the poll to vote on |
| option_index | int | Yes | Zero-based index of the chosen option |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "vote_confirm" |
| poll_id | str | The poll voted on |
| choice | str | Text of the chosen option |
| message | str | Human-readable confirmation |

**Behaviour:**

1. Parse poll_id to extract creator UUID (poll_id encodes creator context from the broadcast event)
2. Search for the poll: check if any entity at the location has the matching poll_data
3. Since we cannot efficiently find the poll creator from just a poll_id, the poll broadcast event includes `creator_uuid`; the agent must store this and pass the creator_uuid alongside poll_id. **Alternative approach used here:** scan entities at location for matching poll_data. This is O(N) reads but N is bounded by room occupancy.
4. **Simplified approach:** require the poll creator to be at the same location. Load each entity at location, check their StructuredMessaging aspect for matching poll_data.
5. **Even simpler (chosen approach):** the vote command takes poll_id, and we brute-force search by loading entities at our location. For efficiency, we could store the creator_uuid in the poll_id format or require it as a parameter. Below we require `creator_uuid` as well.

Revised signature:

```python
@player_command
def vote(self, creator_uuid: str, option_index: int) -> dict:
    """Vote on an active poll created by the specified entity."""
    if not creator_uuid:
        return {"type": "error", "message": "Vote on whose poll? Provide creator UUID."}

    import time
    now = int(time.time())

    try:
        option_index = int(option_index)
    except (TypeError, ValueError):
        return {"type": "error", "message": "Option must be a number (0-based index)."}

    # Load creator's poll
    try:
        creator_entity = Entity(uuid=creator_uuid)
    except KeyError:
        return {"type": "error", "message": "Poll creator not found."}

    try:
        creator_sm = creator_entity.aspect("StructuredMessaging")
    except (ValueError, KeyError):
        return {"type": "error", "message": "No poll found."}

    poll = creator_sm.data.get("poll_data", {})
    if not poll:
        return {"type": "error", "message": "That entity has no active poll."}

    if poll.get("expires_at", 0) <= now:
        return {"type": "error", "message": "That poll has expired."}

    options = poll.get("options", [])
    if option_index < 0 or option_index >= len(options):
        return {"type": "error",
                "message": f"Invalid option. Choose 0-{len(options) - 1}."}

    # Check voter is at same location as poll
    if poll.get("location_uuid") != self.entity.location:
        return {"type": "error", "message": "You must be at the poll location to vote."}

    # Record vote (overwrites previous vote by this entity)
    poll["votes"][self.entity.uuid] = option_index
    creator_sm.data["poll_data"] = poll
    creator_sm._save()

    choice_text = options[option_index]

    # Notify poll creator
    creator_entity.push_event({
        "type": "vote_cast",
        "voter_uuid": self.entity.uuid,
        "voter_name": self.entity.name,
        "option_index": option_index,
        "choice": choice_text,
        "total_votes": len(poll["votes"]),
        "message": f"{self.entity.name} voted for '{choice_text}'.",
    })

    return {
        "type": "vote_confirm",
        "poll_id": poll.get("poll_id", ""),
        "choice": choice_text,
        "message": f"You voted for '{choice_text}'.",
    }
```

**DynamoDB cost:** 1 read (creator entity) + 1 read (creator StructuredMessaging aspect) + 1 write (creator aspect with updated votes) = 2 reads, 1 write.

---

### `poll_results <creator_uuid>`

```python
@player_command
def poll_results(self, creator_uuid: str) -> dict:
    """View the results of a poll."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| creator_uuid | str | Yes | UUID of the poll creator |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "poll_results" |
| question | str | The poll question |
| results | list[dict] | Options with vote counts |
| total_votes | int | Total votes cast |
| expired | bool | Whether voting has closed |
| message | str | Human-readable summary |

**Behaviour:**

```python
@player_command
def poll_results(self, creator_uuid: str) -> dict:
    """View the current results of a poll."""
    if not creator_uuid:
        return {"type": "error", "message": "Whose poll? Provide creator UUID."}

    import time
    now = int(time.time())

    try:
        creator_entity = Entity(uuid=creator_uuid)
        creator_sm = creator_entity.aspect("StructuredMessaging")
    except (KeyError, ValueError):
        return {"type": "error", "message": "Poll not found."}

    poll = creator_sm.data.get("poll_data", {})
    if not poll:
        return {"type": "error", "message": "That entity has no poll."}

    options = poll.get("options", [])
    votes = poll.get("votes", {})
    expired = poll.get("expires_at", 0) <= now

    # Tally
    tally = [0] * len(options)
    for voter_uuid, opt_idx in votes.items():
        if 0 <= opt_idx < len(options):
            tally[opt_idx] += 1

    results = [
        {"index": i, "text": options[i], "votes": tally[i]}
        for i in range(len(options))
    ]
    results.sort(key=lambda r: r["votes"], reverse=True)

    total = sum(tally)
    winner = results[0] if results else None
    summary = f"'{poll.get('question', '')}' - {total} votes."
    if expired and winner:
        summary += f" Winner: {winner['text']} ({winner['votes']} votes)."

    return {
        "type": "poll_results",
        "poll_id": poll.get("poll_id", ""),
        "question": poll.get("question", ""),
        "results": results,
        "total_votes": total,
        "expired": expired,
        "message": summary,
    }
```

**DynamoDB cost:** 1 read (creator entity) + 1 read (creator StructuredMessaging aspect) = 2 reads, 0 writes.

---

### `contract <target_uuid> <contract_type> <terms_json>`

```python
@player_command
def contract(self, target_uuid: str, contract_type: str, **terms) -> dict:
    """Propose a structured contract to another entity."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| target_uuid | str | Yes | UUID of the other party |
| contract_type | str | Yes | One of: "trade", "alliance", "task", "escort", "custom" |
| terms | dict | Yes | Contract terms (varies by type) |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "contract_proposed" |
| contract_id | str | Unique contract ID |
| target_uuid | str | Other party UUID |
| target_name | str | Other party display name |
| contract_type | str | The contract type |
| message | str | Human-readable confirmation |

**Behaviour:**

1. Validate contract_type
2. Prune expired contracts from `contracts` list
3. Check `len(contracts) < MAX_ACTIVE_CONTRACTS`
4. Load target entity and StructuredMessaging aspect
5. Prune target's expired contracts, check their cap
6. Generate contract_id
7. Create contract object on both parties
8. Save both aspects
9. Push `contract_proposed` event to target

```python
VALID_CONTRACT_TYPES = ["trade", "alliance", "task", "escort", "custom"]

@player_command
def contract(self, target_uuid: str, contract_type: str, **terms) -> dict:
    """Propose a structured contract to another entity."""
    if not target_uuid:
        return {"type": "error", "message": "Contract with whom?"}

    if contract_type not in VALID_CONTRACT_TYPES:
        return {"type": "error",
                "message": f"Unknown contract type '{contract_type}'. "
                           f"Valid: {', '.join(VALID_CONTRACT_TYPES)}"}

    if target_uuid == self.entity.uuid:
        return {"type": "error", "message": "You can't contract with yourself."}

    if not terms:
        return {"type": "error", "message": "Contract requires terms."}

    import time
    now = int(time.time())

    # Prune expired contracts
    self.data["contracts"] = [
        c for c in self.data.get("contracts", [])
        if c.get("status") in ("proposed", "accepted")
        and c.get("expires_at", 0) > now
    ]

    if len(self.data.get("contracts", [])) >= MAX_ACTIVE_CONTRACTS:
        return {"type": "error",
                "message": f"Too many active contracts ({MAX_ACTIVE_CONTRACTS} max)."}

    # Load target
    try:
        target_entity = Entity(uuid=target_uuid)
    except KeyError:
        return {"type": "error", "message": "That entity doesn't exist."}

    try:
        target_sm = target_entity.aspect("StructuredMessaging")
    except (ValueError, KeyError):
        return {"type": "error",
                "message": "That entity cannot receive contracts."}

    # Prune target contracts
    target_sm.data["contracts"] = [
        c for c in target_sm.data.get("contracts", [])
        if c.get("status") in ("proposed", "accepted")
        and c.get("expires_at", 0) > now
    ]

    if len(target_sm.data.get("contracts", [])) >= MAX_ACTIVE_CONTRACTS:
        return {"type": "error",
                "message": "That entity has too many active contracts."}

    # Build contract
    from uuid import uuid4
    contract_id = f"ctr-{uuid4()}"
    ttl = min(terms.pop("ttl", DEFAULT_CONTRACT_TTL), MAX_CONTRACT_TTL)

    contract_obj = {
        "contract_id": contract_id,
        "party_a_uuid": self.entity.uuid,
        "party_a_name": self.entity.name,
        "party_b_uuid": target_uuid,
        "party_b_name": target_entity.name,
        "contract_type": contract_type,
        "terms": terms,
        "status": "proposed",
        "created_at": now,
        "accepted_at": None,
        "expires_at": now + ttl,
        "fulfillment_criteria": {
            "type": "manual",
            "details": {},
        },
    }

    # Store on both parties
    self.data.setdefault("contracts", []).append(contract_obj)
    self._save()

    target_sm.data.setdefault("contracts", []).append(contract_obj)
    target_sm._save()

    # Notify target
    target_entity.push_event({
        "type": "contract_proposed",
        "contract_id": contract_id,
        "from_uuid": self.entity.uuid,
        "from_name": self.entity.name,
        "contract_type": contract_type,
        "terms": terms,
        "expires_at": now + ttl,
        "message": f"{self.entity.name} proposes a {contract_type} contract.",
    })

    return {
        "type": "contract_proposed",
        "contract_id": contract_id,
        "target_uuid": target_uuid,
        "target_name": target_entity.name,
        "contract_type": contract_type,
        "message": f"{contract_type.capitalize()} contract proposed to "
                   f"{target_entity.name}. Expires in {ttl}s.",
    }
```

**DynamoDB cost:** 1 read (target entity) + 1 read (target StructuredMessaging) + 1 write (self aspect) + 1 write (target aspect) = 2 reads, 2 writes.

**Example:**

```
Player sends:
{
    "command": "contract",
    "data": {
        "target_uuid": "agent-b-uuid",
        "contract_type": "trade",
        "party_a_provides": ["iron-ore-uuid-1", "iron-ore-uuid-2"],
        "party_b_provides": ["healing-herb-uuid"],
        "party_b_gold": 50,
        "ttl": 600
    }
}

Response:
{
    "type": "contract_proposed",
    "contract_id": "ctr-def456",
    "target_uuid": "agent-b-uuid",
    "target_name": "Builder-3",
    "contract_type": "trade",
    "message": "Trade contract proposed to Builder-3. Expires in 600s."
}
```

---

### `accept_contract <contract_id>`

```python
@player_command
def accept_contract(self, contract_id: str) -> dict:
    """Accept a proposed contract."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| contract_id | str | Yes | ID of the contract to accept |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "contract_accepted" |
| contract_id | str | The accepted contract ID |
| contract_type | str | The type of contract |
| other_party | str | Name of the other party |
| message | str | Human-readable confirmation |

**Behaviour:**

```python
@player_command
def accept_contract(self, contract_id: str) -> dict:
    """Accept a proposed contract."""
    if not contract_id:
        return {"type": "error", "message": "Which contract?"}

    import time
    now = int(time.time())

    # Find contract in our list
    contracts = self.data.get("contracts", [])
    contract_obj = None
    contract_idx = None
    for idx, c in enumerate(contracts):
        if c.get("contract_id") == contract_id:
            contract_obj = c
            contract_idx = idx
            break

    if contract_obj is None:
        return {"type": "error", "message": f"No contract found with ID '{contract_id}'."}

    if contract_obj.get("status") != "proposed":
        return {"type": "error",
                "message": f"Contract already {contract_obj.get('status', 'resolved')}."}

    if contract_obj.get("expires_at", 0) <= now:
        contract_obj["status"] = "expired"
        self._save()
        return {"type": "error", "message": "That contract has expired."}

    # Only party_b can accept (party_a proposed it)
    if contract_obj.get("party_a_uuid") == self.entity.uuid:
        return {"type": "error",
                "message": "You proposed this contract. Wait for the other party to accept."}

    # Update status
    contract_obj["status"] = "accepted"
    contract_obj["accepted_at"] = now
    contracts[contract_idx] = contract_obj
    self.data["contracts"] = contracts
    self._save()

    # Update other party's copy
    other_uuid = contract_obj.get("party_a_uuid", "")
    other_name = contract_obj.get("party_a_name", "someone")
    try:
        other_entity = Entity(uuid=other_uuid)
        other_sm = other_entity.aspect("StructuredMessaging")
        for idx, c in enumerate(other_sm.data.get("contracts", [])):
            if c.get("contract_id") == contract_id:
                c["status"] = "accepted"
                c["accepted_at"] = now
                other_sm.data["contracts"][idx] = c
                break
        other_sm._save()

        other_entity.push_event({
            "type": "contract_accepted",
            "contract_id": contract_id,
            "from_uuid": self.entity.uuid,
            "from_name": self.entity.name,
            "contract_type": contract_obj.get("contract_type", ""),
            "message": f"{self.entity.name} accepted your "
                       f"{contract_obj.get('contract_type', '')} contract.",
        })
    except (KeyError, ValueError):
        pass

    return {
        "type": "contract_accepted",
        "contract_id": contract_id,
        "contract_type": contract_obj.get("contract_type", ""),
        "other_party": other_name,
        "message": f"You accepted the {contract_obj.get('contract_type', '')} "
                   f"contract with {other_name}.",
    }
```

**DynamoDB cost:** 1 read (other entity) + 1 read (other StructuredMessaging) + 1 write (self aspect) + 1 write (other aspect) = 2 reads, 2 writes.

---

### `fulfill_contract <contract_id>`

```python
@player_command
def fulfill_contract(self, contract_id: str) -> dict:
    """Mark a contract as fulfilled (both parties must call this)."""
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| contract_id | str | Yes | ID of the contract to fulfill |

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "contract_fulfilled" or "contract_fulfillment_pending" |
| contract_id | str | The contract ID |
| message | str | Human-readable confirmation |

**Behaviour:**

Fulfillment uses a two-phase approach. Each party calls `fulfill_contract`. The first call marks their side as ready. When both parties have called it, the contract transitions to "fulfilled" and moves to `completed_contracts`.

```python
@player_command
def fulfill_contract(self, contract_id: str) -> dict:
    """Mark your side of a contract as fulfilled."""
    if not contract_id:
        return {"type": "error", "message": "Which contract?"}

    import time
    now = int(time.time())

    contracts = self.data.get("contracts", [])
    contract_obj = None
    contract_idx = None
    for idx, c in enumerate(contracts):
        if c.get("contract_id") == contract_id:
            contract_obj = c
            contract_idx = idx
            break

    if contract_obj is None:
        return {"type": "error", "message": f"No contract found with ID '{contract_id}'."}

    if contract_obj.get("status") != "accepted":
        return {"type": "error",
                "message": f"Contract must be accepted before fulfillment. "
                           f"Current status: {contract_obj.get('status', 'unknown')}."}

    if contract_obj.get("expires_at", 0) <= now:
        contract_obj["status"] = "expired"
        self._save()
        return {"type": "error", "message": "That contract has expired."}

    # Determine which party we are
    my_uuid = self.entity.uuid
    if my_uuid == contract_obj.get("party_a_uuid"):
        my_key = "party_a_fulfilled"
        other_key = "party_b_fulfilled"
        other_uuid = contract_obj.get("party_b_uuid")
        other_name = contract_obj.get("party_b_name")
    elif my_uuid == contract_obj.get("party_b_uuid"):
        my_key = "party_b_fulfilled"
        other_key = "party_a_fulfilled"
        other_uuid = contract_obj.get("party_a_uuid")
        other_name = contract_obj.get("party_a_name")
    else:
        return {"type": "error", "message": "You are not a party to this contract."}

    contract_obj[my_key] = True

    if contract_obj.get(other_key):
        # Both parties fulfilled -- complete the contract
        contract_obj["status"] = "fulfilled"
        contracts.pop(contract_idx)
        completed = self.data.get("completed_contracts", [])
        completed.append(contract_obj)
        # FIFO cap on completed
        if len(completed) > MAX_COMPLETED_CONTRACTS:
            completed = completed[-MAX_COMPLETED_CONTRACTS:]
        self.data["completed_contracts"] = completed
        self.data["contracts"] = contracts
        self._save()

        # Update other party
        try:
            other_entity = Entity(uuid=other_uuid)
            other_sm = other_entity.aspect("StructuredMessaging")
            other_contracts = other_sm.data.get("contracts", [])
            for idx, c in enumerate(other_contracts):
                if c.get("contract_id") == contract_id:
                    other_contracts.pop(idx)
                    other_completed = other_sm.data.get("completed_contracts", [])
                    c["status"] = "fulfilled"
                    other_completed.append(c)
                    if len(other_completed) > MAX_COMPLETED_CONTRACTS:
                        other_completed = other_completed[-MAX_COMPLETED_CONTRACTS:]
                    other_sm.data["completed_contracts"] = other_completed
                    other_sm.data["contracts"] = other_contracts
                    break
            other_sm._save()

            other_entity.push_event({
                "type": "contract_fulfilled",
                "contract_id": contract_id,
                "message": f"Contract with {self.entity.name} has been fulfilled by both parties.",
            })
        except (KeyError, ValueError):
            pass

        return {
            "type": "contract_fulfilled",
            "contract_id": contract_id,
            "message": f"Contract with {other_name} is now fulfilled.",
        }
    else:
        # Only one side fulfilled -- waiting for the other
        contracts[contract_idx] = contract_obj
        self.data["contracts"] = contracts
        self._save()

        # Notify other party
        try:
            other_entity = Entity(uuid=other_uuid)
            other_sm = other_entity.aspect("StructuredMessaging")
            for idx, c in enumerate(other_sm.data.get("contracts", [])):
                if c.get("contract_id") == contract_id:
                    c[my_key] = True
                    other_sm.data["contracts"][idx] = c
                    break
            other_sm._save()

            other_entity.push_event({
                "type": "contract_fulfillment_pending",
                "contract_id": contract_id,
                "from_name": self.entity.name,
                "message": f"{self.entity.name} has marked their side of the contract as fulfilled. "
                           f"Use 'fulfill_contract {contract_id}' to complete.",
            })
        except (KeyError, ValueError):
            pass

        return {
            "type": "contract_fulfillment_pending",
            "contract_id": contract_id,
            "message": f"Your side is fulfilled. Waiting for {other_name} to fulfill.",
        }
```

**DynamoDB cost:** 1 read (other entity) + 1 read (other StructuredMessaging) + 1 write (self) + 1 write (other) = 2 reads, 2 writes.

---

### `requests`

```python
@player_command
def requests(self) -> dict:
    """List all pending incoming and outgoing requests."""
```

**Parameters:** None

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "requests_list" |
| incoming | list[dict] | Pending incoming requests (summary) |
| outgoing | list[dict] | Pending outgoing requests (summary) |
| message | str | Human-readable summary |

**Behaviour:**

```python
@player_command
def requests(self) -> dict:
    """List all pending requests (incoming and outgoing)."""
    import time
    now = int(time.time())

    # Prune expired
    self.data["incoming_requests"] = [
        r for r in self.data.get("incoming_requests", [])
        if r.get("expires_at", 0) > now and r.get("status") == "pending"
    ]
    self.data["outgoing_requests"] = [
        r for r in self.data.get("outgoing_requests", [])
        if r.get("expires_at", 0) > now and r.get("status") == "pending"
    ]
    self._save()

    incoming = [
        {
            "request_id": r["request_id"],
            "from_name": r.get("from_name", "unknown"),
            "action": r.get("action", ""),
            "expires_in": r.get("expires_at", 0) - now,
        }
        for r in self.data.get("incoming_requests", [])
    ]

    outgoing = [
        {
            "request_id": r["request_id"],
            "to_name": r.get("to_name", "unknown"),
            "action": r.get("action", ""),
            "status": r.get("status", "pending"),
            "expires_in": r.get("expires_at", 0) - now,
        }
        for r in self.data.get("outgoing_requests", [])
    ]

    return {
        "type": "requests_list",
        "incoming": incoming,
        "outgoing": outgoing,
        "message": f"{len(incoming)} incoming, {len(outgoing)} outgoing requests.",
    }
```

**DynamoDB cost:** 0 reads (self aspect already loaded), 1 write (pruning expired entries) = 0 reads, 1 write. If nothing was pruned, save can be skipped.

---

### `contracts_list`

```python
@player_command
def contracts_list(self) -> dict:
    """List all active and recently completed contracts."""
```

**Parameters:** None

**Returns:**

| Field | Type | Description |
|-------|------|-------------|
| type | str | "contracts_list" |
| active | list[dict] | Active contracts (proposed or accepted) |
| completed | list[dict] | Recently completed contracts |
| message | str | Human-readable summary |

**Behaviour:**

```python
@player_command
def contracts_list(self) -> dict:
    """List all active and recently completed contracts."""
    import time
    now = int(time.time())

    # Prune expired
    active = []
    for c in self.data.get("contracts", []):
        if c.get("expires_at", 0) <= now and c.get("status") in ("proposed", "accepted"):
            c["status"] = "expired"
            completed = self.data.get("completed_contracts", [])
            completed.append(c)
            if len(completed) > MAX_COMPLETED_CONTRACTS:
                completed = completed[-MAX_COMPLETED_CONTRACTS:]
            self.data["completed_contracts"] = completed
        else:
            active.append(c)
    self.data["contracts"] = active
    self._save()

    active_summary = [
        {
            "contract_id": c["contract_id"],
            "contract_type": c.get("contract_type", ""),
            "other_party": (c.get("party_b_name") if c.get("party_a_uuid") == self.entity.uuid
                           else c.get("party_a_name", "unknown")),
            "status": c.get("status", ""),
            "expires_in": c.get("expires_at", 0) - now,
        }
        for c in active
    ]

    completed_summary = [
        {
            "contract_id": c["contract_id"],
            "contract_type": c.get("contract_type", ""),
            "status": c.get("status", ""),
        }
        for c in self.data.get("completed_contracts", [])
    ]

    return {
        "type": "contracts_list",
        "active": active_summary,
        "completed": completed_summary,
        "message": f"{len(active_summary)} active, "
                   f"{len(completed_summary)} recently completed contracts.",
    }
```

**DynamoDB cost:** 0 reads, 1 write (pruning/save).

## Callable Methods

Internal methods callable via SNS dispatch using `@callable` decorator.

### `_prune_expired`

Not callable externally (underscore prefix blocked by `Entity._action()`). This is an internal helper called at the start of any command that reads request or contract data.

```python
def _prune_expired(self):
    """Remove expired pending requests and contracts. Called internally."""
    import time
    now = int(time.time())

    self.data["outgoing_requests"] = [
        r for r in self.data.get("outgoing_requests", [])
        if not (r.get("status") == "pending" and r.get("expires_at", 0) <= now)
    ]
    self.data["incoming_requests"] = [
        r for r in self.data.get("incoming_requests", [])
        if not (r.get("status") == "pending" and r.get("expires_at", 0) <= now)
    ]

    active_contracts = []
    for c in self.data.get("contracts", []):
        if c.get("expires_at", 0) <= now and c.get("status") in ("proposed", "accepted"):
            c["status"] = "expired"
            completed = self.data.get("completed_contracts", [])
            completed.append(c)
            if len(completed) > MAX_COMPLETED_CONTRACTS:
                self.data["completed_contracts"] = completed[-MAX_COMPLETED_CONTRACTS:]
        else:
            active_contracts.append(c)
    self.data["contracts"] = active_contracts
```

### `receive_request` (callable)

```python
@callable
def receive_request(self, request_data: dict) -> dict:
    """Receive a request via SNS from another aspect/entity.

    This allows non-player entities (NPCs, systems) to send structured
    requests to agents. Uses the same validation as the player command
    but bypasses WebSocket authentication.
    """
    import time
    now = int(time.time())

    self._prune_expired()

    pending = [r for r in self.data.get("incoming_requests", [])
               if r.get("status") == "pending"]
    if len(pending) >= MAX_INCOMING_REQUESTS:
        return {"type": "error", "message": "Incoming request queue full."}

    self.data.setdefault("incoming_requests", []).append(request_data)
    self._save()

    if self.entity:
        self.entity.push_event({
            "type": "request_received",
            "request_id": request_data.get("request_id", ""),
            "from_uuid": request_data.get("from_uuid", ""),
            "from_name": request_data.get("from_name", ""),
            "action": request_data.get("action", ""),
            "params": request_data.get("params", {}),
            "message": f"{request_data.get('from_name', 'Someone')} requests: "
                       f"{request_data.get('action', 'something')}",
        })

    return {"type": "request_queued", "request_id": request_data.get("request_id", "")}
```

### `receive_signal` (callable)

```python
@callable
def receive_signal(self, signal_data: dict) -> dict:
    """Receive a signal via SNS from another entity.

    Allows system entities to signal agents (e.g., world events,
    NPC coordination signals).
    """
    if self.entity:
        self.entity.push_event({
            "type": "signal",
            "signal_type": signal_data.get("signal_type", ""),
            "category": signal_data.get("category", ""),
            "from_uuid": signal_data.get("from_uuid", ""),
            "from_name": signal_data.get("from_name", ""),
            "description": signal_data.get("description", ""),
            "message": f"{signal_data.get('from_name', 'Someone')} signals: "
                       f"{signal_data.get('signal_type', '')}",
        })
    return {"type": "signal_delivered"}
```

## Events

Events pushed to players via WebSocket (`push_event`).

### `request_received`

Pushed when another entity sends a structured request.

```python
{
    "type": "request_received",
    "request_id": "req-abc123",
    "from_uuid": "agent-a-uuid",
    "from_name": "Pathfinder-7",
    "action": "follow",
    "params": {"destination": "5,3,0"},
    "expires_at": 1700000060,
    "message": "Pathfinder-7 requests: follow"
}
```

### `request_response`

Pushed when a request you sent receives a response.

```python
{
    "type": "request_response",
    "request_id": "req-abc123",
    "from_uuid": "agent-b-uuid",
    "from_name": "Builder-3",
    "decision": "accept",           # or "decline" or "counter"
    "original_action": "follow",
    "counter_params": {},            # populated only on "counter"
    "message": "Builder-3 accepted your 'follow' request."
}
```

### `signal`

Pushed when another entity sends a coordination signal.

```python
{
    "type": "signal",
    "signal_type": "ready",
    "category": "coordination",
    "from_uuid": "agent-a-uuid",
    "from_name": "Pathfinder-7",
    "description": "I am ready to proceed",
    "message": "Pathfinder-7 signals: ready"
}
```

### `announcement`

Pushed when another entity broadcasts a topic-tagged announcement.

```python
{
    "type": "announcement",
    "topic": "trade",
    "speaker_uuid": "agent-a-uuid",
    "speaker_name": "Miner-12",
    "message": "Selling 10 iron ore, 5 gold each"
}
```

### `poll`

Pushed when someone creates a poll at your location.

```python
{
    "type": "poll",
    "poll_id": "poll-xyz789",
    "creator_uuid": "agent-a-uuid",
    "creator_name": "Pathfinder-7",
    "question": "Which cave should we explore?",
    "options": [
        {"index": 0, "text": "Northern Cave"},
        {"index": 1, "text": "Eastern Mines"},
        {"index": 2, "text": "Southern Ruins"}
    ],
    "expires_at": 1700000120,
    "message": "Pathfinder-7 asks: Which cave should we explore?"
}
```

### `vote_cast`

Pushed to the poll creator when someone votes.

```python
{
    "type": "vote_cast",
    "voter_uuid": "agent-b-uuid",
    "voter_name": "Builder-3",
    "option_index": 1,
    "choice": "Eastern Mines",
    "total_votes": 3,
    "message": "Builder-3 voted for 'Eastern Mines'."
}
```

### `contract_proposed`

Pushed when another entity proposes a contract.

```python
{
    "type": "contract_proposed",
    "contract_id": "ctr-def456",
    "from_uuid": "agent-a-uuid",
    "from_name": "Pathfinder-7",
    "contract_type": "trade",
    "terms": {
        "party_a_provides": ["iron-ore-uuid-1"],
        "party_b_provides": ["healing-herb-uuid"],
        "party_b_gold": 50
    },
    "expires_at": 1700000600,
    "message": "Pathfinder-7 proposes a trade contract."
}
```

### `contract_accepted`

Pushed when the other party accepts your contract.

```python
{
    "type": "contract_accepted",
    "contract_id": "ctr-def456",
    "from_uuid": "agent-b-uuid",
    "from_name": "Builder-3",
    "contract_type": "trade",
    "message": "Builder-3 accepted your trade contract."
}
```

### `contract_fulfilled`

Pushed when both parties have fulfilled a contract.

```python
{
    "type": "contract_fulfilled",
    "contract_id": "ctr-def456",
    "message": "Contract with Builder-3 has been fulfilled by both parties."
}
```

### `contract_fulfillment_pending`

Pushed when the other party marks their side as fulfilled but you have not yet.

```python
{
    "type": "contract_fulfillment_pending",
    "contract_id": "ctr-def456",
    "from_name": "Pathfinder-7",
    "message": "Pathfinder-7 has marked their side of the contract as fulfilled. Use 'fulfill_contract ctr-def456' to complete."
}
```

## Integration Points

### StructuredMessaging + Communication

Communication remains the free-text channel. StructuredMessaging is the typed channel. They coexist on the same entity without interaction. An agent might use `say` for role-play dialogue while using `request` for actual coordination. The two aspects share no data and do not call each other.

```python
# Agent workflow: discovery -> structured negotiation
# 1. Agent enters room, sees entities via 'look'
# 2. Agent uses 'say "Hello, anyone interested in exploring?"' (flavor)
# 3. Agent uses 'announce exploration "LFG cave exploration, need healer"' (structured)
# 4. Interested agent responds with 'request agent-a-uuid party_invite' (structured)
# 5. Agents exchange signals during exploration: 'signal agent-b-uuid ready'
```

### StructuredMessaging + Trading (doc 13)

The `request` action type `"trade"` initiates negotiation before using Trading commands. An agent sends `request agent-b-uuid trade offered_items=["sword-uuid"] wanted_items=["shield-uuid"]` to propose terms. On acceptance, both agents proceed to the Trading aspect's `trade`, `offer`, and `accept` commands to execute the actual item transfer. StructuredMessaging negotiates terms; Trading executes them.

```python
# Contract-backed trade flow:
# 1. Agent A: contract agent-b-uuid trade party_a_provides=["sword-uuid"] party_b_gold=100
# 2. Agent B: accept_contract ctr-xyz
# 3. Agent A: trade agent-b-uuid (Trading aspect)
# 4. Agent A: offer sword-uuid (Trading aspect)
# 5. Agent B: accept (Trading aspect)
# 6. Both: fulfill_contract ctr-xyz (StructuredMessaging)
```

### StructuredMessaging + Party System (doc 17)

The `party_invite` request action is the structured way to invite agents to a party. Instead of a free-text whisper ("want to join my party?"), an agent sends a typed request. The Party aspect handles actual group management; StructuredMessaging handles the invitation negotiation.

```python
# Party formation flow:
# 1. Agent A: announce party "Forming party for dungeon run, need tank and healer"
# 2. Agent B: request agent-a-uuid party_invite
# 3. Agent A: respond req-id accept
# 4. Agent A: party_add agent-b-uuid (Party aspect)
```

### StructuredMessaging + Project System (doc 18)

Contracts with type `"task"` define project work assignments. An agent leading a project proposes task contracts to workers, specifying deliverables and compensation. Workers accept, perform the task, and both parties fulfill when complete. The Project aspect tracks overall project state; StructuredMessaging handles individual task agreements.

```python
# Project task assignment:
# 1. Project leader: contract worker-uuid task task_type="gather" resource="iron_ore" quantity=20 reward_gold=100
# 2. Worker: accept_contract ctr-xyz
# 3. Worker gathers 20 iron ore using game commands
# 4. Worker: fulfill_contract ctr-xyz
# 5. Leader verifies, pays, fulfills: fulfill_contract ctr-xyz
```

### StructuredMessaging + Agent Profile (doc 19)

Agent profiles expose capabilities and preferences. Before sending a request, an agent can `inspect` another agent's profile to check if they have the skills needed. This prevents wasted requests ("request healer-uuid craft_item" when the healer cannot craft). Profiles are read-only context; StructuredMessaging is the action layer.

```python
# Capability-aware request:
# 1. Agent A inspects Agent B's profile: skills include "mining", "smelting"
# 2. Agent A: request agent-b-uuid craft_item item_name="iron_ingot" materials=["iron_ore"]
# 3. Agent B checks own capabilities, accepts if able
```

### StructuredMessaging + NPC (existing)

NPCs can send signals and requests to agents via the `@callable` methods `receive_request` and `receive_signal`. A guard NPC can signal `danger` to nearby players when hostiles appear. A quest-giving NPC can send a `request` with action `help_with` to agents at its location. This bridges the NPC behavior system into the structured messaging protocol.

```python
# NPC integration in NPC.tick():
def _guard_alert(self):
    """Alert nearby players of danger via structured signal."""
    if self._detects_hostile():
        for player_uuid in self._nearby_players():
            Call(
                tid=str(uuid4()),
                originator=self.entity.uuid,
                uuid=player_uuid,
                aspect="StructuredMessaging",
                action="receive_signal",
                signal_data={
                    "signal_type": "danger",
                    "category": "alert",
                    "from_uuid": self.entity.uuid,
                    "from_name": self.entity.name,
                    "description": "Threat detected nearby",
                },
            ).now()
```

### StructuredMessaging + Combat (doc 01)

The `attack_target` request action coordinates group combat. An agent identifies a target and sends a structured request to allies to focus fire. The `signal` types `danger`, `retreat`, `help`, and `low_hp` provide real-time combat status updates without the overhead of natural language.

```python
# Coordinated combat:
# 1. Scout: signal party-leader-uuid danger
# 2. Leader: request tank-uuid attack_target target_uuid="boss-uuid"
# 3. Leader: request healer-uuid heal
# 4. Tank: respond req-1 accept
# 5. Healer: respond req-2 accept
# 6. [Combat proceeds via Combat aspect]
# 7. Tank: signal leader-uuid low_hp
# 8. Healer: signal tank-uuid ready (healing ready)
```

## Error Handling

### Error Conditions and Responses

| Condition | Command | Response |
|-----------|---------|----------|
| Target entity does not exist | request, signal, contract | `{"type": "error", "message": "That entity doesn't exist."}` |
| Target has no StructuredMessaging aspect | request, contract | `{"type": "error", "message": "That entity cannot receive structured messages."}` |
| Unknown action type | request | `{"type": "error", "message": "Unknown action '...'. Valid: ..."}` |
| Unknown signal type | signal | `{"type": "error", "message": "Unknown signal '...'. Valid: ..."}` |
| Unknown topic | announce | `{"type": "error", "message": "Unknown topic '...'. Valid: ..."}` |
| Outgoing request cap reached | request | `{"type": "error", "message": "Too many pending requests (20 max)."}` |
| Incoming request cap reached (target) | request | `{"type": "error", "message": "That entity has too many pending requests."}` |
| Duplicate request within dedup window | request | `{"type": "error", "message": "Duplicate request. You already sent '...' to that entity Ns ago."}` |
| Request not found | respond | `{"type": "error", "message": "No request found with ID '...'."}` |
| Request already resolved | respond | `{"type": "error", "message": "Request already accepted/declined."}` |
| Request expired | respond | `{"type": "error", "message": "That request has expired."}` |
| Counter without params | respond | `{"type": "error", "message": "Counter-offer requires parameters."}` |
| Active contract cap reached | contract | `{"type": "error", "message": "Too many active contracts (10 max)."}` |
| Contract not found | accept_contract, fulfill_contract | `{"type": "error", "message": "No contract found with ID '...'."}` |
| Contract already resolved | accept_contract | `{"type": "error", "message": "Contract already accepted/expired."}` |
| Trying to accept own contract | accept_contract | `{"type": "error", "message": "You proposed this contract. Wait for the other party."}` |
| Contract not yet accepted | fulfill_contract | `{"type": "error", "message": "Contract must be accepted before fulfillment."}` |
| Self-targeting | request, signal, contract | `{"type": "error", "message": "You can't ... yourself."}` |
| Not at poll location | vote | `{"type": "error", "message": "You must be at the poll location to vote."}` |
| Poll expired | vote | `{"type": "error", "message": "That poll has expired."}` |
| Invalid poll option | vote | `{"type": "error", "message": "Invalid option. Choose 0-N."}` |
| Already have active poll | poll | `{"type": "error", "message": "You already have an active poll."}` |
| Too few/many poll options | poll | `{"type": "error", "message": "Need at least 2 options."/"Too many options."}` |
| No location (nowhere) | announce, poll | `{"type": "error", "message": "You are nowhere."}` |

### Edge Cases

**Target disconnects between request and response.** The request persists in both aspect records. If the target reconnects and loads their aspect, the pending request is still there. If it has expired by then, passive pruning removes it. No data loss, just delayed or expired communication.

**Originator disconnects after sending request.** The response attempts to load the originator's entity and aspect. If the originator's entity still exists (disconnected but not destroyed), the response updates their outgoing_requests. The push_event silently fails (no connection_id). When the originator reconnects, they can check `requests` to see the response.

**Both parties call fulfill_contract simultaneously.** Two Lambda invocations each read the contract, each set their own fulfillment flag, each check the other's flag (not set yet in their read), and each save. Result: both writes succeed, but neither sees the other's fulfillment flag. The contract remains in "accepted" with one flag set (whichever Lambda wrote last wins). The second party must call fulfill_contract again. This is a race condition but not data corruption -- eventual consistency is achieved by retry.

**Entity destroyed with pending requests/contracts.** No cleanup mechanism exists. The other party's copies of the requests/contracts reference a nonexistent entity. When they try to respond, the Entity load fails and they receive "That entity doesn't exist." The requests eventually expire and are pruned. Contracts may linger until expiry. This is acceptable -- entity destruction is rare and the dead references are harmless.

## Cost Analysis

### Per-Operation DynamoDB Costs

| Operation | Reads | Writes | Step Functions | Notes |
|-----------|-------|--------|---------------|-------|
| request | 3 | 2 | 0 | Target entity + aspect + self save + target save |
| respond | 3 | 2 | 0 | Originator entity + aspect + both saves |
| signal | 1 | 0 | 0 | Target entity only, no state |
| announce | O(N) | 0 | 0 | Same cost as say, N = entities at location |
| poll | O(N) | 1 | 0 | Broadcast + creator save |
| vote | 2 | 1 | 0 | Creator entity + aspect + creator save |
| poll_results | 2 | 0 | 0 | Creator entity + aspect (read only) |
| contract | 2 | 2 | 0 | Target entity + aspect + both saves |
| accept_contract | 2 | 2 | 0 | Other party entity + aspect + both saves |
| fulfill_contract | 2 | 2 | 0 | Other party entity + aspect + both saves |
| requests | 0 | 1 | 0 | Self only, pruning save |
| contracts_list | 0 | 1 | 0 | Self only, pruning save |

### Monthly Projections

**Scenario: 50 AI agents, moderately active**

Assumptions per agent per hour:
- 10 requests sent
- 10 responses sent
- 20 signals sent
- 5 announcements
- 1 poll (with 5 votes)
- 2 contracts (with accept + fulfill each)

Per agent per hour:
- Requests: 10 * (3R + 2W) = 30R + 20W
- Responses: 10 * (3R + 2W) = 30R + 20W
- Signals: 20 * (1R + 0W) = 20R + 0W
- Announcements: 5 * (5R + 0W) = 25R + 0W (assuming ~5 entities per room)
- Polls: 1 * (5R + 1W) = 5R + 1W
- Votes (received): 5 * (2R + 1W) = 10R + 5W
- Contracts: 2 * (2R + 2W) = 4R + 4W
- Accept: 2 * (2R + 2W) = 4R + 4W
- Fulfill (2 calls per contract): 4 * (2R + 2W) = 8R + 8W
- List commands: 5 * (0R + 1W) = 0R + 5W

**Per agent per hour:** 136 reads + 67 writes
**50 agents per hour:** 6,800 reads + 3,350 writes
**Per second:** 1.89 reads/s + 0.93 writes/s

At 1 RCU / 1 WCU provisioned, the reads are nearly 2x capacity and writes are just under 1x. DynamoDB burst capacity (up to 300 seconds of accumulated throughput) handles spikes, but sustained load at this level would require increasing to 2 RCU. At on-demand pricing: reads cost $0.25 per million, writes cost $1.25 per million.

**Monthly DynamoDB cost (50 agents, 18 hours/day active):**
- Reads: 6,800 * 18 * 30 = 3,672,000 reads/month = $0.92
- Writes: 3,350 * 18 * 30 = 1,809,000 writes/month = $2.26
- **Total: ~$3.18/month DynamoDB**

**Step Functions cost: $0.** Passive expiry eliminates all delayed call overhead. No ticks, no scheduled calls.

**Comparison to Communication aspect:**
- `say` with 5 entities at location: 5 reads, 0 writes
- 50 agents saying 20 messages/hour: 5,000 reads/hour, 0 writes
- StructuredMessaging adds ~36% more reads and a significant write component

**At scale (200 agents):**
- 27,200 reads/s and 13,400 writes/s per hour
- 7.56 reads/s, 3.72 writes/s sustained
- Would require 4 RCU and 4 WCU provisioned, or on-demand
- Monthly: ~$12.72 DynamoDB -- still negligible

### Cost Comparison with Active Expiry (rejected alternative)

If requests used `Call.after()` for active expiry instead of passive:
- 50 agents * 10 requests/hour = 500 Step Functions executions/hour
- Each execution: $0.000025
- Per hour: $0.0125
- Per month (18h/day): $6.75
- Plus each expiry call does 1 read + 1 write (to load aspect and prune)
- Additional 500 reads + 500 writes per hour

**Passive expiry saves $6.75/month and 9,000 reads + 9,000 writes per month** compared to active expiry. The trade-off is that expired requests persist until the next aspect load, which is cosmetically imperfect but functionally harmless.

## Future Considerations

1. **Broadcast signals.** Currently signals are point-to-point. A `signal_all <signal_type>` command could broadcast a signal to all entities at the current location (e.g., a party leader signaling "go" to the whole group). Cost: O(N) entity reads, same as `say`. Implementation: iterate `loc_entity.contents` and push signal event to each.

2. **Message history / inbox.** Currently, if an agent is disconnected when a signal or announcement is sent, it is lost. An inbox system could store the last N messages for retrieval on reconnect. Cost: adds persistent state (message log per entity) and write overhead per message. Deferred because it changes the fire-and-forget model and most agents are continuously connected.

3. **Automated contract fulfillment.** Currently fulfillment is manual (both parties call `fulfill_contract`). Automated fulfillment could watch for specific conditions: "contract fulfilled when item-uuid-1 is in party_b's inventory." This requires a fulfillment watcher -- either a tick-based check (expensive) or event-driven triggers (complex). Deferred until the contract system proves valuable enough to justify the complexity.

4. **Request forwarding / delegation.** An agent receiving a request they cannot fulfill might want to forward it to someone else. A `forward <request_id> <new_target_uuid>` command would transfer the request to a new target. This adds 1 more read/write pair and updates the request's target on both the originator's and new target's records.

5. **Structured message encryption / privacy.** Currently all structured messages are visible to any entity that can load the relevant aspect data. In a system with hostile agents, request and contract terms could be intercepted by loading another entity's StructuredMessaging aspect. Encryption would require key exchange -- significant complexity for a game. Deferred unless PvP espionage becomes a design goal.

6. **Topic subscriptions for announcements.** Server-side topic filtering would let agents register interest in specific topics and only receive matching announcements. Saves WebSocket bandwidth but adds subscription state management. At current scale (rooms with <20 entities), client-side filtering is adequate.

7. **Request templates.** Predefined request templates for common coordination patterns (trade negotiation, party formation, dungeon run) could reduce the parameter burden on agents. Templates are syntactic sugar over the existing `request` command -- no new infrastructure needed, just convenience wrappers.

8. **Multi-party contracts.** Current contracts are bilateral (two parties). Multi-party contracts (e.g., a three-way trade, a group task assignment) would require N copies of the contract and N-way fulfillment. The data model supports this by adding more party fields, but the fulfillment logic becomes combinatorial. Deferred until two-party contracts are proven.

9. **Contract breach detection.** Currently there is no breach mechanism -- contracts simply expire or are manually fulfilled. A breach detection system could monitor for violations (e.g., an agent who accepted an escort contract but moved to a different location). This requires tick-based monitoring, which reintroduces the Step Functions cost that passive expiry was designed to avoid.

10. **Integration with reputation / faction system.** Completed contracts and accepted requests could feed into a reputation score specific to agent reliability. An agent who accepts requests but never follows through accumulates negative reputation. This creates incentives for honest behavior without requiring trust between unfamiliar agents. Depends on a per-agent reputation system that could extend the existing Faction aspect.

11. **Rate limiting.** The current caps (20 outgoing, 20 incoming) prevent accumulation but not spam. An agent could send 20 requests, wait for them to expire, and send 20 more -- cycling through 20 requests per minute. A rate limit (max N requests per M seconds to the same target) would prevent harassment. Can be implemented with a simple timestamp check in the dedup logic by extending `REQUEST_DEDUP_WINDOW`.
