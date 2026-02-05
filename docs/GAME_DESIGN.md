# Game Design Document

## What Is This?

A **persistent, event-driven game world** where entities (creatures, objects, places) exist independently of players. Players connect to entities via WebSocket and experience the world *through* them — seeing what they see, controlling what they do.

The twist: **AI agents and humans play by the same rules.** Both connect to entities. Both receive events. Both issue commands. The game doesn't know or care who's behind the connection.

## Core Principles

### 1. Aspect-Oriented Architecture
Traditional OOP: `Dragon extends Monster extends Entity`

This game: `Dragon has Location, Combat, Inventory aspects`

Each aspect is a Lambda function that handles one concern. Aspects communicate via events on an SNS bus. A dragon doesn't "know" it's a dragon — it just responds to events routed to its UUID.

### 2. The Entity Is The Viewport
There's no "camera" or "observer mode." You see what your entity experiences:
- It moves → you get the room description
- It gets hit → you see the combat event
- It hears something → the sound event arrives

Disconnect, and the entity continues existing. It just stops pushing events to you.

### 3. Connection As Pipe
A WebSocket is **not** an entity. It's a pipe attached to an entity:
```
Entity (has connection_id) ←→ WebSocket ←→ Player/AI Agent
```

The entity holds the connection. While connected, it pushes events up and receives commands down.

### 4. Symmetry Between Human and AI
Both use the same interface:
- Connect via WebSocket with JWT auth
- Receive events (same format, same timing)
- Send commands (same `@player_command` methods)

An AI isn't "playing the API" — it's playing the *game* through an entity, just like a human.

## The World Model

### Entities
Everything is a Thing (base class):
- **UUID** — immutable identity
- **connection_id** — optional WebSocket binding
- **Aspect data** — stored in DynamoDB per aspect
- **Event handlers** — `@callable` methods

### Locations
Places contain entities. A forest, a room, a void — all are locations with:
- Contents (list of entity UUIDs)
- Exits (direction → destination location)
- Properties (terrain, hazards, etc.)

### Events
All communication happens via SNS events:
```json
{
  "tid": "uuid",
  "aspect": "location",
  "action": "move",
  "uuid": "entity-uuid",
  "data": {"to_loc": "destination-uuid"},
  "actor_uuid": "optional-attacker",
  "target_uuid": "optional-target"
}
```

Events carry viewport hints for multi-party scenarios.

### Time
The world ticks. Some aspects (like LandCreator) run on timers. Player actions are real-time but the world evolves whether players are connected or not.

## Player Experience

### Connecting
1. Open WebSocket with `X-Api-Key: <JWT>` header
2. Server creates Player entity (or reconnects to existing one based on JWT `sub` claim)
3. Entity's `connection_id` is set
4. Events begin flowing immediately

### Playing
Events arrive as JSON:
```json
{"event": "room_description", "data": {...}}
{"event": "combat", "actor": "goblin", "action": "attack", "damage": 5}
{"event": "tell", "from": "player-123", "message": "Behind you!"}
```

Commands sent as JSON:
```json
{"command": "look", "args": {}}
{"command": "attack", "args": {"target": "goblin-uuid"}}
{"command": "say", "args": {"message": "Hello"}}
```

### Disconnecting
Connection drops → entity's `connection_id` cleared → entity continues in world, now autonomous or following default behavior.

## AI Agent Experience

Identical to human, except:
- JWT stored as API credential
- Events processed by code, not rendered to screen
- Commands issued programmatically based on event stream

An AI could:
- Play a wandering merchant NPC when no human is connected
- Take over a creature to assist a player
- Control a "dungeon master" entity that orchestrates scenarios

## Security Model

### Authentication
- JWT in `X-Api-Key` header on WebSocket connect
- `sub` claim = persistent player identity
- Can upgrade to OAuth later without architectural changes

### Authorization
- **Own entities only** — players can only possess their own player object
- **System entities** — marked with `@system_entity`, cannot be possessed
- **Command filtering** — only `@player_command` methods exposed via WebSocket

### Command Safety
```python
@callable              # Internal use only
async def _internal_logic(self): ...

@player_command        # Callable via WebSocket
async def look(self): ...

@admin_only            # Requires admin JWT claim
async def spawn_god(self): ...
```

## Current State vs Future

### Implemented
- [x] Aspect-oriented Lambda architecture
- [x] SNS event bus
- [x] DynamoDB persistence
- [x] LocalStack local development
- [x] CI/CD pipeline

### In Progress (WebSocket Layer)
- [ ] WebSocket API Gateway
- [ ] Connection management (entity holds connection_id)
- [ ] Event push from entities
- [ ] Command routing to entities
- [ ] JWT authentication
- [ ] `@player_command` decorator

### Future
- [ ] AI agent SDK (connect, handle events, send commands)
- [ ] Multi-entity possession (admin feature)
- [ ] Observer entities (camera mode)
- [ ] Event replay / time travel debugging
- [ ] World persistence across deploys

## Why This Architecture?

### Serverless
- Pay per request, not per uptime
- World "exists" without running servers (just Lambdas responding to events)
- Infinite scale if needed (though we're not building for scale)

### Event-Driven
- Loose coupling between aspects
- Easy to add new features (new aspect subscribes to events)
- Natural fit for AI agents (event stream → state → action)

### Entity-Centric Viewport
- No special cases for AI vs human
- Entity autonomy when disconnected (NPC behavior)
- "Possession" is a natural metaphor

## Technical Stack

| Component | Local | Cloud |
|-----------|-------|-------|
| Compute | Local runner / Lambda container | AWS Lambda |
| Events | LocalStack SNS | AWS SNS |
| State | LocalStack DynamoDB | AWS DynamoDB |
| WebSocket | LocalStack API Gateway | AWS API Gateway |
| Auth | Local JWT validation | Cognito or custom |
| Deployment | Docker Compose | Serverless Framework |

## Directory Guide

```
serverless-game/
├── docs/GAME_DESIGN.md           # This document
├── docs/WEBSOCKET_DESIGN.md      # Detailed WebSocket architecture
├── docs/WEBSOCKET_IMPLEMENTATION_SUMMARY.md  # Quick reference
├── README.md                      # Setup and usage
├── backend/aspects/               # Lambda handlers
│   ├── thing.py                   # Base entity class
│   ├── location.py                # Place aspect
│   ├── land.py                    # Grid world aspect
│   ├── websocket_handlers.py      # WebSocket lifecycle
│   └── decorators.py              # @player_command, @system_entity
└── scripts/local-runner.py        # Local game runner
```

---

*Last updated: 2026-02-05*
