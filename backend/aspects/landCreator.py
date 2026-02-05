"""LandCreator module for creating new exits and moving in the land aspect."""

import logging
import random

from .handler import lambdaHandler
from .land import Land
from .location import Location
from .thing import callable


class LandCreator(Location):
    """Entity that creates new exits and moves in the land aspect."""

    @callable
    def create(self):
        """Create a new land location and perform initial tick."""
        loc_uuid = Land.by_coordinates((0, 0, 0))
        super().create()
        self.location = loc_uuid
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
            logging.info(
                "I created a new piece of land, {} of here".format(chosen_exit)
            )
        self.schedule_next_tick()


handler = lambdaHandler(LandCreator)
