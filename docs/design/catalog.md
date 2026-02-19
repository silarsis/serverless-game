# Feature Design Catalog

*Index of all 21 game features with design status and implementation status.*

## Legend

| Status | Meaning |
|--------|---------|
| 📋 Designed | Has detailed design document |
| 🔧 Partial | Partially implemented |
| ✅ Complete | Fully implemented and tested |
| 🚫 Blocked | Blocked by dependencies |
| 💡 Concept | Brief idea only |

---

## Core Systems (1-5)

| # | Feature | Design Doc | Status | Aspect Status | Notes |
|---|---------|------------|--------|---------------|-------|
| 01 | **Combat** | [01-combat.md](features/01-combat.md) | 📋 Designed | 💡 Concept | HP, damage, fighting system |
| 02 | **Crafting** | [02-crafting.md](features/02-crafting.md) | 📋 Designed | 💡 Concept | Recipes, item creation |
| 03 | **Quest Journal** | [03-quest-journal.md](features/03-quest-journal.md) | 📋 Designed | 💡 Concept | Quest tracking, objectives |
| 04 | **Magic Spells** | [04-magic-spells.md](features/04-magic-spells.md) | 📋 Designed | 💡 Concept | Spell system, mana, effects |
| 05 | **Equipment** | [05-equipment.md](features/05-equipment.md) | ✅ Complete | ✅ Complete | Gear, slots, stats |

## World Systems (6-10)

| # | Feature | Design Doc | Status | Aspect Status | Notes |
|---|---------|------------|--------|---------------|-------|
| 06 | **Day/Night/Weather** | [06-day-night-weather.md](features/06-day-night-weather.md) | 📋 Designed | 💡 Concept | Time cycles, weather effects |
| 07 | **Faction Reputation** | [07-faction-reputation.md](features/07-faction-reputation.md) | 📋 Designed | 💡 Concept | NPC factions, standing |
| 08 | **Building Construction** | [08-building-construction.md](features/08-building-construction.md) | 📋 Designed | 💡 Concept | Building, structures |
| 09 | **Dialogue Trees** | [09-dialogue-trees.md](features/09-dialogue-trees.md) | 📋 Designed | 💡 Concept | NPC conversations |
| 10 | **Procedural Dungeons** | [10-procedural-dungeons.md](features/10-procedural-dungeons.md) | 📋 Designed | 💡 Concept | Generated dungeons |

## Gameplay Systems (11-15)

| # | Feature | Design Doc | Status | Aspect Status | Notes |
|---|---------|------------|--------|---------------|-------|
| 11 | **Stealth/Perception** | [11-stealth-perception.md](features/11-stealth-perception.md) | 📋 Designed | 💡 Concept | Sneaking, detection |
| 12 | **Status Effects** | [12-status-effects.md](features/12-status-effects.md) | 📋 Designed | 💡 Concept | Buffs, debuffs |
| 13 | **Trading/Economy** | [13-trading-economy.md](features/13-trading-economy.md) | 📋 Designed | 💡 Concept | Markets, currency |
| 14 | **Exploration/Cartography** | [14-exploration-cartography.md](features/14-exploration-cartography.md) | 📋 Designed | 💡 Concept | Maps, fog of war |
| 15 | **Taming Companions** | [15-taming-companions.md](features/15-taming-companions.md) | 📋 Designed | 💡 Concept | Pets, followers |

## Social/Advanced Systems (16-21)

| # | Feature | Design Doc | Status | Aspect Status | Notes |
|---|---------|------------|--------|---------------|-------|
| 16 | **Shared Knowledge** | [16-shared-knowledge.md](features/16-shared-knowledge.md) | 📋 Designed | 💡 Concept | Learning, libraries |
| 17 | **Party System** | [17-party-system.md](features/17-party-system.md) | 📋 Designed | 💡 Concept | Groups, raids |
| 18 | **Collaborative Projects** | [18-collaborative-projects.md](features/18-collaborative-projects.md) | 📋 Designed | 💡 Concept | Guild projects |
| 19 | **Social Graph** | [19-social-graph.md](features/19-social-graph.md) | 📋 Designed | 💡 Concept | Relationships |
| 20 | **Structured Messaging** | [20-structured-messaging.md](features/20-structured-messaging.md) | 📋 Designed | 💡 Concept | Chat system |
| 21 | **Player Identity** | [21-player-identity.md](features/21-player-identity.md) | 📋 Designed | 💡 Concept | Identity, alts |

---

## Implementation Summary

| Category | Designed | In Progress | Complete |
|----------|----------|-------------|----------|
| Core Systems | 5/5 | 0/5 | 0/5 |
| World Systems | 5/5 | 0/5 | 0/5 |
| Gameplay Systems | 5/5 | 0/5 | 0/5 |
| Social/Advanced | 6/6 | 0/6 | 0/6 |
| **TOTAL** | **21/21** | **0/21** | **0/21** |

## Priority Queue (Suggested Implementation Order)

Based on dependencies and core gameplay loop:

1. ✅ **Location** (already implemented - movement, positioning)
2. ✅ **Land** (already implemented - terrain, claims)
3. 🔧 **Combat** (01) - Core gameplay, enables fighting
4. 🔧 **Equipment** (05) - Natural extension of combat
5. 🔧 **Quest Journal** (03) - Gives players goals
6. 🔧 **Status Effects** (12) - Enhances combat
7. 🔧 **Magic Spells** (04) - Advanced combat
8. 🔧 **Crafting** (02) - Economy entry point
9. 🔧 **Day/Night/Weather** (06) - World flavor
10. 🔧 **Building Construction** (08) - Player persistence

... (remaining follow based on player feedback and dev priorities)

## Design Verification Status

All 21 designs have been reviewed. See `../quality/critical-review.md` for critiques.

**Design Quality Tiers:**
- **Tier 1 (Implementation Ready):** Designs with clear data models, API specs, aspect boundaries
- **Tier 2 (Needs Refinement):** Good concepts but lacking implementation details
- **Tier 3 (Conceptual Only):** High-level ideas, needs significant design work

*Update this section as designs are refined.*

---

*Last updated: 2026-02-12*
*All 21 features have detailed design documents in docs/design/features/*
