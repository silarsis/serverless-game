# Core Beliefs - Agent-First Operating Principles

*This document captures the fundamental principles guiding the serverless game architecture and development process.*

> **Source Note:** This was originally `GAME_DESIGN.md`, reorganized as part of the harness engineering documentation restructure. It now serves as the "core beliefs" document per OpenAI's agent-first methodology.

---

## 1. Aspect-Oriented > Object-Oriented

**Principle:** The game world is composed of cross-cutting concerns (aspects), not hierarchies of objects.

**Why:**
- Real game entities (mobs, items, locations) have multiple overlapping concerns
- A "player character" has: location, health, inventory, quests, reputation, etc.
- Traditional OOP forces artificial inheritance hierarchies
- Aspect-oriented: Each concern is a separate Lambda that handles its domain

**Manifestation:**
```yaml
# Event-driven aspect interaction
event:
  aspect: combat
  action: damage
  uuid: player-123
  data:
    amount: 10
    source: mob-456
# Location aspect doesn't need to know about combat
# Combat aspect handles damage, may emit death event
# Death event picked up by location aspect (corpse handling)
```

---

## 2. Event-Driven Architecture

**Principle:** All state changes flow through events on the SNS bus.

**Why:**
- Loose coupling - aspects don't know about each other
- Audit trail - every state change is logged
- Replay capability - events can be replayed for testing/debugging
- Scalability - aspects scale independently

**Manifestation:**
- SNS topic as central event bus
- Aspects subscribe to relevant event types
- No direct aspect-to-aspect calls (except via events)

---

## 3. Serverless-First

**Principle:** Use managed services over self-hosted infrastructure.

**Why:**
- No server maintenance
- Automatic scaling
- Pay-per-use (cost-effective for sporadic game activity)
- Focus on game logic, not infrastructure

**Manifestation:**
- AWS Lambda for compute
- DynamoDB for state
- SNS for messaging
- API Gateway for HTTP/WebSocket
- Step Functions for delayed events

---

## 4. Agent-Maintained Codebase

**Principle:** This codebase is developed and maintained with AI agent assistance.

**Why:**
- Accelerates development (10x speedup observed)
- Enables complex documentation requirements
- Agents excel at refactoring, testing, cross-referencing

**Manifestation:**
- Comprehensive documentation in `docs/`
- AGENTS.md as entry point
- Clear architecture boundaries for agent understanding
- Claude Code commands in `.claude/commands/`
- Design-before-implement workflow

---

## 5. Design Before Implement

**Principle:** Every feature starts with a design document in `docs/design/features/`.

**Why:**
- Forces clarity of thought
- Enables review before sunk costs
- Creates documentation simultaneously
- Allows parallel work (design while implementing other features)

**Manifestation:**
- 21 feature designs for planned functionality
- ADRs (Architecture Decision Records) for major choices
- No code without corresponding design doc

---

## 6. Progressive Disclosure (Agent UX)

**Principle:** Documentation should enable progressive discovery, not overwhelm.

**Why:**
- Agents (and humans) need to start small and navigate deep
- Monolithic docs become stale and ignored
- Hierarchical structure with clear pointers

**Manifestation:**
- AGENTS.md is ~100 lines (the map)
- Points to deeper docs in `docs/`
- Each doc has "Where to find things" sections
- No single file exceeds ~2000 lines

---

## 7. Mechanical Validation

**Principle:** Documentation freshness is enforced mechanically where possible.

**Why:**
- Manual doc maintenance fails
- Agents can check links, coverage, staleness
- "Doc-gardening" as automated task

**Manifestation:**
- Catalog file lists all features with status
- Assessment file tracks quality
- Technical debt file tracks gaps
- Pre-commit hooks for doc validation (planned)

---

## 8. Stateless Aspects, Durable State

**Principle:** Lambda aspects are stateless; all state lives in DynamoDB.

**Why:**
- Aspects can crash/restart without data loss
- Enables horizontal scaling
- Simplifies testing (mock DB, not mock Lambda state)

**Manifestation:**
- Each aspect has dedicated DynamoDB table
- Events trigger Lambda, which reads/writes DB
- No in-memory state that survives invocation

---

## 9. Entities Are Persistent, Connections Are Not

**Principle:** Game entities (mobs, items) persist. WebSocket connections are ephemeral pipes.

**Why:**
- Players can disconnect/reconnect without losing character
- Multiple clients can control same entity (future feature)
- Clean separation of transport from game state

**Manifestation:**
- Entity state in DynamoDB (survives disconnect)
- WebSocket just a notification pipe
- JWT auth ties connection to entity, not vice versa

---

## 10. Real-Time via WebSocket, State via Events

**Principle:** WebSocket provides real-time notifications, but state changes only via events.

**Why:**
- Prevents race conditions
- Single source of truth (event bus)
- WebSocket can drop, but state remains consistent

**Manifestation:**
- Client sends command → REST aspect → event → state change
- Client receives notification via WebSocket
- If WebSocket drops, reconnect + state resync

---

## Application of These Beliefs

When making architectural decisions, ask:
1. Does this respect aspect boundaries?
2. Can this be implemented as a new aspect, not a modification?
3. Is the state durable and recoverable?
4. Can an agent understand this from docs alone?
5. Have I documented this decision in `docs/design/decisions/`?

---

*These beliefs guide development. They are subject to revision as we learn, but changes require ADR documentation.*
