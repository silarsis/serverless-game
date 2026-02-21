# Day/Night and Weather Cycle (Revised)

## What This Brings to the World

A day/night and weather cycle is one of the most effective ways to make a text-based world feel alive rather than static. When a player logs in at different times and sees dawn breaking or a storm rolling through, the world stops feeling like a collection of room descriptions and starts feeling like a place that exists independently of the player's actions.

This revised design uses **pure computation** instead of scheduled infrastructure, eliminating the DynamoDB hotspot, CloudWatch complexity, and per-look read overhead of the original design.

## Critical Analysis (Revised)

**No infrastructure required.** The new approach uses no CloudWatch Events, no scheduled Lambdas, and no Step Functions. Weather is computed on-demand from location coordinates and current timestamp. This eliminates the operational complexity and cost of the original design.

**No DynamoDB hotspot.** The WorldState singleton is eliminated. Weather is computed per-location using a deterministic noise function, so there's no single item receiving all reads.

**Zero per-look overhead.** Weather computation is O(1) with fast hash functions. No database calls are made for time or weather — it's all in-memory calculation.

**Weather drifts in real-time.** Using time as a dimension in the noise function means weather patterns move across the map at real-time speed, even when no players are online. A storm starting at coordinate (100, 100) will naturally drift toward (150, 120) over minutes.

**Day/night is global but time-based.** Unlike weather (which varies by location), day/night is computed globally from wall clock time. All players see the same time period. No storage needed — it's pure computation.

**Trade-off: Weather is local illusion.** If two players compare notes about the weather at coordinate (100, 100), they'll agree (determinism). But if Player A is at (100, 100) and Player B is at (500, 500), they experience different weather. This is acceptable for a MUD — players verify by looking themselves.

---

## Design Principles

**Pure computation, not storage.** Time and weather are computed from current timestamp and location coordinates. No database reads required in the hot path.

**Noise-based weather with drift.** Weather at location (x, y) at time t is a function: `noise(x, y, t)`. As t increases, the noise field shifts, causing weather patterns to drift across the map.

**Deterministic for consistency.** Same coordinates + same time = same weather. This ensures all players who look at the same location see the same conditions.

**Day/night from wall clock.** Time periods are computed from real-time. 4 hours real time = 1 full day/night cycle (60 minutes per period).

**Biome-aware descriptions.** Weather flavor text varies by biome — "rain in a forest" has different descriptions than "rain in a desert".

---

## Implementation

### Weather Module (`backend/aspects/weather.py`)

The weather system is a standalone module with:

```python
def get_time_period() -> str:
    """Get current period: dawn, day, dusk, night (from wall clock)."""

def get_weather_at(x: int, y: int, biome: str) -> Tuple[str, str]:
    """Get weather type and description for location."""

def add_weather_to_description(desc: str, x: int, y: int, biome: str) -> str:
    """Hook for Land.look() to append atmospheric details."""
```

### Noise Function

A multi-octave hash-based noise function provides deterministic pseudo-random values:

```python
def _noise(x: float, y: float, seed: int) -> float:
    """Hash-based noise: same input = same output."""
    # Multiple sine wave octaves with hash-based offsets
    # Returns value 0-1
```

### Time Periods

| Period | Duration | Description |
|--------|----------|-------------|
| dawn | 60 min | "Dawn light spreads across the sky." |
| day | 60 min | "Sunlight illuminates the area." |
| dusk | 60 min | "Long shadows stretch as the sun sets." |
| night | 60 min | "Darkness envelops the surroundings. Stars glitter overhead." |

Full cycle: 240 minutes (4 hours) real time.

### Weather Types

Weighted options for variety:
- `clear` (37.5%): Clear skies
- `rain` (25%): Rainfall
- `fog` (12.5%): Reduced visibility
- `storm` (12.5%): Thunder/lightning, strongest effect
- `snow` (12.5%): Cold weather, winter conditions

### Biome-Specific Descriptions

Each weather type has flavor text per biome. Example for `rain`:
- plains: "Rain falls steadily across the open ground."
- forest: "Rain patters on the canopy above, dripping through the leaves."
- desert: "A brief, unexpected drizzle falls, quickly evaporating."
- swamp: "Sheets of warm rain hammer the marsh."
- mountain: "Rain streams down the mountain slopes."

---

## Integration

### Land.look() Hook

The `look` command now appends atmospheric details:

```python
from .weather import add_weather_to_description

@player_command
def look(self) -> dict:
    room = self._current_room()
    # ... existing room generation ...
    
    # Add weather overlay
    coords = room.coordinates
    biome = room.data.get("biome", "unknown")
    desc = add_weather_to_description(desc, coords[0], coords[1], biome)
    
    return {"description": desc, ...}
```

### Response Example

```json
{
  "type": "look",
  "description": "Rolling hills stretch in every direction. Tall grass sways in the breeze. Dawn light spreads across the sky. Rain falls steadily across the open ground.",
  "coordinates": [100, 50, 0],
  "exits": ["north", "south", "east"],
  "biome": "plains"
}
```

---

## Cost Analysis

| Component | Original Design | Revised Design |
|-----------|-----------------|----------------|
| Scheduled Lambda | 1 (CloudWatch) | 0 |
| Step Functions | Per-tick execution | 0 |
| DynamoDB reads (look) | +1 per look | +0 |
| DynamoDB writes | Per weather change | 0 |
| Hotspot risk | WorldState entity | None |
| Infrastructure complexity | High | None |

**Estimated cost reduction:** Near-zero incremental cost. Weather is computed in-memory during existing Land.look() calls.

---

## Future Enhancements (Optional)

Once the base system is live, these could be added:

1. **Mechanical weather effects** — Storm reduces visibility for stealth checks, rain makes fire magic weaker, etc.
2. **Weather-based NPC behavior** — NPCs seek shelter during storms (read weather at their location)
3. **Player weather gear** — Cloaks that reduce weather penalties
4. **Weather forecasts** — A "forecast" command showing predicted weather at a location

---

## Files Changed

- **New:** `backend/aspects/weather.py` — Weather computation module
- **Modified:** `backend/aspects/land.py` — Added weather overlay in `look()`
- **New:** This design document (replaces original)

---

## Status

- ✅ **Designed** (this document)
- ✅ **Module created** (`weather.py`, `land.py` integration)
- 🔧 **Needs testing** (manual verification of output)
- ⏳ **Needs CI** (lint/tests)

---

*Revised 2026-02-21 to use noise-based computation instead of scheduled infrastructure.*