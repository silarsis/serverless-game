"""Land is locations on a grid with some terrain.

Rooms are generated lazily via the pluggable worldgen system when a
player first visits them.  The generator decides exits (variable, not
always 4), terrain entities, description, biome tags, and distant features.

Land inherits from Location (which owns exits). Land adds coordinates,
description, biome, and the worldgen integration.

Shared fields (name, location, contents) live on Entity, not on this aspect.
Access them via self.entity.*.
"""

import ast
import logging
from typing import Tuple

from boto3.dynamodb.conditions import Key

from .aws_client import get_dynamodb_table
from .decorators import player_command
from .handler import lambdaHandler
from .location import ExitsType, Location
from .weather import add_weather_to_description
from .thing import Entity, IdType, callable

logger = logging.getLogger(__name__)

CoordType = Tuple[int, int, int]


class Land(Location):
    """A location on a grid, represented by coordinates and some terrain.

    Inherits exits management from Location. Adds coordinates, description,
    biome, and worldgen.
    """

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
        # Create new land aspect record and entity
        land = cls()
        land.coordinates = coordinates
        # Also create the entity record for this room
        entity = Entity()
        entity.data["uuid"] = land.uuid  # Sync UUIDs
        entity.data["name"] = f"Room at {coordinates}"
        entity.data["aspects"] = ["Land"]
        entity.data["primary_aspect"] = "Land"
        entity._save()
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

        Uses self.entity.location to find the containing room, then loads
        that room's Land aspect.
        """
        loc = self.entity.location if self.entity else None
        if loc and loc != self.uuid:
            try:
                return Land(uuid=loc)
            except KeyError:
                pass
        return self

    _OPPOSITE = {
        "north": "south",
        "south": "north",
        "east": "west",
        "west": "east",
        "up": "down",
        "down": "up",
    }

    # ------------------------------------------------------------------
    # Room generation (replaces old _ensure_exits)
    # ------------------------------------------------------------------

    def _generate_room(self, room: "Land") -> None:
        """Generate a room's exits, terrain, and description if needed.

        Called when a player enters or looks at a room for the first time.
        Delegates to the pluggable worldgen system which decides exits
        (variable count), terrain entities, description, biome, etc.
        """
        if room.data.get("generated"):
            return  # already generated

        from .worldgen import generate_room

        # Build context: where did we come from, what neighbors exist?
        context = self._build_generation_context(room)

        # Generate the blueprint
        blueprint = generate_room(room.coordinates, context)

        # Apply exits (resolve coordinates → UUIDs, bidirectional)
        for direction, dest_coords in blueprint.exits.items():
            if direction in room.exits:
                continue  # don't overwrite existing exits
            try:
                dest_uuid = Land.by_coordinates(dest_coords)
                room.add_exit(direction, dest_uuid)
                # Ensure return exit on the neighbor
                neighbor = Land(uuid=dest_uuid)
                reverse = self._OPPOSITE.get(direction)
                if reverse and reverse not in neighbor.exits:
                    neighbor.add_exit(reverse, room.uuid)
            except Exception as e:
                logger.debug(f"Could not create exit {direction}: {e}")

        # Create terrain entities
        for terrain_spec in blueprint.terrain:
            self._create_terrain_entity(room, terrain_spec)

        # Store metadata on the room
        room.data["description"] = blueprint.description
        room.data["biome"] = blueprint.biome
        room.data["scale"] = blueprint.scale
        room.data["tags"] = blueprint.tags
        room.data["distant_features"] = blueprint.distant_features
        if blueprint.landmark:
            room.data["landmark"] = blueprint.landmark
        room.data["generated"] = True
        room._save()

        logger.info(
            f"Generated room at {room.coordinates}: "
            f"biome={blueprint.biome}, exits={list(blueprint.exits.keys())}"
        )

    def _build_generation_context(self, room: "Land"):
        """Build a GenerationContext for the worldgen system."""
        from .worldgen.base import GenerationContext

        # Where did we come from?
        my_room = self._current_room()
        came_from = None
        came_from_desc = None
        came_from_biome = None

        if my_room.uuid != room.uuid:
            try:
                came_from = my_room.coordinates
                came_from_desc = my_room.description
                came_from_biome = my_room.data.get("biome")
            except Exception:
                pass

        # Gather info about existing neighbors
        neighbors = {}
        for direction in ["north", "south", "east", "west", "up", "down"]:
            try:
                neighbor_coords = Land._new_coords_by_direction(room.coordinates, direction)
                # Check if a room already exists at those coords
                coords_str = Land._convertCoordinatesForStorage(neighbor_coords)
                table = get_dynamodb_table(self._tableName)
                result = table.query(
                    IndexName="cartesian",
                    Select="ALL_PROJECTED_ATTRIBUTES",
                    KeyConditionExpression=Key("coordinates").eq(coords_str),
                )
                if result["Items"]:
                    item = result["Items"][0]
                    neighbor_uuid = item["uuid"]
                    # Check if neighbor has an exit pointing back to us
                    neighbor = Land(uuid=neighbor_uuid)
                    reverse = self._OPPOSITE.get(direction)
                    has_exit_to_us = (
                        reverse in neighbor.exits and neighbor.exits[reverse] == room.uuid
                    )
                    neighbors[direction] = {
                        "coords": neighbor_coords,
                        "uuid": neighbor_uuid,
                        "description": neighbor.description or "",
                        "biome": neighbor.data.get("biome", ""),
                        "has_exit_to_us": has_exit_to_us,
                    }
            except Exception:
                continue

        return GenerationContext(
            came_from=came_from,
            came_from_description=came_from_desc,
            came_from_biome=came_from_biome,
            neighbors=neighbors,
        )

    @staticmethod
    def _create_terrain_entity(room: "Land", terrain_spec: dict) -> None:
        """Create a terrain entity at a room.

        Creates both an Entity record and an Inventory aspect record
        for the terrain object.
        """
        try:
            # Create entity record
            entity = Entity()
            entity.data["name"] = terrain_spec["name"]
            entity.data["location"] = room.uuid
            entity.data["aspects"] = ["Inventory"]
            entity.data["primary_aspect"] = "Inventory"
            entity._save()

            # Create inventory aspect record with terrain properties
            from .inventory import Inventory

            inv = Inventory()
            inv.data["uuid"] = entity.uuid  # Sync UUIDs
            inv.data["is_terrain"] = True
            inv.data["terrain_type"] = terrain_spec.get("type", "feature")
            inv.data["description"] = terrain_spec.get("description", "")
            inv.data["tags"] = terrain_spec.get("tags", [])
            inv.data["weight"] = terrain_spec.get("weight", 999)
            inv._save()
        except Exception as e:
            logger.debug(f"Could not create terrain entity: {e}")

    # ------------------------------------------------------------------
    # Player commands
    # ------------------------------------------------------------------

    @player_command
    def look(self) -> dict:
        """Look around the current location."""
        room = self._current_room()
        self._generate_room(room)

        desc = room.description or f"An empty stretch of land at {room.coordinates}."

        # Append distant features to description
        distant = room.data.get("distant_features", [])
        if distant:
            desc += " " + " ".join(distant[:2])

        # Get room entity's contents
        room_entity_contents = []
        try:
            room_entity = Entity(uuid=room.uuid)
            room_entity_contents = room_entity.contents
        except (KeyError, Exception):
            pass

        # Add time and weather overlay
        coords = room.coordinates
        biome = room.data.get("biome", "unknown")
        desc = add_weather_to_description(desc, coords[0], coords[1], biome)

        return {
            "type": "look",
            "description": desc,
            "coordinates": list(room.coordinates),
            "exits": list(room.exits.keys()),
            "contents": room_entity_contents,
            "biome": room.data.get("biome", "unknown"),
        }

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
        # Update the entity's location (writes to entity table)
        if self.entity:
            self.entity.location = dest_uuid

        # Load destination and generate if needed
        dest = Land(uuid=dest_uuid)
        self._generate_room(dest)

        desc = dest.description or f"An empty stretch of land at {dest.coordinates}."

        # Append distant features
        distant = dest.data.get("distant_features", [])
        if distant:
            desc += " " + " ".join(distant[:2])

        return {
            "type": "move",
            "direction": direction,
            "description": desc,
            "coordinates": list(dest.coordinates),
            "exits": list(dest.exits.keys()),
            "biome": dest.data.get("biome", "unknown"),
        }


handler = lambdaHandler(Entity)
