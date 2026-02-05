"""Land is locations on a grid with some terrain."""

import ast
from typing import Tuple

from boto3.dynamodb.conditions import Key

from .aws_client import get_dynamodb_table
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
