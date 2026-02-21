# Serverless Game Architecture

**Pattern:** Aspect-Oriented Serverless Architecture  
**Platform:** AWS Lambda, DynamoDB, SNS, API Gateway  
**Real-time:** WebSocket API Gateway

## Core Philosophy: Aspect-Oriented Design

Unlike traditional OOP (objects with methods), this system uses **aspects** that respond to events.

An aspect is a Lambda function that:
1. Listens to events on an SNS topic (the event bus)
2. Processes events relevant to its concern
3. May emit new events for other aspects

### Why Aspect-Oriented?

- **Decoupling:** Aspects don't know about each other directly
- **Composability:** New features by adding aspects, not modifying existing ones
- **Serverless-native:** Each aspect is independently scalable
- **Testability:** Aspects can be tested in isolation

## System Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│                        Client Layer                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Web Client  │  │ Mobile App  │  │ Future: Game Client │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │   API Gateway       │
              │   (REST + WebSocket) │
              └──────────┬───────────┘
                         │
┌────────────────────────┼────────────────────────────────────┐
│                        │         Aspect Layer              │
│                        │                                   │
│  ┌──────────┐   SNS    ▼   ┌──────────┐                    │
│  │  REST    │◄─────────────►│ Location │ DynamoDB          │
│  │  Aspect  │   Events     │  Aspect  │ location_table    │
│  └──────────┘              └──────────┘                    │
│                            ┌──────────┐                    │
│                            │   Land   │ DynamoDB          │
│                            │  Aspect  │ land_table        │
│                            └──────────┘                    │
│                            ┌──────────┐                    │
│                            │  Combat  │ DynamoDB          │
│                            │  Aspect  │ combat_table      │
│                            └──────────┘                    │
│                            ┌──────────┐                    │
│                            │   ...    │ DynamoDB          │
│                            │  (more)  │ ...               │
│                            └──────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

## Event Bus (SNS)

All communication between aspects happens via SNS topics:

```
topic: game-events

Event Structure:
{
  "aspect": "location",
  "action": "move",
  "uuid": "mob-uuid-123",
  "data": {
    "from_loc": "loc-uuid-456",
    "to_loc": "loc-uuid-789"
  }
}
```

## Current Aspects

| Aspect | Responsibility | DynamoDB Table | Status |
|--------|---------------|----------------|--------|
| **REST** | HTTP API entry point | - | Implemented |
| **Location** | Entity positioning, movement | location_table | Implemented |
| **Land** | Land claims, terrain | land_table | Implemented |
| **Weather** | Time periods, weather conditions | - (pure computation) | Implemented |
| **Combat** | Fighting, damage, HP | combat_table | Designed |
| **Crafting** | Item creation, recipes | crafting_table | Designed |
| **Quest** | Quest tracking, journal | quest_table | Designed |

## Aspect Lifecycle

1. **Initialize:** Load configuration, connect to DynamoDB
2. **Receive Event:** SNS invokes Lambda with event
3. **Process:** Read current state, apply logic, compute changes
4. **Persist:** Write new state to DynamoDB
5. **Emit:** Publish follow-up events to SNS (optional)

## Data Ownership

Each aspect owns its DynamoDB table:
- Location aspect → location_table
- Combat aspect → combat_table
- etc.

Cross-aspect data is accessed via:
1. Events (async, preferred)
2. Direct table reads (sync, when needed)

## Real-time Communication

See `websocket-design.md` for WebSocket architecture details.

**Key Points:**
- Entities hold persistent connections via WebSocket
- Connection is NOT an entity—it's a pipe attached to an entity
- JWT authentication on connect
- Fine-grained authorization (players control their own entities only)

## Infrastructure

**AWS Services Used:**
- Lambda (aspect execution)
- DynamoDB (state storage)
- SNS (event bus)
- API Gateway (REST + WebSocket)
- Step Functions (delayed events)
- S3 (assets, if needed)
- CloudWatch (logs, metrics)

**Local Development:**
- LocalStack for AWS emulation
- Docker Compose for orchestration
- See `../operations/local-dev.md`

## Package/Directory Structure

```
backend/
├── aspects/
│   ├── __init__.py
│   ├── rest_aspect.py       ← HTTP API
│   ├── location_aspect.py   ← Position, movement
│   ├── land_aspect.py       ← Land, terrain
│   └── combat_aspect.py     ← Fighting (WIP)
├── lib/
│   ├── event_bus.py         ← SNS client
│   ├── db.py                ← DynamoDB helpers
│   └── auth.py              ← JWT handling
├── tests/
│   └── aspect_tests.py
└── requirements.txt
```

## Design Decisions (ADRs)

See `../design/decisions/` for architecture decision records:
- Aspect-oriented vs OOP (`aspect-oriented.md`)
- WebSocket architecture (`websocket-design.md`)
- Auth system (`auth-system.md`, `oauth.md`)
- Serverless infrastructure (`serverless-infra.md`)

## Quality Assessment

See `../quality/assessment.md` for:
- Which aspects are solid
- Which need work
- Known issues
- Test coverage

## Future Directions

Per `../design/catalog.md`, planned aspects include:
- Combat, Crafting, Quest, Magic, Equipment
- Weather ✓, Factions, Building, Dialogue
- Dungeons, Stealth, Trading, Exploration
- Companions, Knowledge, Party, Projects
- Social Graph, Messaging, Identity

Each will follow the aspect pattern: Lambda + SNS + DynamoDB.

---

*Aspect-oriented architecture enables rapid feature addition without modifying existing working code.*
