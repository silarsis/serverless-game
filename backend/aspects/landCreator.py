"""LandCreator module for creating new exits and moving in the land aspect.

Enhanced with LLM-powered room descriptions and item placement.
"""

import logging
import random

from .description_generator import generate_description
from .handler import lambdaHandler
from .land import Land
from .location import Location
from .thing import callable

logger = logging.getLogger(__name__)

# Items that can be placed in the world during creation
PLACEABLE_ITEMS = [
    {
        "name": "a smooth stone",
        "description": "A small, unusually smooth stone. It fits perfectly in your palm.",
    },
    {
        "name": "a rusty key",
        "description": "An old key, covered in rust. It might still open something.",
    },
    {
        "name": "a torn map fragment",
        "description": "A scrap of parchment with faded markings. Part of a larger map.",
    },
    {
        "name": "a glowing mushroom",
        "description": "A small mushroom that emits a faint blue glow.",
    },
    {
        "name": "a wooden figurine",
        "description": "A crudely carved wooden figure. It might represent a person.",
    },
    {
        "name": "a bird feather",
        "description": "A large, colorful feather. It shimmers in the light.",
    },
    {
        "name": "a clay pot",
        "description": "A small clay pot, chipped but intact. Something rattles inside.",
    },
    {
        "name": "a copper coin",
        "description": "An old coin with an unfamiliar face stamped on it.",
    },
]

# Chance of placing an item when creating new land (0.0 to 1.0)
ITEM_PLACEMENT_CHANCE = 0.15


class LandCreator(Location):
    """Entity that creates new exits, generates descriptions, and places items."""

    @callable
    def create(self):
        """Create a new land location and perform initial tick."""
        loc_uuid = Land.by_coordinates((0, 0, 0))
        super().create()
        self.location = loc_uuid

        # Generate description for origin if missing
        origin = Land(uuid=loc_uuid)
        if not origin.description:
            origin.description = generate_description((0, 0, 0))

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
        loc = Land(self.location, tid=self.tid)
        chosen_exit = random.choice(list(directions.keys()))
        if chosen_exit in loc.exits:
            self.move(loc.uuid, loc.exits[chosen_exit])
        else:
            new_loc = Land(uuid=loc.by_direction(chosen_exit))
            new_loc.add_exit(directions[chosen_exit], loc.uuid)
            loc.add_exit(chosen_exit, new_loc.uuid)

            # Generate LLM description for the new land
            self._generate_land_description(new_loc, loc)

            # Maybe place an item
            self._maybe_place_item(new_loc)

            logger.info("Created new land %s of here at %s", chosen_exit, new_loc.coordinates)

        self.schedule_next_tick()

    def _generate_land_description(self, new_land: Land, from_land: Land):
        """Generate an LLM description for newly created land."""
        neighbors = []
        if from_land.description:
            neighbors.append(from_land.description)

        for direction, dest_uuid in from_land.exits.items():
            try:
                neighbor = Land(uuid=dest_uuid)
                if neighbor.description:
                    neighbors.append(neighbor.description)
            except KeyError:
                continue
            if len(neighbors) >= 3:
                break

        description = generate_description(
            new_land.coordinates,
            neighbor_descriptions=neighbors,
        )
        new_land.description = description

    def _maybe_place_item(self, land: Land):
        """Randomly place an item in the new land tile."""
        if random.random() > ITEM_PLACEMENT_CHANCE:
            return

        item_template = random.choice(PLACEABLE_ITEMS)
        try:
            from .inventory import Inventory

            creator = Inventory(uuid=self.uuid)
            old_loc = creator.location
            creator.location = land.uuid
            creator.create_item(
                name=item_template["name"],
                description=item_template["description"],
            )
            creator.location = old_loc
            logger.info("Placed item '%s' at %s", item_template["name"], land.coordinates)
        except Exception as e:
            logger.debug(f"Could not place item: {e}")


handler = lambdaHandler(LandCreator)
