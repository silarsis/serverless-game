# Glossary - Domain Terminology

*Quick reference for terms used throughout the serverless game codebase and documentation.*

## Core Concepts

### Aspect
A Lambda function that handles one specific concern of the game. Aspects communicate via events rather than direct calls. Examples: LocationAspect, CombatAspect, LandAspect.

**Related:** Aspect-oriented design, Event-driven architecture

### Aspect-Oriented Design (AOD)
Architectural pattern where cross-cutting concerns (aspects) are separated from entities. Contrast with OOP where objects bundle data and methods.

**See:** `../design/core-beliefs.md` principle #1

### Entity
A game object with a unique identifier (UUID). Can be a player character, mob, item, or location. Entities have state distributed across aspect tables.

**Example:** `uuid: "mob-123-abc"` might have:
- Position in `location_table`
- Health in `combat_table`
- Inventory in `equipment_table`

### Event
A message published to the SNS topic that triggers aspect processing. The fundamental unit of state change in the system.

**Structure:**
```yaml
event:
  aspect: "location"      # Which aspect handles it
  action: "move"          # What to do
  uuid: "mob-123"         # Target entity
  data: {...}             # Action-specific data
```

### Event Bus
The SNS topic `game-events` that all aspects subscribe to. Decouples aspects from each other.

**See:** `../architecture/README.md`

### Mob
A mobile entity in the game world. Originally MUD terminology. Can be player-controlled or NPC.

### Aspect Table
DynamoDB table storing state for one aspect. Named after aspect: `location_table`, `combat_table`, etc.

### Lambda
AWS Lambda function - the compute layer for aspects. Stateless, event-triggered.

## Game Mechanics

### HP / Health Points
Measure of entity vitality. 0 HP = death/unconsciousness.

**Aspect:** Combat aspect manages HP

### Location
A position in the game world. Has a UUID, coordinates, terrain type, and contained entities.

**Aspect:** Location aspect manages positions

### Land
A claimable area in the game world. Players can own land, build on it.

**Aspect:** Land aspect manages claims and terrain

### Crafting
Creating items from recipes and components.

**Feature:** 02-crafting.md (designed, not implemented)

### Quest
A goal-based activity with objectives and rewards.

**Feature:** 03-quest-journal.md (designed, not implemented)

### Faction
An NPC organization with reputation system. Player actions affect standing.

**Feature:** 07-faction-reputation.md

## Technical Terms

### DynamoDB
AWS NoSQL database. Stores all game state across aspect tables.

**Partition Key:** Usually entity UUID
**Sort Key:** Varies by aspect (timestamp, location, etc.)

### SNS
AWS Simple Notification Service. Pub/sub messaging used as event bus.

**Topic:** `game-events` - main event bus

### LocalStack
AWS service emulator for local development. Runs in Docker, simulates Lambda, DynamoDB, SNS locally.

**See:** `../operations/local-dev.md`

### Step Functions
AWS workflow service. Used for delayed event delivery (e.g., "in 5 minutes, heal player").

### JWT
JSON Web Token. Authentication mechanism. Passed in WebSocket connect or API headers.

**See:** `../architecture/websocket-design.md`

### WebSocket
Persistent TCP connection for real-time bidirectional communication. Used for game updates to clients.

**See:** `../architecture/websocket-design.md`

### API Gateway
AWS service for HTTP and WebSocket APIs. Entry point for client requests.

**Routes:**
- REST: `/api/*` → REST aspect
- WebSocket: `wss://*/ws` → WebSocket handler

## Design Patterns

### ADR
Architecture Decision Record. Document capturing why a decision was made. Stored in `../design/decisions/`.

### Progressive Disclosure
Documentation pattern where users (agents) start with a simple map (AGENTS.md) and navigate to deeper docs as needed. Avoids overwhelming with information.

**See:** `../design/core-beliefs.md` principle #6

### Harness Engineering
OpenAI's methodology for agent-first development. Repository as environment for agents, extensive documentation, mechanical validation.

**Reference:** openai.com/index/harness-engineering

## Development Terms

### Implementation Check
File tracking what's built vs designed. Now `../plans/technical-debt.md`.

### Feature Design
Detailed specification for a game feature in `../design/features/`. Numbered 01-21.

### Quality Assessment
Honest evaluation of code health. `../quality/assessment.md`.

### Execution Plan
Document for complex work in progress, in `../plans/active/`. Tracks goal, steps, decisions, progress.

## Abbreviations

| Term | Meaning |
|------|---------|
| AOD | Aspect-Oriented Design |
| ADR | Architecture Decision Record |
| AWS | Amazon Web Services |
| DB | Database (usually DynamoDB) |
| HP | Health Points |
| JWT | JSON Web Token |
| NPC | Non-Player Character |
| SNS | Simple Notification Service |
| UUID | Universally Unique Identifier |
| WIP | Work In Progress |
| REST | Representational State Transfer |
| WS | WebSocket |

---

*Add terms as you encounter them. Keep definitions concrete and cross-linked.*
*Last updated: 2026-02-12*
