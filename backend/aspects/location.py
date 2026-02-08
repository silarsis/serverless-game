"""Location aspect — exits and spatial connections.

A thin Aspect subclass that owns exit management: exits, add_exit, remove_exit.
Land inherits from Location and adds grid-based world features.

Shared fields (location, contents, name, connection_id) live on Entity,
not on this aspect. Access them via self.entity.*.
"""

import logging
from typing import Dict

from aspects.handler import lambdaHandler
from aspects.thing import Aspect, Entity, IdType, callable

logger = logging.getLogger(__name__)

ExitsType = Dict[str, IdType]


class Location(Aspect):
    """Aspect handling exits and spatial connections.

    Stores: exits (dict of direction -> destination UUID).
    """

    _tableName = "LOCATION_TABLE"

    def __init__(self, uuid: IdType = None):
        """Initialize Location, setting up empty exits if new."""
        super().__init__(uuid)
        if not uuid:
            # New aspect record — initialize exits
            self.data.setdefault("exits", {})

    @property
    def exits(self) -> ExitsType:
        """Return the exits for this location."""
        return self.data.get("exits", {})

    @callable
    def add_exit(self, direction: str, destination: IdType) -> ExitsType:
        """Add an exit in a direction to a destination."""
        self.data.setdefault("exits", {})[direction] = destination
        self._save()
        return self.data["exits"]

    @callable
    def remove_exit(self, direction: str) -> ExitsType:
        """Remove the exit in the specified direction."""
        exits = self.data.get("exits", {})
        if direction in exits:
            del exits[direction]
            self._save()
        return self.data.get("exits", {})


handler = lambdaHandler(Entity)
