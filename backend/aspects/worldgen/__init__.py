"""Pluggable world generation system.

Routes room generation to the appropriate generator based on biome data,
applies landmark influence, and generates descriptions.

Usage from Land:
    from .worldgen import generate_room
    blueprint = generate_room(coordinates, context)
"""

from __future__ import annotations

import logging
from typing import Dict, Tuple

from .base import GenerationContext, RoomBlueprint
from .biome import get_biome
from .describe import generate_room_description
from .dungeon import DungeonGenerator
from .landmarks import check_landmark
from .overworld import OverworldGenerator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Generator registry
# ---------------------------------------------------------------------------

_GENERATORS: Dict[str, object] = {
    "overworld": OverworldGenerator(),
    "dungeon": DungeonGenerator(),
}


def register_generator(name: str, generator: object) -> None:
    """Register a new generator for a biome category."""
    _GENERATORS[name] = generator


def _get_generator(name: str):
    """Look up a generator by name, falling back to overworld."""
    gen = _GENERATORS.get(name)
    if gen is None:
        logger.warning(f"No generator for '{name}', falling back to overworld")
        gen = _GENERATORS["overworld"]
    return gen


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_room(
    coordinates: Tuple[int, int, int],
    context: GenerationContext,
) -> RoomBlueprint:
    """Generate a complete room blueprint for the given coordinates.

    1. Compute biome from noise layers
    2. Select generator based on biome
    3. Generate exits, terrain, tags, distant features
    4. Check for landmark influence
    5. Generate description (LLM or fallback)

    Args:
        coordinates: (x, y, z) grid coordinates.
        context: What we know about where the player came from, neighbors, etc.

    Returns:
        A RoomBlueprint with everything needed to materialize the room.
    """
    # Step 1: biome
    biome_data = get_biome(*coordinates)
    context.biome_data = biome_data

    # Step 2: select generator
    generator = _get_generator(biome_data.generator_name)

    # Step 3: generate blueprint
    blueprint = generator.generate(coordinates, context)

    # Step 4: landmark influence
    landmark = check_landmark(*coordinates)
    if landmark:
        blueprint.landmark = landmark.description_modifier

        # Add landmark terrain entities
        for terrain_spec in landmark.terrain_additions:
            if terrain_spec not in blueprint.terrain:
                blueprint.terrain.append(terrain_spec)

        # Biome override (for rooms near landmark center)
        if landmark.biome_override and landmark.center == coordinates:
            blueprint.biome = landmark.biome_override

        logger.debug(f"Landmark '{landmark.name}' influences {coordinates}")

    # Step 5: description
    blueprint.description = generate_room_description(blueprint, context)

    return blueprint
