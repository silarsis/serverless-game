"""Tests for the Equipment aspect."""

import os
import unittest

from moto import mock_aws


@mock_aws
class TestEquipment(unittest.TestCase):
    """Test the Equipment aspect."""

    def setUp(self):
        """Set up DynamoDB tables for testing."""
        import boto3

        os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

        os.environ["ENTITY_TABLE"] = "test-entity"
        os.environ["LOCATION_TABLE"] = "test-location"

        self.dynamodb = boto3.resource("dynamodb", region_name="ap-southeast-1")

        # Entity table
        self.dynamodb.create_table(
            TableName="test-entity",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "uuid", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )

        # Location/Inventory/Equipment aspect table
        self.dynamodb.create_table(
            TableName="test-location",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "uuid", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )

    def _make_player(self, name="TestPlayer"):
        """Create Entity with Equipment aspect."""
        from aspects.equipment import Equipment
        from aspects.thing import Entity

        entity = Entity()
        entity.data["name"] = name
        entity.data["location"] = "room-1"
        entity.data["aspects"] = ["Equipment"]
        entity.data["primary_aspect"] = "Equipment"
        entity._save()

        equip = Equipment()
        equip.data["uuid"] = entity.uuid
        equip._save()
        equip.entity = entity
        return equip, entity

    def _make_equippable_item(
        self, name, slot, attack_bonus=0, defense_bonus=0, magic_bonus=0, location="room-1"
    ):
        """Create Entity + Inventory aspect for an equippable item."""
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
        inv.data["slot"] = slot
        inv.data["attack_bonus"] = attack_bonus
        inv.data["defense_bonus"] = defense_bonus
        inv.data["magic_bonus"] = magic_bonus
        inv.data["durability"] = 100
        inv._save()
        inv.entity = entity
        return inv, entity

    def test_gear_empty(self):
        """Test gear command with no equipment."""
        equip, _ = self._make_player()
        result = equip.gear()
        assert result["type"] == "gear"
        assert result["slots"]["head"] is None
        assert result["total_bonuses"]["attack"] == 0

    def test_equip(self):
        """Test equipping an item."""
        equip, player = self._make_player()
        inv, item = self._make_equippable_item("iron sword", "held_main", attack_bonus=3)
        item.data["location"] = player.uuid
        item._save()

        result = equip.equip(item_uuid=item.uuid)
        assert result["type"] == "equip_confirm"
        assert result["item"] == "iron sword"
        assert result["slot"] == "held_main"

    def test_unequip(self):
        """Test unequipping an item."""
        equip, player = self._make_player()
        inv, item = self._make_equippable_item("iron sword", "held_main", attack_bonus=3)
        item.data["location"] = player.uuid
        item._save()

        # Equip first
        equip.equip(item_uuid=item.uuid)

        # Now unequip
        result = equip.unequip(slot="held_main")
        assert result["type"] == "unequip_confirm"
        assert result["slot"] == "held_main"

    def test_equip_invalid_slot(self):
        """Test equipping an item to an invalid slot."""
        equip, player = self._make_player()
        inv, item = self._make_equippable_item("weird item", "invalid_slot")
        item.data["location"] = player.uuid
        item._save()

        result = equip.equip(item_uuid=item.uuid)
        assert result["type"] == "error"
        assert "Invalid slot" in result["message"]

    def test_equip_not_in_inventory(self):
        """Test equipping an item not in inventory."""
        equip, _ = self._make_player()
        inv, item = self._make_equippable_item("iron sword", "held_main")

        result = equip.equip(item_uuid=item.uuid)
        assert result["type"] == "error"
        assert "not carrying" in result["message"]


if __name__ == "__main__":
    unittest.main()
