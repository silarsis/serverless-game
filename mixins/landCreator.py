import thing
from handler import lambdaHandler
import random


class LandCreator(thing):
    " This entity creates new exits and moves "
    def tick(self):
        # Get a list of exits in the location I'm in
        exits = self.location.exits
        # Randomly pick a direction - n, s, e, w
        exit = random.choice(['north', 'south', 'west', 'east'])
        # If that exit already exists, take it
        if exit in exits:
            self.move(exit)
        # Otherwise, create a new exit with a new piece of land
        else:
            self.location.createExit(exit)


handler = lambdaHandler(LandCreator)
