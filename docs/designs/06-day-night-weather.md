# Day/Night and Weather Cycle

## Overview

The Day/Night and Weather Cycle introduces a world clock and atmospheric conditions that affect gameplay across all aspects. A singleton WorldState entity tracks the current time period and weather, updated by a scheduled CloudWatch Events Lambda on a tick interval. Time and weather modify room descriptions, NPC behavior, visibility, and movement -- making the world feel alive and dynamic without requiring per-player state. All entities read from the same WorldState, ensuring consistency across the shared world.

## Design Principles

**Singleton world state, not per-player state.** Time and weather are global facts about the world. A single WorldState entity (with a well-known UUID) holds the canonical clock and weather. Any aspect that needs current conditions reads from this entity. This avoids fan-out writes and keeps the model simple.

**Explicit cross-aspect access.** When `Land.look()` needs the current weather, it loads `Entity(uuid=WORLD_STATE_UUID).aspect("Weather")` and reads `data["current_time"]` and `data["current_weather"]`. The dependency is visible in code.

**Lazy creation.** The WorldState entity and its Weather aspect are created on first access if they do not exist. The scheduled tick Lambda creates them if missing.

**Deterministic weather from seed.** Weather transitions use a seed-based progression so that the sequence is reproducible given the same starting seed. This aligns with the worldgen philosophy of determinism from coordinates/seeds.

**Each aspect owns its data.** The Weather aspect stores time/weather fields. It does not store biome data (that belongs to Land/worldgen). It does not store NPC schedules (NPCs read weather and decide locally).

## Aspect Data

### WorldState Entity (well-known UUID)

Stored in the **entity table**:

| Field | Type | Description |
|-------|------|-------------|
| uuid | str | Well-known UUID constant, e.g. `"00000000-0000-0000-0000-000000000001"` |
| name | str | `"WorldState"` |
| aspects | list | `["Weather"]` |
| primary_aspect | str | `"Weather"` |
| tick_delay | int | Seconds between weather ticks (default: 300 = 5 minutes) |

### Weather Aspect

Stored in the **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Description |
|-------|------|-------------|
| uuid | str | Same as WorldState entity UUID |
| current_tick | int | Monotonically increasing world tick counter |
| current_time | str | One of: `"dawn"`, `"day"`, `"dusk"`, `"night"` |
| time_in_period | int | Ticks elapsed in current time period |
| ticks_per_period | int | How many ticks each period lasts (default: 12, so a full day = 48 ticks) |
| current_weather | str | One of: `"clear"`, `"rain"`, `"fog"`, `"storm"`, `"snow"` |
| weather_duration | int | Ticks remaining for current weather before re-evaluation |
| weather_seed | int | Seed for deterministic weather progression |
| previous_weather | str | Weather before the current one (for transition descriptions) |

### Time Period Cycle

The four time periods cycle in order: `dawn` -> `day` -> `dusk` -> `night` -> `dawn` ...

Each period lasts `ticks_per_period` ticks. At default settings (12 ticks per period, 5 minutes per tick), a full day-night cycle takes 4 hours of real time.

### Weather Probability by Biome

Weather is global, but biome-specific modifiers adjust what players experience locally:

| Biome | Clear | Rain | Fog | Storm | Snow |
|-------|-------|------|-----|-------|------|
| plains | 0.40 | 0.25 | 0.15 | 0.15 | 0.05 |
| forest | 0.30 | 0.30 | 0.20 | 0.10 | 0.10 |
| desert | 0.70 | 0.05 | 0.05 | 0.15 | 0.05 |
| swamp | 0.15 | 0.30 | 0.35 | 0.10 | 0.10 |
| mountain_peak | 0.20 | 0.15 | 0.15 | 0.20 | 0.30 |
| misty_highlands | 0.15 | 0.20 | 0.40 | 0.15 | 0.10 |

The global weather state determines the base condition. Biome modifiers shift the probability: a `rain` event in the desert might present as `"a brief, unexpected drizzle"` while the same event in a swamp becomes `"sheets of warm rain hammer the marsh"`.

## Commands

### No direct player commands

Weather is not player-controlled. Players observe weather through `look` output and ambient messages. However, a query command is provided for convenience:

