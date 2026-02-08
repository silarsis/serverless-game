"""Dungeon/cave generator stub.

Handles underground biomes (z < 0).  Currently delegates most logic
to a simplified version of the overworld generator.  This is the
extension point for cave systems, dungeons, mines, etc.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple

from .base import GenerationContext, RoomBlueprint

# Underground terrain
_CAVE_TERRAIN = [
    {
        "name": "a stalagmite",
        "type": "rock",
        "description": "A cone of mineral deposits rising from the floor.",
        "weight": 999,
        "tags": ["rock", "cave"],
    },
    {
        "name": "a dripping ceiling",
        "type": "terrain",
        "description": "Water seeps through cracks above, forming slow drops.",
        "weight": 999,
        "tags": ["water", "cave", "damp"],
    },
    {
        "name": "a pile of loose rubble",
        "type": "rock",
        "description": "Broken stone, as if something collapsed here.",
        "weight": 999,
        "tags": ["rock", "rubble", "dangerous"],
    },
    {
        "name": "a patch of cave moss",
        "type": "vegetation",
        "description": "Soft, pale moss clings to the damp rock.",
        "weight": 1,
        "tags": ["vegetation", "cave", "damp"],
    },
    {
        "name": "a narrow crack in the wall",
        "type": "terrain",
        "description": "A dark fissure. Cool air flows from within.",
        "weight": 999,
        "tags": ["crack", "air", "cave"],
    },
]

_COORD_DELTAS = {
    "north": (0, 1, 0),
    "south": (0, -1, 0),
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "up": (0, 0, 1),
    "down": (0, 0, -1),
}
_OPPOSITE = {
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
    "up": "down",
    "down": "up",
}


def _coord_seed(x: int, y: int, z: int) -> int:
    h = hashlib.md5(f"dungeon:{x},{y},{z}".encode()).hexdigest()
    return int(h[:8], 16)


def _dest_coords(origin: Tuple[int, int, int], d: str) -> Tuple[int, int, int]:
    dx, dy, dz = _COORD_DELTAS[d]
    return (origin[0] + dx, origin[1] + dy, origin[2] + dz)


class DungeonGenerator:
    """Generator for underground biomes.

    Caves are more restrictive than the overworld -- typically 2-3 exits,
    with a chance of going deeper (down) or returning to surface (up).
    """

    def generate(
        self,
        coords: Tuple[int, int, int],
        context: GenerationContext,
    ) -> RoomBlueprint:
        seed = _coord_seed(*coords)
        biome = context.biome_data.biome_name if context.biome_data else "shallow_cave"

        # --- Exits: 2-3, always including way back ---
        exits = self._generate_exits(coords, seed, context)

        # --- Terrain: 1-2 cave features ---
        count = 1 + (seed % 2)
        terrain = []
        available = list(_CAVE_TERRAIN)
        for i in range(min(count, len(available))):
            idx = (seed + i * 6311) % len(available)
            terrain.append(available.pop(idx))

        # --- Tags ---
        tags = ["underground", "dark", "damp", "echoing"]
        if biome == "crystal_cavern":
            tags.extend(["glowing", "mystical"])
        if biome == "underground_river":
            tags.extend(["water", "rushing"])

        hint_parts = [biome.replace("_", " ")]
        if context.came_from_biome:
            hint_parts.append(f"descended from {context.came_from_biome}")

        return RoomBlueprint(
            exits=exits,
            biome=biome,
            terrain=terrain,
            description_hint="; ".join(hint_parts),
            scale="cramped" if seed % 3 != 0 else "room",
            tags=tags,
            distant_features=[],  # can't see far underground
        )

    def _generate_exits(
        self,
        coords: Tuple[int, int, int],
        seed: int,
        context: GenerationContext,
    ) -> Dict[str, Tuple[int, int, int]]:
        """Generate cave exits -- typically 2-3."""
        cardinals = ["north", "south", "east", "west"]

        # Forced: reciprocal exits from existing neighbors
        forced: set = set()
        for direction, info in context.neighbors.items():
            if info.get("has_exit_to_us"):
                forced.add(direction)

        # Force the way back
        if context.came_from:
            for d in cardinals + ["up", "down"]:
                if _dest_coords(coords, d) == context.came_from:
                    forced.add(d)
                    break

        selected = set(forced)

        # Add 1-2 more random cardinal exits
        remaining = [d for d in cardinals if d not in selected]
        remaining.sort(key=lambda d: (seed + hash(d)) % 1000)
        target = 2 + (seed % 2)  # 2-3 total
        for d in remaining:
            if len(selected) >= target:
                break
            selected.add(d)

        # Chance of up/down
        if (seed >> 12) % 3 == 0:
            if coords[2] < -1:  # deep enough for further descent
                selected.add("down")
            if coords[2] < 0:  # can always go up if underground
                selected.add("up")

        exits = {}
        for d in selected:
            exits[d] = _dest_coords(coords, d)
        return exits
