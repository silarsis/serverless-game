"""Lazy landmark discovery system.

Landmarks are NOT pre-placed.  They're implicit in the coordinate space,
discovered via a coordinate-seeded hash function.  The same coordinates
always produce the same landmark (or no landmark).

Each landmark has an influence radius -- nearby rooms get thematic
modifications to their descriptions and terrain.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Landmark definitions
# ---------------------------------------------------------------------------

# Rarity: roughly 1 landmark per LANDMARK_RARITY tiles scanned.
# Since we check in a radius, effective density is higher than this.
LANDMARK_RARITY = 150

# Maximum influence radius of any landmark (used to bound the search area).
MAX_LANDMARK_RADIUS = 5


@dataclass
class Landmark:
    """A discovered landmark at specific coordinates."""

    name: str
    landmark_type: str  # "ruin", "nature", "settlement", "mystical", "danger"
    center: Tuple[int, int, int]
    radius: int
    description_modifier: str  # added to description hints
    terrain_additions: List[dict]  # extra terrain entities near the landmark
    biome_override: Optional[str] = None  # if set, overrides biome near center


# The catalog -- extend this to add new landmark types.
# Each entry is a template; the actual landmark is placed at specific coords.
LANDMARK_CATALOG = [
    {
        "name": "a crumbling watchtower",
        "type": "ruin",
        "radius": 3,
        "biome_override": "hilltop_ruins",
        "description_modifier": "near the ruins of an old watchtower",
        "terrain": [
            {
                "name": "a pile of ancient bricks",
                "type": "structure",
                "description": "Weathered bricks from a collapsed structure.",
                "weight": 999,
                "tags": ["stone", "ruins", "ancient"],
            },
        ],
    },
    {
        "name": "a crystal spring",
        "type": "nature",
        "radius": 2,
        "biome_override": None,
        "description_modifier": "near a spring of clear, sparkling water",
        "terrain": [
            {
                "name": "a crystal-clear pool",
                "type": "water",
                "description": "Water so clear you can see every pebble on the bottom.",
                "weight": 999,
                "tags": ["water", "clean", "magical"],
            },
        ],
    },
    {
        "name": "a traders' camp",
        "type": "settlement",
        "radius": 4,
        "biome_override": "settlement_outskirts",
        "description_modifier": "near a well-used traders' camp",
        "terrain": [
            {
                "name": "a fire pit",
                "type": "structure",
                "description": "A ring of stones around old ashes. Recently used.",
                "weight": 999,
                "tags": ["fire", "civilization", "camp"],
            },
        ],
    },
    {
        "name": "an ancient standing stone",
        "type": "mystical",
        "radius": 2,
        "biome_override": None,
        "description_modifier": "in the shadow of a towering standing stone",
        "terrain": [
            {
                "name": "a monolith of dark stone",
                "type": "structure",
                "description": "A single upright stone, taller than two people, "
                "carved with spiralling symbols.",
                "weight": 999,
                "tags": ["stone", "ancient", "mystical", "landmark"],
            },
        ],
    },
    {
        "name": "a collapsed mine entrance",
        "type": "danger",
        "radius": 3,
        "biome_override": None,
        "description_modifier": "near the gaping mouth of an old mine",
        "terrain": [
            {
                "name": "a rotting mine cart",
                "type": "structure",
                "description": "A wooden cart on rusted rails, half-collapsed.",
                "weight": 100,
                "tags": ["wood", "metal", "ruins", "civilization"],
            },
        ],
    },
    {
        "name": "a forgotten shrine",
        "type": "mystical",
        "radius": 2,
        "biome_override": None,
        "description_modifier": "near the remains of a small roadside shrine",
        "terrain": [
            {
                "name": "a worn stone altar",
                "type": "structure",
                "description": "A low stone altar, smoothed by countless hands.",
                "weight": 999,
                "tags": ["stone", "ancient", "mystical", "structure"],
            },
        ],
    },
    {
        "name": "a great hollow tree",
        "type": "nature",
        "radius": 2,
        "biome_override": None,
        "description_modifier": "beside a massive hollow tree",
        "terrain": [
            {
                "name": "a cavernous tree trunk",
                "type": "tree",
                "description": "The trunk is wide enough to shelter in, "
                "its interior dark and dry.",
                "weight": 999,
                "tags": ["tree", "shelter", "ancient", "wood"],
            },
        ],
    },
    {
        "name": "a stone bridge",
        "type": "ruin",
        "radius": 2,
        "biome_override": None,
        "description_modifier": "near an old stone bridge spanning a dry channel",
        "terrain": [
            {
                "name": "a moss-covered bridge",
                "type": "structure",
                "description": "Arched stonework, still solid despite its age.",
                "weight": 999,
                "tags": ["stone", "structure", "ancient", "bridge"],
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# Discovery functions
# ---------------------------------------------------------------------------


def _landmark_seed(x: int, y: int, z: int) -> int:
    """Deterministic seed for landmark checks."""
    h = hashlib.md5(f"landmark:{x},{y},{z}".encode()).hexdigest()
    return int(h[:8], 16)


def _is_landmark_center(x: int, y: int, z: int) -> bool:
    """Check if these coordinates are a landmark center."""
    return _landmark_seed(x, y, z) % LANDMARK_RARITY == 0


def _landmark_at(x: int, y: int, z: int) -> Optional[Landmark]:
    """If (x, y, z) is a landmark center, return the Landmark."""
    if not _is_landmark_center(x, y, z):
        return None

    seed = _landmark_seed(x, y, z)
    entry = LANDMARK_CATALOG[seed % len(LANDMARK_CATALOG)]

    return Landmark(
        name=entry["name"],
        landmark_type=entry["type"],
        center=(x, y, z),
        radius=entry["radius"],
        description_modifier=entry["description_modifier"],
        terrain_additions=entry["terrain"],
        biome_override=entry.get("biome_override"),
    )


def check_landmark(x: int, y: int, z: int) -> Optional[Landmark]:
    """Check if coordinates are at or near a landmark.

    Scans a square of side 2*MAX_LANDMARK_RADIUS+1 centered on (x,y,z).
    Returns the closest landmark whose influence reaches here, or None.

    This is pure math -- no DB queries.  Same coords always give same result.
    """
    # Check if WE are a landmark center first (fast path)
    direct = _landmark_at(x, y, z)
    if direct:
        return direct

    # Scan nearby for landmark centers whose radius reaches us
    best: Optional[Landmark] = None
    best_dist = MAX_LANDMARK_RADIUS + 1

    for dx in range(-MAX_LANDMARK_RADIUS, MAX_LANDMARK_RADIUS + 1):
        for dy in range(-MAX_LANDMARK_RADIUS, MAX_LANDMARK_RADIUS + 1):
            if dx == 0 and dy == 0:
                continue
            cx, cy = x + dx, y + dy
            lm = _landmark_at(cx, cy, z)
            if lm is None:
                continue
            dist = abs(dx) + abs(dy)  # Manhattan distance
            if dist <= lm.radius and dist < best_dist:
                best = lm
                best_dist = dist

    return best