```python
@player_command
def time(self) -> dict:
    """Check the current time of day and weather conditions.

    Returns:
        dict with current time period, weather, and descriptive text.
    """
```

**Behavior:** Loads the WorldState entity, reads Weather aspect data, and returns a formatted description like `"It is dusk. A light rain falls steadily."` Includes the tick count for AI agents that want precise timing.

**Return format:**
```python
{
    "type": "time",
    "time_period": "dusk",
    "weather": "rain",
    "tick": 147,
    "description": "The sun sinks toward the horizon. A steady rain falls from grey clouds overhead."
}
```

This command lives on the Weather aspect class but is available to any entity with Weather in its aspects list. Since players do not have Weather as an aspect, this command is instead added to the Land aspect (where `look` and `move` already live) and reads the WorldState internally.

## Cross-Aspect Interactions

### Land.look() -- time and weather in descriptions

`Land.look()` is modified to query the WorldState entity and append time/weather context to room descriptions:

```python
# In Land.look(), after generating base description:
try:
    world_state = Entity(uuid=WORLD_STATE_UUID)
    weather = world_state.aspect("Weather")
    time_period = weather.data.get("current_time", "day")
    current_weather = weather.data.get("current_weather", "clear")
    biome = room.data.get("biome", "plains")

    time_desc = TIME_DESCRIPTIONS[time_period]
    weather_desc = get_weather_description(current_weather, biome)

    desc = desc + " " + time_desc + " " + weather_desc
except (KeyError, Exception):
    pass  # WorldState not yet created; show base description
```

**Time description examples:**
- dawn: `"The sky brightens with the first light of morning."`
- day: `"Sunlight illuminates the area."`
- dusk: `"Long shadows stretch across the ground as the sun sets."`
- night: `"Darkness envelops the surroundings. Stars glitter overhead."`

**Weather description examples (varies by biome):**
- rain + forest: `"Rain patters on the canopy above, dripping through the leaves."`
- fog + swamp: `"A thick fog clings to everything, limiting visibility to a few paces."`
- storm + mountain_peak: `"Thunder cracks against the peaks. Lightning illuminates the clouds."`
- snow + plains: `"Snowflakes drift across the open ground, dusting everything in white."`

### Land.look() -- visibility effects

During `night` or `fog`, the exits list may be reduced:

```python
if time_period == "night" and current_weather == "fog":
    # Only show 50% of exits (rounded up), minimum 1
    visible_count = max(1, (len(exits) + 1) // 2)
    visible_exits = exits[:visible_count]
    desc += " You can barely make out your surroundings."
elif time_period == "night":
    # Show all exits but note reduced visibility
    desc += " The darkness makes it hard to see far."
```

### Land.move() -- movement speed effects

Storms and heavy snow slow movement by adding a delay:

```python
if current_weather == "storm":
    # Storm slows movement -- add descriptive delay text
    result["weather_effect"] = "The storm batters you as you push forward."
elif current_weather == "snow" and biome not in ("desert", "swamp"):
    result["weather_effect"] = "Snow slows your progress."
```

No mechanical tick delay is imposed (that would require Step Functions integration for player commands, which is unnecessarily complex). The effect is narrative only, though future Combat integration could apply penalties.

### NPC.tick() -- behavior changes by time

NPCs check the WorldState to vary behavior:

```python
# In NPC._wander(), before deciding to move:
try:
    world_state = Entity(uuid=WORLD_STATE_UUID)
    weather = world_state.aspect("Weather")
    time_period = weather.data.get("current_time", "day")
except (KeyError, Exception):
    time_period = "day"

if time_period == "night":
    if self.data.get("behavior") == "guard":
        # Guards patrol more aggressively at night
        self._wander()  # Move every tick instead of 50% chance
        return
    elif self.data.get("nocturnal") is not True:
        # Non-nocturnal NPCs stay put at night
        return
```

**NPC nocturnal field:** NPCs can have `"nocturnal": True` in their data. Nocturnal NPCs are active at night and dormant during day. This is set during NPC creation.

### Inventory.examine() -- weather-affected item descriptions

Items with weather-reactive tags could show different descriptions:

