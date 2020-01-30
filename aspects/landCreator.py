from aspects.handler import lambdaHandler
from aspects.location import Location
from aspects.land import Land
import random
import logging


class LandCreator(Location):
    " This entity creates new exits and moves "
    @callable
    def create(self):
        loc_uuid = Land.by_coordinates((0, 0, 0))
        super().create()
        self.location = loc_uuid

    @callable
    def tick(self):
        # Get a list of exits in the location I'm in
        directions = {
            'north': 'south',
            'south': 'north',
            'west': 'east',
            'east': 'west'
        }
        loc = Land(self.location, tid=self.tid)
        # Randomly pick a direction - n, s, e, w
        exit = random.choice(list(directions.keys()))
        # If that exit already exists, take it
        if exit in loc.exits:
            self.move(loc.uuid, loc.exits[exit])
        # Otherwise, create a new exit with no land
        else:
            new_loc = Land(uuid=loc.by_direction(exit))
            new_loc.add_exit(directions[exit], loc.uuid)
            loc.add_exit(exit, new_loc.uuid)
            logging.info("I created a new piece of land, {} of here".format(exit))
        self.schedule_next_tick()


handler = lambdaHandler(LandCreator)
