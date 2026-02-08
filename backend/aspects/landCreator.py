"""LandCreator module for creating new exits and moving in the land aspect.

Enhanced to use the pluggable worldgen system for room generation.
"""

import logging
import random

from .handler import lambdaHandler
from .land import Land
from .thing import Aspect, Entity, callable

logger = logging.getLogger(__name__)


class LandCreator(Aspect):
    """Entity that explores and creates new land tiles.

    Uses the Land aspect table to read room exits and coordinates,
    but the LandCreator's own data (minimal) lives on LOCATION_TABLE.
    """

    _tableName = "LOCATION_TABLE"

    @callable
    def create(self):
        """Create a new land location and perform initial tick."""
        loc_uuid = Land.by_coordinates((0, 0, 0))
        if self.entity:
            self.entity.location = loc_uuid
        self._save()
        self.tick()

    @callable
    def tick(self):
        """Perform a movement or create new land exit if needed."""
        directions = {
            "north": "south",
            "south": "north",
            "west": "east",
            "east": "west",
        }
        loc_uuid = self.entity.location if self.entity else None
        if not loc_uuid:
            return

        loc = Land(uuid=loc_uuid)
        chosen_exit = random.choice(list(directions.keys()))
        if chosen_exit in loc.exits:
            # Move to existing exit
            if self.entity:
                self.entity.location = loc.exits[chosen_exit]
        else:
            new_loc = Land(uuid=loc.by_direction(chosen_exit))
            new_loc.add_exit(directions[chosen_exit], loc.uuid)
            loc.add_exit(chosen_exit, new_loc.uuid)

            # Generate room via worldgen if not already generated
            if not new_loc.data.get("generated"):
                try:
                    from .worldgen import generate_room
                    from .worldgen.base import GenerationContext

                    context = GenerationContext(
                        came_from=loc.coordinates,
                        came_from_description=loc.description,
                        came_from_biome=loc.data.get("biome"),
                    )
                    blueprint = generate_room(new_loc.coordinates, context)

                    # Apply description and metadata
                    new_loc.data["description"] = blueprint.description
                    new_loc.data["biome"] = blueprint.biome
                    new_loc.data["scale"] = blueprint.scale
                    new_loc.data["tags"] = blueprint.tags
                    new_loc.data["distant_features"] = blueprint.distant_features
                    if blueprint.landmark:
                        new_loc.data["landmark"] = blueprint.landmark
                    new_loc.data["generated"] = True
                    new_loc._save()

                    # Create terrain entities
                    for terrain_spec in blueprint.terrain:
                        Land._create_terrain_entity(new_loc, terrain_spec)

                except Exception as e:
                    logger.warning(f"Worldgen failed for LandCreator: {e}")
                    # Fallback: at least set a basic description
                    from .description_generator import generate_description

                    neighbors = []
                    if loc.description:
                        neighbors.append(loc.description)
                    new_loc.description = generate_description(
                        new_loc.coordinates,
                        neighbor_descriptions=neighbors,
                    )

            logging.info("I created a new piece of land, {} of here".format(chosen_exit))

        if self.entity:
            self.entity.schedule_next_tick()


handler = lambdaHandler(Entity)