```python
# If item has "weather_reactive" tag and weather is "rain":
if "weather_reactive" in item_tags and current_weather == "rain":
    desc += " It glistens with rainwater."
```

This is a minor enhancement and optional for initial implementation.

## Event Flow

### Scheduled Tick (CloudWatch Events -> Lambda)

```
CloudWatch Events Rule (every 5 minutes)
  -> weather_tick Lambda
    -> Load WorldState entity (WORLD_STATE_UUID)
    -> If not exists: create WorldState entity + Weather aspect with defaults
    -> Increment current_tick
    -> Advance time_in_period; if >= ticks_per_period, advance to next time period
    -> Decrement weather_duration; if <= 0, roll new weather from seed
    -> Save Weather aspect
    -> If time period changed:
      -> Broadcast time_change event to all connected entities
    -> If weather changed:
      -> Broadcast weather_change event to all connected entities
    -> Schedule next tick via entity.schedule_next_tick()
```

### Broadcast Events

**Time change broadcast:**
```python
# Query entity table for all entities with connection_id (GSI: by_connection)
# For each connected entity:
entity.push_event({
    "type": "time_change",
    "from": "day",
    "to": "dusk",
    "description": "The sun begins to set, casting the world in amber light."
})
```

**Weather change broadcast:**
```python
entity.push_event({
    "type": "weather_change",
    "from": "clear",
    "to": "rain",
    "description": "Dark clouds roll in and rain begins to fall."
})
```

### Weather Transition Logic

```python
@callable
def tick(self) -> dict:
    """Advance the world clock by one tick."""
    self.data["current_tick"] = self.data.get("current_tick", 0) + 1

    # Advance time period
    time_in_period = self.data.get("time_in_period", 0) + 1
    ticks_per_period = self.data.get("ticks_per_period", 12)

    if time_in_period >= ticks_per_period:
        time_in_period = 0
        periods = ["dawn", "day", "dusk", "night"]
        current = self.data.get("current_time", "day")
        idx = periods.index(current) if current in periods else 1
        self.data["current_time"] = periods[(idx + 1) % 4]
        # broadcast time change

    self.data["time_in_period"] = time_in_period

    # Advance weather
    duration = self.data.get("weather_duration", 0) - 1
    if duration <= 0:
        self._roll_new_weather()
    else:
        self.data["weather_duration"] = duration

    self._save()
    if self.entity:
        self.entity.schedule_next_tick()
```

### Weather Rolling

```python
def _roll_new_weather(self):
    """Deterministically select new weather from seed progression."""
    seed = self.data.get("weather_seed", 42)
    tick = self.data.get("current_tick", 0)

    # Advance seed
    combined = (seed * 6364136223846793005 + tick) & 0xFFFFFFFFFFFFFFFF
    weather_options = ["clear", "clear", "clear", "rain", "rain", "fog", "storm", "snow"]
    idx = combined % len(weather_options)

    self.data["previous_weather"] = self.data.get("current_weather", "clear")
    self.data["current_weather"] = weather_options[idx]
    self.data["weather_duration"] = 3 + (combined >> 8) % 6  # 3-8 ticks
    self.data["weather_seed"] = combined & 0xFFFFFFFF
```

## NPC Integration

### Time-dependent NPC behavior

| Behavior | Dawn | Day | Dusk | Night |
|----------|------|-----|------|-------|
| wander | Active, explores | Active, explores | Returns toward landmarks | Sleeps (no movement) |
| guard | Alert | Standard patrol | Alert | High alert (always moves) |
| merchant | Setting up shop | Active trading | Packing up | Closed (ignores players) |
| hermit | Meditating | Available | Available | Sleeps |

### Nocturnal NPCs

NPCs with `"nocturnal": True` reverse the day/night table: active at night, dormant during day. This enables creatures like bats, wolves, or shadow entities that only appear after dark.

### Weather-dependent NPC behavior

- During `storm`: all NPCs seek shelter (move toward the nearest landmark with a "shelter" tag if available, otherwise stay put).
- During `fog`: guard NPCs have reduced detection range (do not greet players unless player has been at the location for 2+ ticks).
- During `snow`: wanderer NPCs reduce movement probability from 50% to 20%.

