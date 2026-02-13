# CLAUDE.md - Agent Maintenance Guide

> **For Claude Code and AI agents working on this repository**

## Quick Reference

- **Entry Point:** `AGENTS.md` - Always start here
- **Knowledge Base:** `docs/README.md` - Navigate from there
- **Current Status:** `docs/quality/assessment.md` - Check before starting
- **Design Catalog:** `docs/design/catalog.md` - See all 21 features

---

## Your Role as Agent

You are a **maintainer and implementer**, not just a code generator. This codebase follows the **OpenAI harness engineering** pattern where agents are first-class developers.

### Core Responsibilities

1. **Read before writing** - Check design docs before implementing
2. **Document as you go** - Update assessment, debt, catalog files
3. **Test continuously** - Run tests frequently, not just at the end
4. **Follow the architecture** - Aspect-oriented, event-driven, serverless
5. **Maintain freshness** - Docs must reflect code reality

---

## Understanding This Repository

### Philosophy: Aspect-Oriented Serverless

This is NOT traditional OOP. Key mental model shifts:

| Traditional | This Repository |
|-------------|-----------------|
| Objects with methods | Aspects (Lambdas) responding to events |
| Direct function calls | Events via SNS bus |
| Stateful objects | Stateless Lambdas + DynamoDB |
| Class inheritance | Aspect composition via events |

**The Event is King:** Every state change flows through the SNS event bus. Aspects subscribe to relevant events and react.

### Architecture Pattern

```
Client → API Gateway → REST Aspect → SNS Event Bus
                                           ↓
                                     ┌──────┴──────┐
                                     ↓             ↓
                               Location     Combat
                                Aspect       Aspect
                                     ↓             ↓
                                DynamoDB     DynamoDB
```

### Documentation Hierarchy (Progressive Disclosure)

```
AGENTS.md (100 lines - the MAP)
    ↓
docs/README.md (knowledge base overview)
    ↓
docs/architecture/ (domain map)
docs/design/ (catalog, decisions, features)
docs/quality/ (assessment, review)
docs/plans/ (debt, active, completed)
docs/context/ (onboarding, glossary)
docs/operations/ (deployment, local-dev)
```

**Rule:** Start at the top, navigate down as needed. Never read everything at once.

---

## Before You Start Any Work

### 1. Check Current State

```bash
# Read these files (in order)
cat docs/quality/assessment.md      # What's working, what needs work
cat docs/plans/technical-debt.md    # Known issues
cat docs/design/catalog.md          # Feature status
```

### 2. Verify Understanding

Ask yourself:
- [ ] What aspect(s) will this touch?
- [ ] Are there existing design docs for this?
- [ ] What's the dependency chain?
- [ ] Does this change public APIs?

### 3. For Complex Work: Create Execution Plan

If work spans multiple files or days, create:
`docs/plans/active/YYYY-MM-DD-feature-name.md`

Template:
```markdown
# Execution Plan: Feature Name

**Goal:** One sentence
**Agent:** Your name/ID
**Started:** Date

## Steps
- [ ] Step 1
- [ ] Step 2

## Decision Log
| Date | Decision | Rationale |
|------|----------|-----------|

## Progress
YYYY-MM-DD: What was done
```

---

## While You Work

### Code Standards

**Python (Backend Aspects):**
- Type hints required
- Docstrings for public functions
- Tests for aspect behavior
- Event structure validation

**Tests:**
```bash
cd backend
python -m pytest tests/test_YOUR_ASPECT.py -v
```

**Event Structure:**
```python
# Always validate events
if not all(k in event for k in ['aspect', 'action', 'uuid']):
    raise ValueError("Invalid event structure")
```

### Documentation Updates (Required)

Update these files as you work:

| File | When to Update | What to Add |
|------|----------------|-------------|
| `docs/quality/assessment.md` | After completing work | Status change, grade if significant |
| `docs/plans/technical-debt.md` | When finding/ fixing issues | New debt or resolved items |
| `docs/design/catalog.md` | When implementing features | Status emoji change |
| `docs/plans/active/*.md` | During complex work | Progress updates |

**Never leave docs stale.** If you change code, update docs in same commit.

### Commit Messages

Format:
```
aspect: brief description

- Detailed change 1
- Detailed change 2
- Updates docs/design/catalog.md
```

Example:
```
combat: implement damage calculation

- Adds damage formula per design/features/01-combat.md
- Includes armor mitigation
- Adds tests for edge cases
- Updates assessment.md: Combat now Partial
```

---

## Specific Guidance by Task Type

### Adding a New Aspect

1. **Read:** `docs/architecture/README.md` (architecture section)
2. **Design:** Document in `docs/design/decisions/YOUR_ASPECT.md`
3. **Implement:**
   - Lambda in `backend/aspects/YOUR_ASPECT.py`
   - Table definition (if needed)
   - Event handlers
4. **Test:** `backend/tests/test_YOUR_ASPECT.py`
5. **Update:** `docs/quality/assessment.md`

### Implementing a Feature

