# Design Context: Serverless Game

*A living document capturing principles, practices, and design intentions for this codebase.*

**What this is:** Designer's notes, graffiti wall, todo list, and architectural diary all rolled into one. Not formal documentation — formal docs get extracted from here once concepts stabilize.

**How to use it:** Write down half-formed thoughts. Sketch protocols before implementing them. Record "why we did X" when the reason isn't obvious from the code. When a section stabilizes, it graduates to formal docs like GAME_DESIGN.md or WEBSOCKET_DESIGN.md.

---

## Core Principles (Things We Believe)

### 1. Aspect-Oriented > Object-Oriented

**What we avoid:** Deep inheritance hierarchies where `Dragon extends Monster extends Creature extends Entity`. That path leads to the "diamond problem" and classes that accumulate cruft from every layer.

**What we do:** Each concern is a separate Lambda. A dragon has `Combat`, `Inventory`, and `Location` aspects. Each aspect is a function that subscribes to events about its UUID. The dragon doesn't know it's a dragon — it just responds to events.

**Why this matters:**
- Can add `Flammable` aspect to anything without touching existing code
- Can version aspects independently
- Natural fit for serverless (each aspect = one Lambda)

**Current state:** `Thing` base class exists, `@callable` decorator marks methods for SNS routing. Aspects communicate via SNS events with `tid` (transaction ID) for tracing.

**Open questions:**
- How do we handle aspect ordering when multiple aspects need to respond to the same event?
- Should aspects have dependencies (e.g., `Combat` requires `Health`)?

### 2. Entity Is The Viewport

**The principle:** You don't "observe" the world. You experience what your entity experiences. No camera object, no spectator mode.

**How it works:**
```
Player connects → JWT identifies them → Entity created/bound → Entity pushes events to connection
```

Events flow:
```json
{"event": "room_description", "data": {...}}
{"event": "combat", "actor": "goblin", "action": "attack"}
```

**Symmetry implication:** AI agents and humans use the same mechanism. Both possess entities. Both receive the same events. The game cannot distinguish between them.

**Current state:** WebSocket handlers exist (`connect_handler`, `command_handler`, `disconnect_handler`). Entity holds `connection_id`. `push_event()` sends to WebSocket if connected.

**Design tension:** We want entity autonomy when disconnected (NPC behavior), but also want clean "pause" semantics. Currently leaning toward: entity always autonomous, player just "guides" it while connected.

### 3. Connection As Pipe

**Critical clarification:** The WebSocket is NOT the entity. It's a pipe temporarily attached to an entity.

```
Entity (holds connection_id) ←→ WebSocket ←→ Player/Agent
```

**Key insight from implementation:** The entity owns the connection, not vice versa. This means:
- Entity can push events without the WebSocket layer knowing what entity it's for
- Multiple connections to same entity? Possible but not implemented
- Connection drops? Entity clears `connection_id`, keeps living

**Implementation:** `possess` command binds connection to entity UUID. `detach_connection` clears it. All routed through SNS to preserve event flow.

**Current state:** `possess`, `attach_connection`, `detach_connection` implemented. Need to test reconnection scenarios.

### 4. Event-Driven Everything

**All communication is events.** No direct method calls between aspects. No shared state. Every action is an SNS message with:
- `tid`: Transaction ID for tracing
- `aspect`: Target aspect
- `action`: Method to invoke
- `uuid`: Entity UUID
- `data`: Arguments
- `callback`: Optional continuation

**Event loop mechanics:**
1. Event arrives on SNS
2. Lambda spins up (or warm start)
3. Aspect loads entity state from DynamoDB
4. Method executes
5. State saved back to DynamoDB
6. Any callbacks scheduled

