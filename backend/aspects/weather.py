"""
Weather System - Noise-based, tickless weather with real-time drift.

This module provides weather computation based on spatial noise, allowing
weather systems (storms, rain, fog) to drift across the map in real-time
without any scheduled infrastructure (CloudWatch, Step Functions).

The weather at any location is a pure function of:
- Location coordinates (x, y)
- Current timestamp (real-time)
- A seed for the location

This means:
- Weather is deterministic: same coords + time = same weather
- No database reads needed (computed on-demand)
- Weather "moves" as time progresses
- Zero infrastructure cost
"""

import hashlib
import math
import time
from typing import Tuple

# Configuration
DAY_LENGTH_MINUTES = 240  # 4 hours real time = 1 full day/night cycle
TIME_PERIODS = ["dawn", "day", "dusk", "night"]

# Weather types with weights (for noise -> weather mapping)
WEATHER_OPTIONS = ["clear", "clear", "clear", "rain", "rain", "fog", "storm", "snow"]

# Time period descriptions (appended to room descriptions)
TIME_DESCRIPTIONS = {
    "dawn": "Dawn light spreads across the sky.",
    "day": "Sunlight illuminates the area.",
    "dusk": "Long shadows stretch as the sun sets.",
    "night": "Darkness envelops the surroundings. Stars glitter overhead.",
}

# Weather descriptions by biome
WEATHER_DESCRIPTIONS = {
    "clear": {
        "plains": "The sky is clear and vast.",
        "forest": "Sunlight filters through the canopy.",
        "desert": "The sun beats down without mercy.",
        "swamp": "The stale air hangs heavy and still.",
        "mountain": "Crisp, clear air dominates the peaks.",
        "default": "The weather is clear.",
    },
    "rain": {
        "plains": "Rain falls steadily across the open ground.",
        "forest": "Rain patters on the canopy above, dripping through the leaves.",
        "desert": "A brief, unexpected drizzle falls, quickly evaporating.",
        "swamp": "Sheets of warm rain hammer the marsh.",
        "mountain": "Rain streams down the mountain slopes.",
        "default": "Rain falls from the sky.",
    },
    "fog": {
        "plains": "A thick fog rolls in, limiting visibility.",
        "forest": "A thick fog clings to everything, limiting visibility to a few paces.",
        "desert": "A surreal fog rises from the hot sand.",
        "swamp": "A thick fog clings to everything, limiting visibility to a few paces.",
        "mountain": "Clouds of fog swirl around the peaks.",
        "default": "A thick fog surrounds you.",
    },
    "storm": {
        "plains": "Thunder rumbles across the open plains. Lightning flashes in the distance.",
        "forest": "A fierce storm rattles the trees. Branches sway ominously.",
        "desert": "A sandstorm sweeps across the desert, biting grit into every corner.",
        "swamp": "Thunder cracks overhead. Lightning illuminates the clouds.",
        "mountain": "Thunder cracks against the peaks. Lightning illuminates the clouds.",
        "default": "A violent storm rages around you.",
    },
    "snow": {
        "plains": "Snowflakes drift across the open ground, dusting everything in white.",
        "forest": "Snow accumulates on branches, creating a winter wonderland.",
        "desert": "Snow dusts the sand, an surreal sight.",
        "swamp": "Snow blankets the marsh, freezing the stagnant water.",
        "mountain": "Snow piles deep on the mountain trails.",
        "default": "Snow falls silently from the sky.",
    },
}


def _noise(x: float, y: float, seed: int) -> float:
    """
    Simple hash-based noise function.

    Uses a combination of sine waves with hash-based phase offsets to create
    a pseudo-random but deterministic noise pattern.

    Args:
        x, y: Coordinates
        seed: Location seed for determinism

    Returns:
        Value between 0 and 1
    """
    # Multiple octaves of sine waves with hash-based offsets
    result = 0.0
    amplitude = 1.0
    frequency = 1.0

    for octave in range(3):
        # Hash-based offset for this octave
        h = hashlib.md5(f"{seed},{octave},{x},{y}".encode()).hexdigest()
        offset_x = int(h[:8], 16) / 0xFFFFFFFF
        offset_y = int(h[8:16], 16) / 0xFFFFFFFF

        result += amplitude * (
            0.5
            + 0.5
            * math.sin(frequency * x + offset_x * 6.28)
            * math.cos(frequency * y + offset_y * 6.28)
        )

        amplitude *= 0.5
        frequency *= 2.0

    # Normalize to 0-1
    return (result / 1.75) % 1.0


def _get_location_seed(x: int, y: int) -> int:
    """Get a deterministic seed for a location."""
    h = hashlib.md5(f"weather:{x},{y}".encode()).hexdigest()
    return int(h[:8], 16)


def get_time_period() -> str:
    """
    Get the current time period based on wall clock time.

    4 hours real time = 1 game day (60 min per period)

    Returns:
        One of: "dawn", "day", "dusk", "night"
    """
    epoch_minutes = int(time.time() // 60)
    day_minutes = epoch_minutes % DAY_LENGTH_MINUTES
    period_index = day_minutes // (DAY_LENGTH_MINUTES // 4)
    return TIME_PERIODS[period_index]


def get_weather_at(x: int, y: int, biome: str = "default") -> Tuple[str, str]:
    """
    Get weather for a specific location at the current time.

    Uses spatial noise to compute weather, with time as a dimension
    so weather patterns "drift" in real-time.

    Args:
        x, y: Location coordinates
        biome: Biome for flavor text selection

    Returns:
        Tuple of (weather_type, description)
    """
    # Location seed
    seed = _get_location_seed(x, y)

    # Current time in "ticks" (every 5 minutes = one tick)
    tick = int(time.time() // 300)

    # Apply time as drift - shift the noise field over time
    # Using a slow drift rate so weather systems move realistically
    drift_factor = tick / 1000.0  # Full cycle over ~8 hours

    # Compute noise at this location+time
    noise_value = _noise(x * 0.1, y * 0.1 + drift_factor, seed)

    # Map to weather type
    weather_idx = int(noise_value * len(WEATHER_OPTIONS)) % len(WEATHER_OPTIONS)
    weather = WEATHER_OPTIONS[weather_idx]

    # Get description for this weather + biome
    biome_key = biome if biome in WEATHER_DESCRIPTIONS.get(weather, {}) else "default"
    description = WEATHER_DESCRIPTIONS.get(weather, {}).get(
        biome_key, WEATHER_DESCRIPTIONS[weather]["default"]
    )

    return weather, description


def get_time_description() -> str:
    """Get the description for the current time period."""
    return TIME_DESCRIPTIONS.get(get_time_period(), "")


# Integration hook for Land.look()
def add_weather_to_description(description: str, x: int, y: int, biome: str) -> str:
    """
    Add time and weather flavor text to a room description.

    Call this from Land.look() to append atmospheric details.

    Args:
        description: Current room description
        x, y: Room coordinates
        biome: Room biome

    Returns:
        Description with time/weather appended
    """
    time_desc = get_time_description()
    weather, weather_desc = get_weather_at(x, y, biome)

    # Append atmosphere
    parts = [description]
    if time_desc:
        parts.append(time_desc)
    if weather_desc:
        parts.append(weather_desc)

    return " ".join(parts)
