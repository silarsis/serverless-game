import thing
from handler import lambdaHandler
import random


class LandCreator(thing):
    " This entity creates new exits and moves "
    def create(self):
        # Land creators are mobs, so they're location aware
        self.createAspect('location')
        super().create()

    def tick(self):
        # Get a list of exits in the location I'm in
        my = self.aspect('Location')
        for loc in my.locations:
            # Randomly pick a direction - n, s, e, w
            exit = random.choice(['north', 'south', 'west', 'east'])
            # If that exit already exists, take it
            if exit in loc.exits:
                my.move(loc.uuid, loc.exits[exit])
            # Otherwise, create a new exit with no land
            else:
                my.add_exit(exit, '')


handler = lambdaHandler(LandCreator)
