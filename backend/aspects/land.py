# Land is locations on a grid with some terrain

import ast
from os import environ
from typing import Tuple

import boto3
from boto3.dynamodb.conditions import Key

from .location import ExitsType, Location
from .thing import IdType, callable

CoordType = Tuple[int, int, int]


class Land(Location):
    _tableName = "LAND_TABLE"

    @classmethod
    def _convertCoordinatesForStorage(cls, value: CoordType) -> str:
        assert isinstance(value, tuple)
        assert len(value) == 3
        assert all([isinstance(item, int) for item in value])
        return str(value)

    @property
    def coordinates(self):
        return ast.literal_eval(self.data["coordinates"])

    @coordinates.setter
    def coordinates(self, value: CoordType):
        self.data["coordinates"] = self._convertCoordinatesForStorage(value)
        self._save()

    @classmethod
    def by_coordinates(cls, coordinates: CoordType) -> IdType:
        coords = cls._convertCoordinatesForStorage(coordinates)
        queryResults = (
            boto3.resource("dynamodb")
            .Table(environ[cls._tableName])
            .query(
                IndexName="cartesian",
                Select="ALL_PROJECTED_ATTRIBUTES",
                KeyConditionExpression=Key("coordinates").eq(coords),
            )
        )
        if queryResults["Items"]:
            return queryResults["Items"][0]["uuid"]
        land = cls()
        land.coordinates = coordinates
        return land.uuid

    @classmethod
    def _new_coords_by_direction(cls, coordinates: CoordType, direction: str) -> CoordType:
        exits = ["north", "south", "west", "east", "up", "down"]
        assert direction in exits
        new_coord = coordinates
        if direction == "north":
            new_coord = (coordinates[0], coordinates[1] + 1, coordinates[2])
        elif direction == "south":
            new_coord = (coordinates[0], coordinates[1] - 1, coordinates[2])
        elif direction == "west":
            new_coord = (coordinates[0] - 1, coordinates[1], coordinates[2])
        elif direction == "east":
            new_coord = (coordinates[0] + 1, coordinates[1], coordinates[2])
        elif direction == "up":
            new_coord = (coordinates[0], coordinates[1], coordinates[2] + 1)
        elif direction == "down":
            new_coord = (coordinates[0], coordinates[1], coordinates[2] - 1)
        return new_coord

    def by_direction(self, direction: str) -> IdType:
        new_coord = Land._new_coords_by_direction(self.coordinates, direction)
        return self.by_coordinates(new_coord)

    @callable
    def add_exit(self, direction: str, destination: IdType) -> ExitsType:
        if not destination:
            new_coord = self._new_coords_by_direction(self.coordinates, direction)
            destination = Land.by_coordinates(new_coord)
        return super().add_exit(direction, destination)
