"""Land is locations on a grid with some terrain."""

import ast
from typing import Tuple

from boto3.dynamodb.conditions import Key

from .aws_client import get_dynamodb_table
from .decorators import player_command
from .location import ExitsType, Location
from .thing import IdType, callable

CoordType = Tuple[int, int, int]


class Land(Location):
    """A location on a grid, represented by coordinates and some terrain."""

    _tableName = "LAND_TABLE"

    @classmethod
    def _convertCoordinatesForStorage(cls, value: CoordType) -> str:
        """Convert a tuple of coordinates to a string for storage.

        Args:
            value: A tuple of three integers representing the coordinates.
        Returns:
            String representation of coordinates.
        """
        assert isinstance(value, tuple)
        assert len(value) == 3
        assert all(isinstance(item, int) for item in value)
        return str(value)

    @property
    def coordinates(self):
        """Retrieve the coordinates from the data property."""
        return ast.literal_eval(self.data["coordinates"])

    @coordinates.setter
    def coordinates(self, value: CoordType):
        """Set the coordinates property and save the data.

        Args:
            value: A tuple of three integers representing the coordinates.
        """
        self.data["coordinates"] = self._convertCoordinatesForStorage(value)
        self._save()

    @classmethod
    def by_coordinates(cls, coordinates: CoordType) -> IdType:
        """Get or create land at the given coordinates.

        Args:
            coordinates: Tuple of (x, y, z) coordinates.
        Returns:
            UUID of the land at those coordinates.
        """
        coords_str = cls._convertCoordinatesForStorage(coordinates)
        key_condition = Key("coordinates").eq(coords_str)
        table = get_dynamodb_table(cls._tableName)
        queryResults = table.query(
            IndexName="cartesian",
            Select="ALL_PROJECTED_ATTRIBUTES",
            KeyConditionExpression=key_condition,
        )
        if queryResults["Items"]:
            return queryResults["Items"][0]["uuid"]
        land = cls()
        land.coordinates = coordinates
        return land.uuid

    @classmethod
    def _new_coords_by_direction(cls, coordinates: CoordType, direction: str) -> CoordType:
        """Compute new coordinates by moving in the given direction.

        Args:
            coordinates: Current (x, y, z) coordinates.
            direction: Direction to move (e.g., 'north', 'south').
        Returns:
            New (x, y, z) coordinates after moving in the given direction.
        """
        exits = ["north", "south", "west", "east", "up", "down"]
        assert direction in exits
        x, y, z = coordinates
        if direction == "north":
            return (x, y + 1, z)
        if direction == "south":
            return (x, y - 1, z)
        if direction == "west":
            return (x - 1, y, z)
        if direction == "east":
            return (x + 1, y, z)
        if direction == "up":
            return (x, y, z + 1)
        if direction == "down":
            return (x, y, z - 1)
        return coordinates

    def by_direction(self, direction: str) -> IdType:
        """Get the land ID in the given direction from this location.

        Args:
            direction: The direction to move in.
        Returns:
            UUID of the land in that direction.
        """
        new_coord = Land._new_coords_by_direction(self.coordinates, direction)
        land_id = self.by_coordinates(new_coord)
        return land_id

    @callable
    def add_exit(self, d: str, dest: IdType) -> ExitsType:
        """Add an exit in the given direction, creating a new land if necessary.

        Args:
            d: The direction for the exit.
            dest: The destination UUID or None to create one.
        Returns:
            Updated exits dictionary.
        """
        if not dest:
            new_coord = self._new_coords_by_direction(self.coordinates, d)
            dest = Land.by_coordinates(new_coord)
        result = super().add_exit(d, dest)
        return result

    @property
    def description(self):
        """Get the room description, or a default based on coordinates."""
        return self.data.get("description", "")

    @description.setter
    def description(self, value: str):
        """Set the room description."""
        self.data["description"] = value
        self._save()

    def _current_room(self) -> "Land":
        """Return the room the player is currently in.

        If this entity has a ``location`` pointing to another Land tile,
        load and return that room.  Otherwise ``self`` *is* the room.
        """
        loc = self.data.get("location")
        if loc and loc != self.uuid:
            try:
                return Land(uuid=loc)
            except KeyError:
                pass
        return self

    @player_command
    def look(self) -> dict:
        """Look around the current location."""
        room = self._current_room()
        desc = room.description or f"An empty stretch of land at {room.coordinates}."
        return {
            "type": "look",
            "description": desc,
            "coordinates": list(room.coordinates),
            "exits": list(room.exits.keys()),
            "contents": room.contents,
        }

    _OPPOSITE = {
        "north": "south",
        "south": "north",
        "east": "west",
        "west": "east",
        "up": "down",
        "down": "up",
    }

    def _ensure_exits(self, room: "Land") -> None:
        """Ensure a room has exits in all cardinal directions.

        When a player arrives in a room, we fill in any missing cardinal
        exits (and add a return exit on each new neighbor).  This makes
        the world infinitely explorable — every room you visit gets
        connected to its four cardinal neighbors.
        """
        for direction in ["north", "south", "east", "west"]:
            if direction in room.exits:
                continue
            try:
                new_coord = Land._new_coords_by_direction(
                    room.coordinates, direction
                )
                dest_uuid = Land.by_coordinates(new_coord)
                room.add_exit(direction, dest_uuid)
                # Ensure return exit on the neighbor
                neighbor = Land(uuid=dest_uuid)
                reverse = self._OPPOSITE[direction]
                if reverse not in neighbor.exits:
                    neighbor.add_exit(reverse, room.uuid)
            except Exception:
                pass

    @player_command
    def move(self, direction: str) -> dict:
        """Move to an adjacent location.

        Args:
            direction: The direction to move (north, south, east, west, up, down).
        Returns:
            dict with movement result and new location info.
        """
        valid_directions = ["north", "south", "east", "west", "up", "down"]
        if direction not in valid_directions:
            return {"type": "error", "message": f"Invalid direction: {direction}"}

        room = self._current_room()
        if direction not in room.exits:
            return {"type": "error", "message": f"There is no exit to the {direction}."}

        dest_uuid = room.exits[direction]
        # Update the player's location to the destination
        self.data["location"] = dest_uuid
        self._save()

        # Load destination and auto-generate exits if needed
        dest = Land(uuid=dest_uuid)
        self._ensure_exits(dest)

        desc = dest.description or f"An empty stretch of land at {dest.coordinates}."
        return {
            "type": "move",
            "direction": direction,
            "description": desc,
            "coordinates": list(dest.coordinates),
            "exits": list(dest.exits.keys()),
        }
