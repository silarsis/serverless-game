# Onboarding Guide - New Developer/Agent

*Welcome to the serverless game! This guide will get you oriented and productive.*

## 5-Minute Orientation

### What is this?
A multiplayer text-based game using aspect-oriented serverless architecture on AWS.
Think MUD (Multi-User Dungeon) meets modern cloud infrastructure.

### Key Concepts (in 30 seconds)
1. **Aspect** = Lambda function handling one concern (location, combat, etc.)
2. **Event** = Message on SNS bus triggering aspects
3. **Entity** = Game object (player, mob, item) with UUID
4. **No OOP** = Aspects compose via events, not inheritance

## Your First Hour

### 1. Read the Map (5 min)
- Start with `../AGENTS.md` - the 100-line repository guide
- It points to everything else

### 2. Understand Architecture (15 min)
- Read `../architecture/README.md`
- Focus on: aspect-oriented design, event flow, system diagram

### 3. See What's Built (10 min)
- Review `../design/catalog.md` - all 21 planned features
- Check `../quality/assessment.md` - what's actually working

### 4. Run It Locally (20 min)
```bash
# Setup
./scripts/local-setup.sh

# Start LocalStack and services
docker-compose up -d

# Run interactive game
python scripts/local-runner.py --command interactive
```

### 5. Explore the Code (10 min)
- `backend/aspects/` - Lambda functions
- `backend/lib/` - Shared utilities
- `docs/design/features/` - Feature specifications

## Common Tasks

### Adding a New Aspect

1. **Read** `../architecture/README.md` section "Adding Aspects"
2. **Design** document in `../design/decisions/my-aspect.md`
3. **Implement** Lambda in `backend/aspects/my_aspect.py`
4. **Test** in `backend/tests/test_my_aspect.py`
5. **Update** `../quality/assessment.md`

### Implementing a Feature

1. **Check** `../design/catalog.md` for feature status
2. **Read** relevant `../design/features/XX-feature.md`
3. **Create** execution plan in `../plans/active/my-feature.md`
4. **Implement** aspects per design
5. **Update** `../plans/technical-debt.md` when done

### Understanding WebSocket Flow

1. **Architecture:** `../architecture/websocket-design.md`
2. **Implementation:** `../plans/completed/websocket-implementation.md`
3. **Test:** Connect via wscat: `wscat -c ws://localhost:3001`

## Key Files Quick Reference

| Task | File |
|------|------|
| What's implemented? | `../quality/assessment.md` |
| How does aspect X work? | `../architecture/README.md` + source |
| How to add feature Y? | `../design/features/YY-*.md` |
| What's broken? | `../plans/technical-debt.md` |
| Design philosophy | `../design/core-beliefs.md` |
| Domain terms | `./glossary.md` (this directory) |

## Development Workflow

### Before Starting Work
```bash
# Pull latest
git pull origin main

# Check current state
cat ../quality/assessment.md

# Check planned work
cat ../plans/technical-debt.md
```

### During Development
```bash
# Run tests frequently
cd backend && python -m pytest

# Test your aspect locally
python scripts/local-runner.py --command test

# Check docs still valid
# (No automated check yet - manual review)
```

### Before Committing
```bash
# Run full test suite
python -m pytest backend/tests/

# Update relevant docs
vim ../quality/assessment.md

# Commit with context
git commit -m "aspect: add damage calculation to combat

- Implements damage formula from design/features/01-combat.md
- Adds tests for edge cases
- Updates assessment.md status"
```

## Common Pitfalls

### ❌ Thinking in OOP
**Wrong:** "I'll add a Player class that inherits from Mob"
**Right:** "I'll add a PlayerIdentity aspect that tracks player-specific data"

### ❌ Direct Aspect Calls
**Wrong:** `location_aspect.move_entity(uuid, dest)`
**Right:** `event_bus.publish(aspect='location', action='move', ...)`

### ❌ Storing State in Lambda
**Wrong:** Global variables, instance state
**Right:** Read from DynamoDB every invocation, write when done

### ❌ Skipping Design Doc
**Wrong:** Jump straight to code
**Right:** Write/update design doc first, get alignment, then code

## Getting Help

### Documentation
- **Architecture questions:** `../architecture/README.md`
- **Design questions:** `../design/catalog.md` + specific feature doc
- **Quality concerns:** `../quality/assessment.md`
- **Roadmap:** `../plans/technical-debt.md`

### Code Exploration
```bash
# Find where something is implemented
grep -r "def move" backend/aspects/

# Find event handlers
grep -r "action.*move" backend/

# See test examples
cat backend/tests/test_location_aspect.py
```

### When Stuck
1. Check if design doc exists for what you're building
2. Look at existing aspects (Location, Land) as examples
3. Review `../design/core-beliefs.md` for architectural guidance
4. Check `../quality/assessment.md` for known blockers

## Agent-Specific Notes

If you're an AI agent working on this codebase:

1. **Always start with AGENTS.md** - it's the map
2. **Follow progressive disclosure** - don't read everything at once
3. **Update docs as you go** - assessment.md, technical-debt.md
4. **Cite sources** - when making changes, reference design docs
5. **Test incrementally** - run tests after small changes, not just at end
6. **Ask for clarification** - if design doc contradicts code, flag it

## Quick Commands Cheat Sheet

```bash
# Setup
docker-compose up -d                    # Start LocalStack
./scripts/local-setup.sh                # Install deps

# Development
docker-compose logs -f localstack       # Watch LocalStack
python scripts/local-runner.py          # Interactive game
cd backend && python -m pytest          # Run tests

# Debugging
aws --endpoint-url=http://localhost:4566 dynamodb scan --table-name location_table
aws --endpoint-url=http://localhost:4566 sns list-topics
```

---

*This is an agent-maintained codebase. If this doc is confusing, update it!*
*Last updated: 2026-02-12*
