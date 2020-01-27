from handler import lambdaHandler
from location import Location
import random
import logging


class LandCreator(Location):
    " This entity creates new exits and moves "
    @callable
    def create(self):
        # Randomly assign myself a starting position
        super().create()

    @callable
    def tick(self):
        # Get a list of exits in the location I'm in
        directions = {
            'north': 'south',
            'south': 'north',
            'west': 'east',
            'east': 'west'
        }
        for loc_uuid in self.locations:
            loc = Location(uuid=loc_uuid, tid=self.tid)
            # Randomly pick a direction - n, s, e, w
            exit = random.choice(list(directions.keys()))
            # If that exit already exists, take it
            if exit in loc.exits:
                self.move(loc.uuid, loc.exits[exit])
            # Otherwise, create a new exit with no land
            else:
                new_loc = Location(tid=self.tid)
                new_loc.add_exit(directions[exit], loc.uuid)
                loc.add_exit(exit, new_loc.uuid)
                new_loc._save()
                logging.info("I created a new piece of land, {} of here".format(exit))
            loc._save()
        self.schedule_next_tick()


handler = lambdaHandler(LandCreator)
