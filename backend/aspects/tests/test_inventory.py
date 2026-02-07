"""Tests for the Inventory aspect (take, drop, examine, inventory)."""

import os
import unittest

from moto import mock_aws


@mock_aws
class TestInventory(unittest.TestCase):
    """Test the Inventory aspect."""

    def setUp(self):
        """Set up DynamoDB tables for testing."""
        import boto3

        os.environ["LOCATION_TABLE"] = "test-location"
        os.environ["THING_TABLE"] = "test-thing"
        os.environ["LAND_TABLE"] = "test-land"

        self.dynamodb = boto3.resource("dynamodb", region_name="ap-southeast-1")

        # Create location table with contents GSI
        self.dynamodb.create_table(
            TableName="test-location",
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

        # Create thing table
        self.dynamodb.create_table(
            TableName="test-thing",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )

        self.mock = mock_aws()

    def test_take_no_item(self):
        """Test take with no item UUID returns error."""
        from aspects.inventory import Inventory

        inv = Inventory()
        inv.data["location"] = "loc-123"
        result = inv.take(item_uuid="")
        assert result["type"] == "error"
        assert "Take what?" in result["message"]

    def test_take_no_location(self):
        """Test take when entity has no location."""
        from aspects.inventory import Inventory

        inv = Inventory()
        inv.data["location"] = None
        result = inv.take(item_uuid="some-uuid")
        assert result["type"] == "error"

    def test_drop_no_item(self):
        """Test drop with no item UUID returns error."""
        from aspects.inventory import Inventory

        inv = Inventory()
        inv.data["location"] = "loc-123"
        result = inv.drop(item_uuid="")
        assert result["type"] == "error"

    def test_examine_no_item(self):
        """Test examine with no item UUID returns error."""
        from aspects.inventory import Inventory

        inv = Inventory()
        result = inv.examine(item_uuid="")
        assert result["type"] == "error"

    def test_examine_nonexistent(self):
        """Test examine with non-existent item returns error."""
        from aspects.inventory import Inventory

        inv = Inventory()
        result = inv.examine(item_uuid="nonexistent-uuid")
        assert result["type"] == "error"

    def test_inventory_empty(self):
        """Test inventory when carrying nothing."""
        from aspects.inventory import Inventory

        inv = Inventory()
        inv.data["location"] = "loc-123"
        result = inv.inventory()
        assert result["type"] == "inventory"
        assert result["count"] == 0
        assert result["items"] == []

    def test_create_item(self):
        """Test creating an item at a location."""
        from aspects.inventory import Inventory

        inv = Inventory()
        inv.data["location"] = "loc-123"
        result = inv.create_item(name="a test sword", description="A sharp blade.")
        assert result["type"] == "item_created"
        assert result["name"] == "a test sword"
        assert "item_uuid" in result

    def test_take_and_drop_flow(self):
        """Test the full take and drop flow."""
        from aspects.inventory import Inventory

        # Create a player entity at a location
        player = Inventory()
        player.data["location"] = "room-1"
        player.data["name"] = "TestPlayer"
        player._save()

        # Create an item at the same location
        item = Inventory()
        item.data["location"] = "room-1"
        item.data["name"] = "a golden ring"
        item.data["description"] = "A ring of gold."
        item.data["is_item"] = True
        item._save()

        # Take the item
        result = player.take(item_uuid=item.uuid)
        assert result["type"] == "take_confirm"
        assert "golden ring" in result["message"]

        # Verify item is now in player's inventory
        item_reloaded = Inventory(uuid=item.uuid)
        assert item_reloaded.location == player.uuid

        # Drop the item
        result = player.drop(item_uuid=item.uuid)
        assert result["type"] == "drop_confirm"

        # Verify item is back at the location
        item_reloaded2 = Inventory(uuid=item.uuid)
        assert item_reloaded2.location == "room-1"

    def test_examine_item(self):
        """Test examining an item in inventory."""
        from aspects.inventory import Inventory

        # Create player and item
        player = Inventory()
        player.data["location"] = "room-1"
        player._save()

        item = Inventory()
        item.data["location"] = player.uuid  # in player's inventory
        item.data["name"] = "magic wand"
        item.data["description"] = "A wand crackling with energy."
        item.data["is_item"] = True
        item._save()

        result = player.examine(item_uuid=item.uuid)
        assert result["type"] == "examine"
        assert result["name"] == "magic wand"
        assert "crackling" in result["description"]


if __name__ == "__main__":
    unittest.main()
