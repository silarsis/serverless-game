from handler import lambdaHandler
from location import Location
import random


class LandCreator(Location):
    " This entity creates new exits and moves "
    def tick(self):
        # Get a list of exits in the location I'm in
        directions = {
            'north': 'south',
            'south': 'north',
            'west': 'east',
            'east': 'west'
        }
        for loc in self.locations:
            # Randomly pick a direction - n, s, e, w
            exit = random.choice(directions)
            # If that exit already exists, take it
            if exit in loc.exits:
                self.move(loc.uuid, loc.exits[exit])
            # Otherwise, create a new exit with no land
            else:
                new_loc = Location()
                new_loc.add_exit(directions[exit], loc.uuid)
                loc.add_exit(exit, new_loc.uuid)
        self.schedule_next_tick()


handler = lambdaHandler(LandCreator)
