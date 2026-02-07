"""Inventory aspect for item management.

Items are Things with a Location. An item's location can be either a land
tile UUID (it's on the ground) or an entity UUID (it's in that entity's
inventory). Uses the existing Location contents GSI to query.
"""

import logging

from .decorators import player_command
from .handler import lambdaHandler
from .location import Location
from .thing import Thing, callable

logger = logging.getLogger(__name__)


class Inventory(Location):
    """Aspect handling item pickup, dropping, and examination."""

    @player_command
    def take(self, item_uuid: str) -> dict:
        """Pick up an item from the current location.

        Args:
            item_uuid: UUID of the item to pick up.

        Returns:
            dict with take result.
        """
        if not item_uuid:
            return {"type": "error", "message": "Take what?"}

        my_location = self.location
        if not my_location:
            return {"type": "error", "message": "You are nowhere."}

        # Verify the item is at our location
        try:
            item = Inventory(uuid=item_uuid)
        except KeyError:
            return {"type": "error", "message": "That item doesn't exist."}

        if item.location != my_location:
            return {"type": "error", "message": "That item isn't here."}

        # Check it's actually an item (has is_item flag)
        if not item.data.get("is_item"):
            return {"type": "error", "message": "You can't pick that up."}

        # Move item to our inventory (set location to our UUID)
        item.location = self.uuid
        item_name = item.data.get("name", item_uuid[:8])

        # Notify others at the location
        self._broadcast_to_location(
            my_location,
            {
                "type": "take",
                "actor": self.data.get("name", self.uuid[:8]),
                "item": item_name,
            },
        )

        return {
            "type": "take_confirm",
            "message": f"You pick up {item_name}.",
            "item_uuid": item_uuid,
        }

    @player_command
    def drop(self, item_uuid: str) -> dict:
        """Drop an item from inventory to the current location.

        Args:
            item_uuid: UUID of the item to drop.

        Returns:
            dict with drop result.
        """
        if not item_uuid:
            return {"type": "error", "message": "Drop what?"}

        my_location = self.location
        if not my_location:
            return {"type": "error", "message": "You are nowhere."}

        # Verify item is in our inventory
        try:
            item = Inventory(uuid=item_uuid)
        except KeyError:
            return {"type": "error", "message": "That item doesn't exist."}

        if item.location != self.uuid:
            return {"type": "error", "message": "You don't have that item."}

        # Move item to current location
        item.location = my_location
        item_name = item.data.get("name", item_uuid[:8])

        # Notify others at the location
        self._broadcast_to_location(
            my_location,
            {
                "type": "drop",
                "actor": self.data.get("name", self.uuid[:8]),
                "item": item_name,
            },
        )

        return {
            "type": "drop_confirm",
            "message": f"You drop {item_name}.",
            "item_uuid": item_uuid,
        }

    @player_command
    def examine(self, item_uuid: str) -> dict:
        """Examine an item (in inventory or at current location).

        Args:
            item_uuid: UUID of the item to examine.

        Returns:
            dict with item details.
        """
        if not item_uuid:
            return {"type": "error", "message": "Examine what?"}

        try:
            item = Inventory(uuid=item_uuid)
        except KeyError:
            return {"type": "error", "message": "That item doesn't exist."}

        # Must be in our inventory or at our location
        if item.location != self.uuid and item.location != self.location:
            return {"type": "error", "message": "You can't see that item."}

        return {
            "type": "examine",
            "name": item.data.get("name", item_uuid[:8]),
            "description": item.data.get("description", "Nothing special about it."),
            "item_uuid": item_uuid,
            "properties": {
                k: v
                for k, v in item.data.items()
                if k not in ("uuid", "exits", "location", "connection_id")
            },
        }

    @player_command
    def inventory(self) -> dict:
        """List items in this entity's inventory.

        Returns:
            dict with list of carried items.
        """
        # Items in inventory have their location set to our UUID
        item_uuids = self.contents  # Uses the GSI: location = self.uuid
        items = []
        for iuuid in item_uuids:
            try:
                item = Inventory(uuid=iuuid)
                if item.data.get("is_item"):
                    items.append(
                        {
                            "uuid": iuuid,
                            "name": item.data.get("name", iuuid[:8]),
                        }
                    )
            except KeyError:
                continue

        return {
            "type": "inventory",
            "items": items,
            "count": len(items),
        }

    @callable
    def create_item(self, name: str, description: str = "", **properties) -> dict:
        """Create a new item at a location.

        Args:
            name: Display name for the item.
            description: Item description.
            **properties: Additional item properties.

        Returns:
            dict with created item info.
        """
        item = Inventory()
        item.data["name"] = name
        item.data["description"] = description
        item.data["is_item"] = True
        item.data.update(properties)
        item.location = self.location or self.uuid
        item._save()

        return {
            "type": "item_created",
            "item_uuid": item.uuid,
            "name": name,
        }

    def _broadcast_to_location(self, location_uuid: str, event: dict) -> None:
        """Push an event to all connected entities at a location, except self."""
        try:
            loc = Location(uuid=location_uuid)
            for entity_uuid in loc.contents:
                if entity_uuid == self.uuid:
                    continue
                try:
                    entity = Thing(uuid=entity_uuid)
                    entity.push_event(event)
                except (KeyError, Exception):
                    pass
        except (KeyError, Exception) as e:
            logger.debug(f"Could not broadcast to location {location_uuid}: {e}")


handler = lambdaHandler(Inventory)
