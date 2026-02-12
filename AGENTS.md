# AGENTS.md - Serverless Game Repository Guide

> **STRUCTURE NOTE FOR CLAUDE:** This repository follows the OpenAI harness engineering pattern.
> AGENTS.md is a MAP (not an encyclopedia). Detailed knowledge lives in `docs/`.
> When working, start here for orientation, then navigate to specific docs/ sections.

## Repository Overview

A toy game world built with **aspect-oriented serverless architecture** using AWS Lambda, DynamoDB, and SNS.

**Key Principle:** Aspect-oriented design (not OOP). Each aspect is a Lambda listening to events on SNS.

## Quick Start for New Agents

1. **First read:** `docs/README.md` - Knowledge base overview
2. **Understand architecture:** `docs/architecture/README.md` - Domain map
3. **See what's designed:** `docs/design/catalog.md` - All 21 feature designs
4. **Check current state:** `docs/quality/assessment.md` - What's solid vs gaps

## Working Agreements

- Run tests before PRs: `cd backend && python -m pytest`
- Local dev: `./scripts/local-setup.sh` then `python scripts/local-runner.py`
- Update docs when changing: public APIs, aspect behavior, or architecture
- Document decisions in: `docs/design/decisions/`
- Feature designs go in: `docs/design/features/XX-feature-name.md`

## Directory Structure (Where to Find Things)

```
AGENTS.md              ← You are here (the map)
docs/
├── README.md          ← Start here for knowledge base overview
├── requirements.md    ← Project requirements
├── architecture/      ← System architecture & domain map
│   ├── README.md      ← Architecture overview
│   └── websocket-design.md  ← WebSocket architecture
├── design/
│   ├── catalog.md     ← Index of all 21 features + status
│   ├── core-beliefs.md ← Agent-first principles (was GAME_DESIGN.md)
│   ├── decisions/     ← ADRs (Auth, Email, OAuth, Firebase)
│   └── features/      ← 21 feature designs (01-combat.md through 21-player-identity.md)
├── quality/
│   ├── assessment.md  ← What's working vs needs work
│   └── critical-review.md ← Design critiques
├── plans/
│   ├── active/        ← In-progress work
│   ├── completed/     ← Finished implementations
│   └── technical-debt.md ← Known issues (was IMPLEMENTATION_CHECK.md)
├── context/
│   ├── design-context.md ← Design philosophy (was DESIGN_CONTEXT.md)
│   ├── onboarding.md  ← New developer guide
│   └── glossary.md    ← Domain terminology
└── operations/
    ├── deployment.md  ← Firebase setup (was FIREBASE_MANUAL_SETUP.md)
    └── local-dev.md   ← Extracted from root README
```

## Code Locations

| Component | Path |
|-----------|------|
| Backend (Lambda aspects) | `backend/` |
| Frontend | `frontend/` |
| Infrastructure | `infra/` |
| Local dev scripts | `scripts/` |
| Claude commands | `.claude/commands/` |

## Key Architectural Concepts

**Aspect-Oriented Design:**
- Each aspect (location, land, combat, etc.) is a Lambda function
- Aspects communicate via SNS event bus
- Events have: `aspect`, `action`, `uuid`, `data`

**Event Example:**
```yaml
event:
  aspect: location
  action: move
  uuid: <mob uuid>
  data:
    from_loc: <current location uuid>
    to_loc: <new location uuid>
```

## 21 Feature Designs (in docs/design/features/)

1. Combat (01-combat.md)
2. Crafting (02-crafting.md)
3. Quest Journal (03-quest-journal.md)
4. Magic Spells (04-magic-spells.md)
5. Equipment (05-equipment.md)
6. Day/Night/Weather (06-day-night-weather.md)
7. Faction Reputation (07-faction-reputation.md)
8. Building Construction (08-building-construction.md)
9. Dialogue Trees (09-dialogue-trees.md)
10. Procedural Dungeons (10-procedural-dungeons.md)
11. Stealth/Perception (11-stealth-perception.md)
12. Status Effects (12-status-effects.md)
13. Trading/Economy (13-trading-economy.md)
14. Exploration/Cartography (14-exploration-cartography.md)
15. Taming Companions (15-taming-companions.md)
16. Shared Knowledge (16-shared-knowledge.md)
17. Party System (17-party-system.md)
18. Collaborative Projects (18-collaborative-projects.md)
19. Social Graph (19-social-graph.md)
20. Structured Messaging (20-structured-messaging.md)
21. Player Identity (21-player-identity.md)

## Common Tasks

**Adding a new aspect:**
1. Read `docs/architecture/README.md`
2. Create Lambda in `backend/`
3. Add to event bus configuration
4. Document in `docs/design/decisions/`

**Implementing a feature:**
1. Check `docs/design/catalog.md` for feature status
2. Read relevant `docs/design/features/XX-*.md`
3. Check `docs/quality/assessment.md` for dependencies
4. Update `docs/plans/technical-debt.md` when complete

**Understanding WebSocket system:**
- Architecture: `docs/architecture/websocket-design.md`
- Implementation: `docs/plans/completed/websocket-implementation.md`

## Quality & Standards

- All aspects must have tests in `backend/tests/`
- Design decisions require ADR in `docs/design/decisions/`
- Features need design doc in `docs/design/features/` before implementation
- Update `docs/quality/assessment.md` when completing work

## Working with Claude Code

This repo is being developed with agent-first principles. The structure supports:
- Progressive disclosure (start small, navigate deep)
- Mechanical validation (linting, linking, doc freshness)
- Agent-to-agent review (design docs → implementation → quality check)

For complex work, create an execution plan in `docs/plans/active/` with:
- Goal statement
- Steps with checkboxes
- Decision log
- Progress updates
