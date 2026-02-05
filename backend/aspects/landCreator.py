import logging
import random

from .handler import lambdaHandler
from .land import Land
from .location import Location
from .thing import callable


class LandCreator(Location):
    "This entity creates new exits and moves"

    @callable
    def create(self):
        loc_uuid = Land.by_coordinates((0, 0, 0))
        super().create()
        self.location = loc_uuid
        self.tick()

    @callable
    def tick(self):
        # Get a list of exits in the location I'm in
        directions = {
            "north": "south",
            "south": "north",
            "west": "east",
            "east": "west",
        }
        loc = Land(self.location, tid=self.tid)
        # Randomly pick a direction - n, s, e, w
        chosen_exit = random.choice(list(directions.keys()))
        # If that exit already exists, take it
        if chosen_exit in loc.exits:
            self.move(loc.uuid, loc.exits[chosen_exit])
        # Otherwise, create a new exit with no land
        else:
            new_loc = Land(uuid=loc.by_direction(chosen_exit))
            new_loc.add_exit(directions[chosen_exit], loc.uuid)
            loc.add_exit(chosen_exit, new_loc.uuid)
            logging.info(
                "I created a new piece of land, {} of here".format(chosen_exit)
            )
        self.schedule_next_tick()


handler = lambdaHandler(LandCreator)