1. **Check:** `docs/design/catalog.md` for design status
2. **Read:** Relevant `docs/design/features/XX-*.md`
3. **Check:** `docs/quality/assessment.md` for dependencies
4. **Implement:** Required aspects
5. **Update:** 
   - `docs/design/catalog.md` (change status emoji)
   - `docs/quality/assessment.md` (update grade)
   - `docs/plans/technical-debt.md` (remove if done)

### Fixing a Bug

1. **Locate:** Aspect responsible
2. **Test:** Write test that reproduces bug
3. **Fix:** Implement fix
4. **Verify:** Test passes
5. **Document:** If significant, update `technical-debt.md`

### Refactoring

1. **Read:** All affected design docs
2. **Plan:** Document approach
3. **Test:** Ensure tests exist before refactoring
4. **Execute:** Small, testable changes
5. **Validate:** All tests pass
6. **Update:** Any affected documentation

---

## Common Mistakes to Avoid

### ❌ Violating Aspect Boundaries

**Wrong:** Calling `location_aspect.move_entity()` directly from combat
**Right:** Publishing event: `{'aspect': 'location', 'action': 'move', ...}`

### ❌ Skipping Design Docs

**Wrong:** Jumping straight to code for new feature
**Right:** Reading `docs/design/features/XX-*.md` first

### ❌ Storing Lambda State

**Wrong:** Global variables in Lambda
**Right:** Read from DynamoDB each invocation

### ❌ Stale Documentation

**Wrong:** "I'll update docs later"
**Right:** Docs updated in same commit as code

### ❌ Breaking Event Contract

**Wrong:** Changing event structure without updating all subscribers
**Right:** Maintaining backward compatibility or updating all aspects

---

## Key Files Reference

### Must Read Before Work

| File | Purpose | Read Time |
|------|---------|-----------|
| `AGENTS.md` | Entry point, map | 2 min |
| `docs/README.md` | Knowledge base nav | 2 min |
| `docs/architecture/README.md` | Domain understanding | 5 min |
| `docs/design/core-beliefs.md` | Principles | 5 min |

### Status Check Files

| File | Check When | Update When |
|------|------------|-------------|
| `docs/quality/assessment.md` | Starting work | Completing work |
| `docs/plans/technical-debt.md` | Finding issues | Resolving issues |
| `docs/design/catalog.md` | Planning features | Implementing features |

### Deep Dive (As Needed)

| File | When to Read |
|------|--------------|
| `docs/design/features/XX-*.md` | Implementing specific feature |
| `docs/design/decisions/*.md` | Understanding past choices |
| `docs/architecture/websocket-design.md` | WebSocket work |
| `docs/context/glossary.md` | Unfamiliar terminology |
| `docs/operations/local-dev.md` | Setup issues |

---

## Mechanical Validation

When possible, verify:

1. **All features have design docs:**
   ```bash
   ls docs/design/features/*.md | wc -l  # Should be 21
   ```

2. **Catalog matches reality:**
   ```bash
   # Compare catalog status to actual implementation
   grep -r "class.*Aspect" backend/aspects/ | wc -l
   ```

3. **Tests exist for implemented aspects:**
   ```bash
   ls backend/tests/ | grep -c "test_.*_aspect.py"
   ```

4. **No broken links in docs:**
   ```bash
   # (Manual review for now - automated check planned)
   grep -r "\[.*\](.*)" docs/ | grep -v "http" | head -20
   ```

---

## Agent-to-Agent Handoff

If work spans multiple sessions or agents:

1. **Leave execution plan** in `docs/plans/active/`
2. **Document decisions** in plan's Decision Log
3. **Update catalog/assessment** with current status
4. **Commit work-in-progress** with descriptive message

---

## Emergency Procedures

### Tests Failing After Your Changes

1. Read failure output carefully
2. Check if you broke event contracts
3. Verify DynamoDB table schemas
4. Rollback if needed: `git checkout -- <files>`

### Design Doc Contradicts Code

1. Code is ground truth for implementation
2. Design doc is ground truth for intent
3. If diverged: update whichever is wrong
4. Document the divergence in Decision Log

### Unsure About Architecture Decision

1. Check `docs/design/core-beliefs.md`
2. Check relevant `docs/design/decisions/`
3. If still unclear: create ADR before proceeding

---

## Quick Commands

```bash
# Setup
docker-compose up -d                    # Start LocalStack
./scripts/local-setup.sh                # Initialize

# Development
python scripts/local-runner.py          # Interactive game
cd backend && python -m pytest          # Run tests

# Debugging
aws --endpoint-url=http://localhost:4566 dynamodb scan --table-name location_table

# Docs
ls docs/design/features/*.md | wc -l    # Count feature designs
```

---

## Summary

**You are a maintainer.** This codebase succeeds when:
- Docs stay fresh
- Architecture is respected
- Tests pass
- Features match their designs

**Start at AGENTS.md.** Navigate down the hierarchy. Update docs as you go. Test continuously. When in doubt, check `docs/design/core-beliefs.md`.

**Remember:** Progress over perfection. A working implementation with updated docs beats a perfect implementation with stale docs.

---

*This guide is agent-facing. For human contributors, see AGENTS.md and docs/context/onboarding.md*

*Last updated: 2026-02-12*