### NPC dialogue changes

NPC greeting pools can include weather/time-specific lines:

```python
WEATHER_GREETINGS = {
    "guard": {
        "storm": ["Terrible night for patrol. Stay indoors if you can."],
        "night": ["Who goes there? Identify yourself!"],
    },
    "merchant": {
        "rain": ["Come under the awning! Browse my wares out of the rain."],
        "night": ["Shop's closed. Come back at dawn."],
    },
}
```

## AI Agent Considerations

### Reading world state

AI agents interact via the same WebSocket command interface as human players. The `time` command provides structured data:

```json
{
    "type": "time",
    "time_period": "night",
    "weather": "storm",
    "tick": 247,
    "description": "..."
}
```

Agents can use `tick` as a numeric reference for planning. The `time_period` and `weather` fields are machine-readable enums suitable for decision trees.

### Planning around time

An AI agent might:
- Avoid travel during storms (check weather before issuing `move`).
- Wait for dawn before entering a dungeon (fewer nocturnal enemies during day).
- Seek out nocturnal NPCs at night for unique dialogue/quests.
- Time merchant interactions for daytime hours.

### No special API needed

Because the `time` command returns structured data and weather effects are reflected in `look` output, AI agents need no special integration. They read the same events human players receive.

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/weather.py` | Weather aspect class with `tick()`, `time` command, weather rolling logic |
| `backend/aspects/tests/test_weather.py` | Unit tests for weather tick, time cycling, weather transitions |

### Files to modify

| File | Change |
|------|--------|
| `backend/aspects/land.py` | Modify `look()` and `move()` to query WorldState for time/weather descriptions |
| `backend/aspects/npc.py` | Add time/weather awareness to `tick()`, `_wander()`, `_guard()`, `_check_for_players()` |
| `backend/serverless.yml` | Add `weather` Lambda function with SNS filter for `Weather` aspect; add CloudWatch Events rule for scheduled tick |
| `backend/aspects/worldgen/describe.py` | Add time/weather parameters to `_build_llm_prompt()` for richer descriptions |

### Infrastructure additions (serverless.yml)

```yaml
weatherTick:
  handler: aspects/weather.handler
  events:
    - sns:
        arn: "arn:aws:sns:#{AWS::Region}:#{AWS::AccountId}:${self:custom.topics.thingName}"
        filterPolicy:
          aspect:
            - Weather
    - schedule:
        rate: rate(5 minutes)
        input:
          source: "scheduled"
          action: "tick_world"
```

### Implementation order

1. Create `weather.py` with Weather aspect, WorldState constant UUID, tick logic, time command.
2. Add scheduled Lambda trigger in serverless.yml.
3. Modify `Land.look()` to include time/weather descriptions.
4. Modify `NPC.tick()` for time-aware behavior.
5. Write tests for weather transitions, time cycling, biome-weather interaction.

## Open Questions

1. **Should weather be truly global or regional?** A single WorldState keeps things simple, but a large world might want different weather in different regions. One approach: keep global weather as the base, use biome modifiers for local flavor. A future enhancement could add regional weather entities.

2. **How long should a full day cycle be?** The default of 4 hours real time (48 ticks at 5 min each) may be too long or too short. This is configurable via `ticks_per_period` and the CloudWatch schedule rate, but a good default matters for player experience.

3. **Should visibility reduction be mechanical or narrative?** Currently, fog/night only adds descriptive text about reduced visibility but does not actually hide exits. Hiding exits could be confusing (especially for new players) but adds gameplay depth. A middle ground: show all exits but mark some as "obscured" so players know they exist but cannot see what lies beyond.

4. **Do we need a light source item?** Torches or lanterns that counteract night visibility penalties would add depth but require Inventory integration. Defer to a future Crafting system?

5. **CloudWatch Events cost.** A rule firing every 5 minutes is ~8,640 invocations/month, well within free tier. But if tick_delay is reduced for faster cycles, costs increase linearly.

6. **Connected entity broadcast fan-out.** Broadcasting time/weather changes to all connected entities requires scanning the `by_connection` GSI. With many connected players, this could hit DynamoDB read limits. Consider batching or using a dedicated broadcast mechanism.
