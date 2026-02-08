"""Tests for the Inventory aspect (take, drop, examine, inventory).

Inventory is now an Aspect subclass. Shared fields (name, location, contents)
live on Entity. Tests create Entity records and wire them to Inventory
aspects via the entity back-reference.
"""

import os
import unittest

from moto import mock_aws


@mock_aws
class TestInventory(unittest.TestCase):
    """Test the Inventory aspect."""

    def setUp(self):
        """Set up DynamoDB tables for testing."""
        import boto3

        os.environ["ENTITY_TABLE"] = "test-entity"
        os.environ["LOCATION_TABLE"] = "test-location"

        self.dynamodb = boto3.resource("dynamodb", region_name="ap-southeast-1")

        # Entity table with contents GSI
        self.dynamodb.create_table(
            TableName="test-entity",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
                {"AttributeName": "location", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "contents",
                    "KeySchema": [
                        {"AttributeName": "location", "KeyType": "HASH"},
                        {"AttributeName": "uuid", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                    "ProvisionedThroughput": {
                        "ReadCapacityUnits": 5,
                        "WriteCapacityUnits": 5,
                    },
                }
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )

        # Location/Inventory aspect table
        self.dynamodb.create_table(
            TableName="test-location",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )

    def _make_player(self, name="TestPlayer", location="room-1", carry_capacity=None):
        """Helper: create Entity + Inventory aspect for a player."""
        from aspects.inventory import Inventory
        from aspects.thing import Entity

        entity = Entity()
        entity.data["name"] = name
        if location is not None:
            entity.data["location"] = location
        entity.data["aspects"] = ["Inventory"]
        entity.data["primary_aspect"] = "Inventory"
        entity._save()

        inv = Inventory()
        inv.data["uuid"] = entity.uuid
        if carry_capacity is not None:
            inv.data["carry_capacity"] = carry_capacity
        inv._save()
        inv.entity = entity
        return inv, entity

    def _make_item(self, name="a test item", location="room-1", is_item=True,
                   weight=1, description="", is_terrain=False):
        """Helper: create Entity + Inventory aspect for an item."""
        from aspects.inventory import Inventory
        from aspects.thing import Entity

        entity = Entity()
        entity.data["name"] = name
        entity.data["location"] = location
        entity.data["aspects"] = ["Inventory"]
        entity.data["primary_aspect"] = "Inventory"
        entity._save()

        inv = Inventory()
        inv.data["uuid"] = entity.uuid
        inv.data["is_item"] = is_item
        inv.data["weight"] = weight
        if description:
            inv.data["description"] = description
        if is_terrain:
            inv.data["is_terrain"] = True
            inv.data["is_item"] = False
        inv._save()
        inv.entity = entity
        return inv, entity

    def test_take_no_item(self):
        """Test take with no item UUID returns error."""
        inv, _ = self._make_player(location="loc-123")
        result = inv.take(item_uuid="")
        assert result["type"] == "error"
        assert "Take what?" in result["message"]

    def test_take_no_location(self):
        """Test take when entity has no location."""
        inv, entity = self._make_player(location=None)
        # Entity has no location field at all
        result = inv.take(item_uuid="some-uuid")
        assert result["type"] == "error"

    def test_drop_no_item(self):
        """Test drop with no item UUID returns error."""
        inv, _ = self._make_player(location="loc-123")
        result = inv.drop(item_uuid="")
        assert result["type"] == "error"

    def test_examine_no_item(self):
        """Test examine with no item UUID returns error."""
        inv, _ = self._make_player()
        result = inv.examine(item_uuid="")
        assert result["type"] == "error"

    def test_examine_nonexistent(self):
        """Test examine with non-existent item returns error."""
        inv, _ = self._make_player()
        result = inv.examine(item_uuid="nonexistent-uuid")
        assert result["type"] == "error"

    def test_inventory_empty(self):
        """Test inventory when carrying nothing."""
        inv, _ = self._make_player(location="loc-123")
        result = inv.inventory()
        assert result["type"] == "inventory"
        assert result["count"] == 0
        assert result["items"] == []

    def test_create_item(self):
        """Test creating an item at a location."""
        inv, _ = self._make_player(location="loc-123")
        result = inv.create_item(name="a test sword", description="A sharp blade.")
        assert result["type"] == "item_created"
        assert result["name"] == "a test sword"
        assert "item_uuid" in result

    def test_take_and_drop_flow(self):
        """Test the full take and drop flow."""
        inv, player_entity = self._make_player(name="TestPlayer", location="room-1")
        _, item_entity = self._make_item(
            name="a golden ring", location="room-1",
            description="A ring of gold.", is_item=True
        )

        # Take the item
        result = inv.take(item_uuid=item_entity.uuid)
        assert result["type"] == "take_confirm"
        assert "golden ring" in result["message"]

        # Verify item is now in player's inventory (location = player uuid)
        from aspects.thing import Entity
        item_reloaded = Entity(uuid=item_entity.uuid)
        assert item_reloaded.location == player_entity.uuid

        # Drop the item
        result = inv.drop(item_uuid=item_entity.uuid)
        assert result["type"] == "drop_confirm"

        # Verify item is back at the location
        item_reloaded2 = Entity(uuid=item_entity.uuid)
        assert item_reloaded2.location == "room-1"

    def test_examine_item(self):
        """Test examining an item in inventory."""
        inv, player_entity = self._make_player(location="room-1")
        _, item_entity = self._make_item(
            name="magic wand", location=player_entity.uuid,
            description="A wand crackling with energy.", is_item=True
        )

        result = inv.examine(item_uuid=item_entity.uuid)
        assert result["type"] == "examine"
        assert result["name"] == "magic wand"
        assert "crackling" in result["description"]

    def test_take_weight_limit(self):
        """Test that take rejects items exceeding carry capacity."""
        inv, _ = self._make_player(
            name="WeakPlayer", location="room-1", carry_capacity=5
        )
        _, heavy_entity = self._make_item(
            name="a massive boulder", location="room-1",
            is_item=True, weight=100
        )

        result = inv.take(item_uuid=heavy_entity.uuid)
        assert result["type"] == "error"
        assert "heavy" in result["message"].lower()

    def test_take_within_weight_limit(self):
        """Test that take succeeds when within carry capacity."""
        inv, _ = self._make_player(
            name="StrongPlayer", location="room-1", carry_capacity=50
        )
        _, light_entity = self._make_item(
            name="a feather", location="room-1",
            is_item=True, weight=1
        )

        result = inv.take(item_uuid=light_entity.uuid)
        assert result["type"] == "take_confirm"

    def test_carried_weight_calculation(self):
        """Test that _carried_weight sums correctly."""
        inv, player_entity = self._make_player(name="TestPlayer", location="room-1")

        # Create two items in player's inventory (location = player UUID)
        self._make_item(
            name="sword", location=player_entity.uuid,
            is_item=True, weight=10
        )
        self._make_item(
            name="shield", location=player_entity.uuid,
            is_item=True, weight=15
        )

        total = inv._carried_weight()
        assert total == 25

    def test_default_carry_capacity(self):
        """Test that default carry capacity is 50."""
        inv, _ = self._make_player(name="TestPlayer", location="room-1")
        _, item_entity = self._make_item(
            name="a heavy sack", location="room-1",
            is_item=True, weight=49
        )

        result = inv.take(item_uuid=item_entity.uuid)
        assert result["type"] == "take_confirm"

    def test_cant_take_terrain(self):
        """Test that terrain entities (is_terrain=True) can't be picked up."""
        inv, _ = self._make_player(name="TestPlayer", location="room-1")
        _, terrain_entity = self._make_item(
            name="a tall oak tree", location="room-1",
            is_terrain=True, weight=999
        )

        result = inv.take(item_uuid=terrain_entity.uuid)
        assert result["type"] == "error"
        assert "can't pick" in result["message"].lower()


if __name__ == "__main__":
    unittest.main()
