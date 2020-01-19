import thing
from handler import lambdaHandler
import random


class LandCreator(thing):
    " This entity creates new exits and moves "
    def create(self):
        # Land creators are mobs, so they're location aware
        self.createAspect('Location')
        super().create()

    def tick(self):
        # Get a list of exits in the location I'm in
        my = self.aspect('Location')
        directions = {
            'north': 'south',
            'south': 'north',
            'west': 'east',
            'east': 'west'
        }
        for loc in my.locations:
            # Randomly pick a direction - n, s, e, w
            exit = random.choice(directions)
            # If that exit already exists, take it
            if exit in loc.exits:  # loc.exits is wrong, need to callback here
                my.move(loc.uuid, loc.exits[exit])
            # Otherwise, create a new exit with no land
            else:
                # create isn't a good call, init with no uuid already creates
                self.call(
                    '',
                    'Location',
                    'add_exit',
                    direction=directions[exit],
                    destination=loc
                ).thenCall(loc.uuid, 'Location', 'add_exit', )
                loc.add_exit(exit, '')


handler = lambdaHandler(LandCreator)