**Why events:**
- Loose coupling (aspects don't know about each other)
- Replayability (event log = world state history)
- AI-friendly (event stream is natural input for agents)

**Current state:** SNS bus working. `Call` class constructs events. `handler.py` routes to aspect methods. Step Functions handle delayed events.

**Performance note:** 32KB limit on Step Functions payload. Keep events small.

---

## Security Model (What We Enforce)

### Authentication

**Current:** JWT in `X-Api-Key` header on WebSocket connect. `sub` claim = persistent identity.

**Deferred:** OAuth, refresh tokens, revocation. JWTs are "API keys" for now — acceptable for development, not production.

**Open question:** Should we support anonymous play? Demo mode? Or always require identity?

### Authorization

**Three layers:**

1. **@player_command** — Only methods with this decorator can be called via WebSocket. Validates:
   - Caller possesses this entity (connection_id matches)
   - Entity is not a system entity
   
2. **@admin_only** — Requires admin flag. System entities can call these. Regular players cannot.

3. **@system_entity** — Class decorator. Entity cannot be possessed. Used for world infrastructure.

**Current state:** All three decorators implemented in `decorators.py`. `Thing._action()` validates actions aren't private and are in allowed set.

**Known gap:** `@admin_only` checks `is_admin` flag but doesn't cryptographically verify. Defense-in-depth: only system entities can have `is_admin=True`, and system entities can't be possessed. Good enough for now.

### Command Safety

**Action validation:**
- Actions starting with `_` are prohibited (private methods)
- Actions must be in `_get_allowed_actions()` set
- `_get_allowed_actions()` walks the MRO collecting `@callable` methods

**Why this matters:** Prevents event bus from invoking arbitrary methods. Only explicitly marked methods are reachable.

---

## WebSocket Architecture (How We Connect)

### Lifecycle

**$connect:**
1. API Gateway accepts connection
2. `connect_handler` logs connection_id
3. NO entity bound yet — connection is "orphaned"
4. Client must send `possess` command to bind

**possess command:**
1. Client sends: `{"command": "possess", "data": {"entity_uuid": "...", "entity_aspect": "..."}}`
2. Handler finds existing entity with that connection_id, detaches if found
3. Sends SNS event to entity: `attach_connection` with connection_id
4. Entity stores connection_id, begins pushing events

**Regular commands:**
1. Client sends: `{"command": "look"}` or `{"command": "move", "data": {"direction": "north"}}`
2. Handler finds entity by connection_id
3. Sends SNS event: `receive_command` with command and args
4. Entity's `receive_command` routes to `@player_command` method

**$disconnect:**
1. API Gateway notifies disconnect
2. `disconnect_handler` finds entity with this connection_id
3. Sends SNS event: `detach_connection`
4. Entity clears connection_id

### Event Flow

**Entity → Player:**
```python
self.push_event({"event": "you_see", "description": "A dark room..."})
```
This checks `self.connection_id`, uses `apigatewaymanagementapi` to post to WebSocket.

**Player → Entity:**
Always routed through SNS to preserve the event architecture. Never direct Lambda calls.

### Scaling Considerations

**Problem:** `apigatewaymanagementapi` requires knowing the API Gateway endpoint. In LocalStack this is `http://localhost:4566/_aws/execute-api`. In AWS it's `https://{api-id}.execute-api.{region}.amazonaws.com/{stage}`.

**Solution:** `aws_client.py` detects LocalStack mode and configures endpoint accordingly.

**Deferred concern:** WebSocket connections have 2-hour idle timeout. Need keepalive pings? Not implemented yet.

---

## Local Development Philosophy

### LocalStack

**Principle:** The game should run entirely locally without AWS credentials. Same/same as cloud version.

**How:** LocalStack provides SNS, DynamoDB, Step Functions, API Gateway locally. `aws_client.py` detects `LOCALSTACK_ENDPOINT` env var and routes there.

**Benefits:**
- No cloud costs during development
- No credential sharing
- Deterministic testing
- Works offline

**Trade-offs:**
- Not identical to AWS (some edge cases differ)
- Performance characteristics different

### Testing Strategy

**Unit tests:** Use `moto` mocks. Fast, no dependencies.

**Integration tests:** Run against LocalStack. Tests actual event flow through SNS.

**Current state:** `moto` tests in `aspects/tests/`. LocalStack test runner in `scripts/local-test.sh`. Need more integration coverage.

---

## AI Agent Design (Future, But In Mind)

**Goal:** AI agents are first-class players. Not "playing the API" — playing the *game*.

**How it works:**
1. Agent SDK connects via WebSocket (same as human client)
2. JWT identifies the agent (stored like API credential)
3. Events arrive as JSON → parsed → state updated
4. Agent logic decides action → command sent

**What agents can do:**
- Play NPCs when no human connected
- Take over creatures to assist players
- Act as "dungeon master" orchestrating scenarios
- Compete with humans (PvP, leaderboards)

**Design constraint:** Agents must be indistinguishable from humans in the event stream. If an agent needs "super powers," that's a different entity type (system entity), not a cheating player.

**Open question:** Should we provide agent SDK as separate package? Or just document the WebSocket protocol?

---

## Deferred Items (Known, Not Forgotten)

### JWT Refresh/Revocation
- **Issue:** No strategy for token refresh or revocation
- **Plan:** Implement when we get closer to production/OAuth

### SNS Single Point of Failure
- **Issue:** If SNS fails, game stops
- **Acceptance:** SNS has 99.9% SLA. Acceptable for current scale.
- **Future:** Consider event bus abstraction with fallback

### Entity Garbage Collection
- **Issue:** Disconnected/abandoned entities accumulate
- **Plan:** Not needed now. When scale demands: TTL on DynamoDB with `last_activity`, or periodic cleanup Lambda

### Race Conditions
- **Issue:** Simultaneous events on same entity could conflict
- **Current:** DynamoDB handles concurrency at storage layer
- **Concern:** Event ordering guarantees? Need to test.

---

## TODO / Current Work

### Immediate (Next Session)
- [x] ~~Email/Password Auth~~ — **DEPRECATED: Using Firebase Auth instead**
  - Historical designs: docs/AUTH_DESIGN.md, docs/EMAIL_DESIGN.md
- [ ] **Google OAuth 2.0** — Google Sign-In (no passwords, no Firebase)
  - See `docs/design/decisions/oauth.md` for technical details
  - Create Google Cloud project, configure OAuth consent screen
  - Create `users` DynamoDB table (google_id PK, entity assignment)
  - Implement `/api/auth/login` — verify Google ID token, get/create user, issue internal JWT
  - Auto-create Player entity at (0,0,0) on first sign-in
  - WebSocket auth with internal JWT → auto-possess entity
  - Frontend React app with Google Sign-In button (react-oauth/google or direct flow)
- [ ] Test WebSocket end-to-end with real client
- [ ] Add keepalive/ping to prevent 2-hour timeout

### Near Term (This Week)
- [ ] **Web UI — Auth (React + Firebase)** — Google Sign-In only
  - React app with React Router
  - Landing page with game description + "Sign in with Google" button
  - Firebase Auth client SDK integration
  - Auth state management (logged in / logged out)
  - Automatic redirect to /play after sign-in
- [ ] **Web UI — Game Page (React)** — `/play` interface
  - WebSocket connection with auto-possession
  - Event log panel (styled by event type)
  - Sidebar: location, stats, inventory
  - Command input with history
  - Quick action buttons
- [ ] **Agent-Friendly REST API** — For programmatic access
  - POST /api/auth/register, /verify, /login
  - GET /api/player/me, /location, /inventory
  - POST /api/command
  - Document in API_SPEC.md
- [ ] Add tests for `websocket_handlers.py`
- [ ] Create example web client (vanilla JS)
- [ ] Stress test: 100 concurrent connections

### Medium Term (This Month)
- [ ] **Agent SDK** — Python package for bot development
  - Agent class with WebSocket/REST support
  - Event handling framework
  - Command builders
  - Example bot implementations

### Near Term (This Week)
- [ ] Add tests for `websocket_handlers.py`
- [ ] Document the WebSocket protocol formally
- [ ] Create example web client (vanilla JS)
- [ ] Stress test: 100 concurrent connections

### Medium Term (This Month)
- [ ] Implement combat aspect
- [ ] Implement inventory aspect  
- [ ] NPC AI behavior trees
- [ ] World persistence across deploys

### Architectural Questions to Resolve
- [ ] Aspect dependency system needed?
- [ ] Event versioning strategy?
- [ ] Should we support entity migration (UUID → different aspect)?
- [ ] How to handle "world restart" events?

---

## Code Organization Principles

### Lambda = Aspect
Each file in `aspects/` is essentially one Lambda handler. `handler.py` factory routes events to the right class.

### State in DynamoDB, Logic in Lambda
No long-running state. Entity loaded from DB, method runs, entity saved. Cold starts are acceptable.

### Decorators for Security
`@callable`, `@player_command`, `@admin_only`, `@system_entity`. Security declared at method level, enforced at runtime.

### Configuration via Environment
LocalStack vs AWS determined by env vars. No code changes needed to switch environments.

---

## Extracted (Graduated to Formal Docs)

- GAME_DESIGN.md — Core game concepts and world model
- (Future) WEBSOCKET_DESIGN.md — Detailed protocol spec
- (Future) AGENT_SDK.md — AI agent development guide

---

*Last updated: 2026-02-05*
*Branch: design*
*Status: Living document — expect graffiti*
