# Serverless Game - Knowledge Base

**Repository:** https://github.com/silarsis/serverless-game  
**Architecture:** Aspect-oriented serverless (AWS Lambda + DynamoDB + SNS)  
**Agent-First:** This codebase is maintained with Claude Code agent assistance

## What This Knowledge Base Contains

This `docs/` directory is the **system of record** for the serverless game project.
Per the OpenAI harness engineering model, we treat documentation as the primary
interface for agents working on this codebase.

## Navigation Guide

### 🗺️ Getting Oriented
- **New here?** → Read `../AGENTS.md` first (the map)
- **Understand the system** → `architecture/README.md`
- **See all features** → `design/catalog.md`
- **Current status** → `quality/assessment.md`

### 🏗️ Architecture
- `architecture/README.md` - Domain map, aspect-oriented design
- `architecture/websocket-design.md` - Real-time communication architecture

### 🎨 Design Documentation
- `design/catalog.md` - Index of all 21 feature designs with status
- `design/core-beliefs.md` - Agent-first operating principles
- `design/decisions/` - Architecture Decision Records (ADRs)
- `design/features/` - 21 detailed feature designs (01-21)

### 📊 Quality & Assessment
- `quality/assessment.md` - What's solid vs needs work
- `quality/critical-review.md` - Design critiques and concerns

### 📋 Planning
- `plans/active/` - Current in-progress work
- `plans/completed/` - Finished implementations
- `plans/technical-debt.md` - Known issues and gaps

### 🎯 Context
- `context/design-context.md` - Design philosophy and constraints
- `context/onboarding.md` - New developer/agent guide
- `context/glossary.md` - Domain terminology

### 🚀 Operations
- `operations/deployment.md` - AWS deployment guide
- `operations/local-dev.md` - Local development setup

## Key Principles (from core-beliefs.md)

1. **Aspect-Oriented > Object-Oriented** - Aspects (Lambda functions) compose via events
2. **Event-Driven Architecture** - SNS topics as event bus between aspects
3. **Serverless-First** - Lambda, DynamoDB, managed services
4. **Agent-Maintained** - Documentation is primary interface for agents
5. **Progressive Disclosure** - Start with map (AGENTS.md), navigate deep

## Repository Layout

```
serverless-game/
├── AGENTS.md           ← Start here (the map)
├── README.md           ← Project overview for humans
├── docs/               ← This knowledge base (you are here)
├── backend/            ← Lambda aspects (Python)
├── frontend/           ← Web client
├── infra/            ← Infrastructure as code
├── scripts/          ← Local dev scripts
└── .claude/commands/ ← Claude Code commands
```

## Contributing (Agent or Human)

1. **Before starting work:** Check `design/catalog.md` and `plans/technical-debt.md`
2. **For complex work:** Create execution plan in `plans/active/`
3. **When making decisions:** Document in `design/decisions/`
4. **When completing work:** Update `quality/assessment.md` and `plans/technical-debt.md`
5. **Always:** Run tests, update relevant docs

## Status Overview

| Area | Status | Notes |
|------|--------|-------|
| Core aspects | Working | Location, Land implemented |
| WebSocket system | Complete | Docs in architecture/ |
| Auth system | Partial | Google OAuth designed, not implemented |
| 21 Features | Designed | All have design docs, varying implementation |

See `quality/assessment.md` for detailed status.

---

*This knowledge base is maintained per OpenAI harness engineering principles.*
*Last restructured: 2026-02-12*
