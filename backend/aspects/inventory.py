"""Inventory aspect for item management.

Items are Things with a Location. An item's location can be either a land
tile UUID (it's on the ground) or an entity UUID (it's in that entity's
inventory). Uses the entity table's contents GSI to query.

Shared fields (name, location, contents) live on Entity, not on this aspect.
Access them via self.entity.*.
"""

import logging

from .decorators import player_command
from .handler import lambdaHandler
from .thing import Aspect, Entity, callable

logger = logging.getLogger(__name__)


class Inventory(Aspect):
    """Aspect handling item pickup, dropping, and examination.

    Stores: carry_capacity, is_item, weight, is_terrain, terrain_type,
    item_description, tags.
    """

    _tableName = "LOCATION_TABLE"  # Shared aspect table — keyed by entity UUID, no conflicts

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

        my_location = self.entity.location
        if not my_location:
            return {"type": "error", "message": "You are nowhere."}

        # Verify the item is at our location
        try:
            item_entity = Entity(uuid=item_uuid)
        except KeyError:
            return {"type": "error", "message": "That item doesn't exist."}

        if item_entity.location != my_location:
            return {"type": "error", "message": "That item isn't here."}

        # Check it's actually an item (has is_item flag, not terrain)
        # Load the item's inventory aspect to check
        try:
            item_inv = item_entity.aspect("Inventory")
        except (ValueError, KeyError):
            return {"type": "error", "message": "You can't pick that up."}

        if not item_inv.data.get("is_item"):
            return {"type": "error", "message": "You can't pick that up."}

        # Check weight capacity
        item_weight = item_inv.data.get("weight", 1)
        carry_capacity = self.data.get("carry_capacity", 50)
        current_load = self._carried_weight()
        if current_load + item_weight > carry_capacity:
            return {
                "type": "error",
                "message": "That's too heavy to carry.",
            }

        # Move item to our inventory (set item entity's location to our UUID)
        item_entity.location = self.entity.uuid
        item_name = item_entity.name

        # Notify others at the location
        self.entity.broadcast_to_location(
            my_location,
            {
                "type": "take",
                "actor": self.entity.name,
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

        my_location = self.entity.location
        if not my_location:
            return {"type": "error", "message": "You are nowhere."}

        # Verify item is in our inventory
        try:
            item_entity = Entity(uuid=item_uuid)
        except KeyError:
            return {"type": "error", "message": "That item doesn't exist."}

        if item_entity.location != self.entity.uuid:
            return {"type": "error", "message": "You don't have that item."}

        # Move item to current location
        item_entity.location = my_location
        item_name = item_entity.name

        # Notify others at the location
        self.entity.broadcast_to_location(
            my_location,
            {
                "type": "drop",
                "actor": self.entity.name,
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
            item_entity = Entity(uuid=item_uuid)
        except KeyError:
            return {"type": "error", "message": "That item doesn't exist."}

        # Must be in our inventory or at our location
        if (
            item_entity.location != self.entity.uuid
            and item_entity.location != self.entity.location
        ):
            return {"type": "error", "message": "You can't see that item."}

        # Load item's inventory aspect for properties
        try:
            item_inv = item_entity.aspect("Inventory")
        except (ValueError, KeyError):
            item_inv = None

        item_data = item_inv.data if item_inv else {}

        return {
            "type": "examine",
            "name": item_entity.name,
            "description": item_data.get("description", "Nothing special about it."),
            "item_uuid": item_uuid,
            "properties": {
                k: v
                for k, v in item_data.items()
                if k not in ("uuid", "exits", "location", "connection_id")
            },
        }

    @player_command
    def inventory(self) -> dict:
        """List items in this entity's inventory.

        Returns:
            dict with list of carried items.
        """
        # Items in inventory have their location set to our UUID in the entity table
        item_uuids = self.entity.contents
        items = []
        for iuuid in item_uuids:
            try:
                item_entity = Entity(uuid=iuuid)
                item_inv = item_entity.aspect("Inventory")
                if item_inv.data.get("is_item"):
                    items.append(
                        {
                            "uuid": iuuid,
                            "name": item_entity.name,
                        }
                    )
            except (KeyError, ValueError):
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
        # Create entity record
        item_entity = Entity()
        item_entity.data["name"] = name
        item_entity.data["location"] = self.entity.location or self.entity.uuid
        item_entity.data["aspects"] = ["Inventory"]
        item_entity.data["primary_aspect"] = "Inventory"
        item_entity._save()

        # Create inventory aspect record
        item_inv = Inventory()
        item_inv.data["uuid"] = item_entity.uuid  # Sync UUIDs
        item_inv.data["description"] = description
        item_inv.data["is_item"] = True
        item_inv.data.update(properties)
        item_inv._save()

        return {
            "type": "item_created",
            "item_uuid": item_entity.uuid,
            "name": name,
        }

    def _carried_weight(self) -> int:
        """Calculate total weight of items in inventory.

        Excludes equipped items (items in Equipment aspect's equipped dict)
        from the weight calculation.
        """
        # Get equipped item UUIDs to exclude from weight
        equipped_uuids = set()
        try:
            equip = self.entity.aspect("Equipment")
            equipped_uuids = set(equip.data.get("equipped", {}).values())
        except (ValueError, KeyError):
            pass  # Equipment aspect not present - no exclusions

        total = 0
        for iuuid in self.entity.contents:
            if iuuid in equipped_uuids:
                continue  # Skip equipped items
            try:
                item_entity = Entity(uuid=iuuid)
                item_inv = item_entity.aspect("Inventory")
                if item_inv.data.get("is_item"):
                    total += item_inv.data.get("weight", 1)
            except (KeyError, ValueError):
                continue
        return total


handler = lambdaHandler(Entity)
