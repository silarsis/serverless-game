"""Tests for the Equipment aspect (gear, equip, unequip).

Equipment is an Aspect subclass that manages fixed gear slots, equip/unequip/gear commands,
and cached stat bonuses from equipped items.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from moto import mock_aws


@mock_aws
class TestEquipment(unittest.TestCase):
    """Test the Equipment aspect."""

    def setUp(self):
        """Set up DynamoDB tables for testing."""
        import boto3

        os.environ["ENTITY_TABLE"] = "test-entity"
        os.environ["LOCATION_TABLE"] = "test-location"

        self.dynamodb = boto3.resource("dynamodb", region_name="ap-southeast-1")

        # Entity table
        self.dynamodb.create_table(
            TableName="test-entity",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )

        # Location/Inventory/Equipment aspect table
        self.dynamodb.create_table(
            TableName="test-location",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )

    def _make_player(self, name="TestPlayer"):
        """Create Entity + Equipment aspect for a player."""
        from aspects.equipment import Equipment
        from aspects.thing import Entity

        entity = Entity()
        entity.data["name"] = name
        entity.data["location"] = "room-1"
        entity.data["aspects"] = ["Equipment"]
        entity.data["primary_aspect"] = "Equipment"
        entity._save()

        eq = Equipment()
        eq.data["uuid"] = entity.uuid
        eq._save()
        eq.entity = entity
        return eq, entity

    def _make_equippable_item(
        self,
        name="a test sword",
        location="room-1",
        slot="held_main",
        attack_bonus=5,
        defense_bonus=0,
        magic_bonus=0,
        hp_bonus=0,
        durability=100,
    ):
        """Create an equippable item (Entity + Inventory aspect with slot)."""
        from aspects.equipment import SLOTS
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
        inv.data["is_item"] = True
        inv.data["weight"] = 1
        inv.data["slot"] = slot
        inv.data["attack_bonus"] = attack_bonus
        inv.data["defense_bonus"] = defense_bonus
        inv.data["magic_bonus"] = magic_bonus
        inv.data["hp_bonus"] = hp_bonus
        inv.data["durability"] = durability
        inv._save()
        inv.entity = entity
        return inv, entity

    def test_gear_empty(self):
        """Test gear command when nothing is equipped."""
        eq, _ = self._make_player()
        result = eq.gear()

        assert result["type"] == "gear"
        assert "slots" in result
        assert "total_bonuses" in result

        # All slots should be None
        for slot_name, slot_data in result["slots"].items():
            assert slot_data is None

        # Bonuses should all be zero
        bonuses = result["total_bonuses"]
        assert bonuses["attack"] == 0
        assert bonuses["defense"] == 0
        assert bonuses["magic"] == 0
        assert bonuses["hp"] == 0

    def test_equip_no_uuid(self):
        """Test equip with no item UUID returns error."""
        eq, _ = self._make_player()
        result = eq.equip(item_uuid="")

        assert result["type"] == "error"
        assert "Equip what?" in result["message"]

    def test_equip_not_found(self):
        """Test equip with non-existent item returns error."""
        eq, _ = self._make_player()
        result = eq.equip(item_uuid="nonexistent-uuid")

        assert result["type"] == "error"
        assert "not found" in result["message"].lower()

    def test_equip_not_in_inventory(self):
        """Test equip item not in player's inventory returns error."""
        eq, player_entity = self._make_player()

        # Create item at a different location (not in player's inventory)
        _, item_entity = self._make_equippable_item(name="sword", location="room-1")

        result = eq.equip(item_uuid=item_entity.uuid)

        assert result["type"] == "error"
        assert "not carrying" in result["message"].lower()

    def test_equip_valid_item(self):
        """Test equipping a valid item."""
        eq, player_entity = self._make_player()

        # Create item and put it in player's inventory
        _, item_entity = self._make_equippable_item(
            name="Iron Sword",
            location=player_entity.uuid,
            slot="held_main",
            attack_bonus=10,
            defense_bonus=2,
        )

        result = eq.equip(item_uuid=item_entity.uuid)

        assert result["type"] == "equip_confirm"
        assert result["item"] == "Iron Sword"
        assert result["slot"] == "held_main"
        assert "stat_changes" in result
        assert "attack" in result["stat_changes"]
        assert result["message"] is not None

    def test_equip_replaces_existing(self):
        """Test equipping replaces existing item in slot."""
        eq, player_entity = self._make_player()

        # Create and equip first sword
        _, sword1_entity = self._make_equippable_item(
            name="Weak Sword", location=player_entity.uuid, slot="held_main", attack_bonus=5
        )
        eq.equip(item_uuid=sword1_entity.uuid)

        # Create second sword
        _, sword2_entity = self._make_equippable_item(
            name="Strong Sword", location=player_entity.uuid, slot="held_main", attack_bonus=15
        )

        result = eq.equip(item_uuid=sword2_entity.uuid)

        assert result["type"] == "equip_confirm"
        assert "replacing" in result["message"].lower()

    def test_unequip_no_slot(self):
        """Test unequip with no slot returns error."""
        eq, _ = self._make_player()
        result = eq.unequip(slot="")

        assert result["type"] == "error"
        assert "Unequip what?" in result["message"]

    def test_unequip_unknown_slot(self):
        """Test unequip with unknown slot returns error."""
        eq, _ = self._make_player()
        result = eq.unequip(slot="invalid_slot")

        assert result["type"] == "error"
        assert "Unknown slot" in result["message"]

    def test_unequip_nothing_equipped(self):
        """Test unequip from empty slot returns error."""
        eq, _ = self._make_player()
        result = eq.unequip(slot="head")

        assert result["type"] == "error"
        assert "Nothing is equipped" in result["message"]

    def test_unequip_valid_item(self):
        """Test unequipping an equipped item."""
        eq, player_entity = self._make_player()

        # Create and equip item
        _, item_entity = self._make_equippable_item(
            name="Magic Helm", location=player_entity.uuid, slot="head", magic_bonus=5
        )
        eq.equip(item_uuid=item_entity.uuid)

        result = eq.unequip(slot="head")

        assert result["type"] == "unequip_confirm"
        assert result["item"] == "Magic Helm"
        assert result["slot"] == "head"
        assert "stat_changes" in result
        assert "magic" in result["stat_changes"]

    def test_gear_shows_equipped(self):
        """Test gear command shows equipped items."""
        eq, player_entity = self._make_player()

        # Equip items in different slots
        _, head_item = self._make_equippable_item(
            name="Golden Crown", location=player_entity.uuid, slot="head", defense_bonus=3
        )
        eq.equip(item_uuid=head_item.uuid)

        _, main_item = self._make_equippable_item(
            name="Flame Blade", location=player_entity.uuid, slot="held_main", attack_bonus=20
        )
        eq.equip(item_uuid=main_item.uuid)

        result = eq.gear()

        assert result["type"] == "gear"
        assert result["slots"]["head"] is not None
        assert result["slots"]["head"]["name"] == "Golden Crown"
        assert result["slots"]["held_main"] is not None
        assert result["slots"]["held_main"]["name"] == "Flame Blade"

    def test_stat_bonuses_aggregation(self):
        """Test stat bonuses are correctly aggregated from all equipped items."""
        eq, player_entity = self._make_player()

        # Equip multiple items with various bonuses
        _, weapon = self._make_equippable_item(
            name="Sword", location=player_entity.uuid, slot="held_main", attack_bonus=10
        )
        eq.equip(item_uuid=weapon.uuid)

        _, armor = self._make_equippable_item(
            name="Plate", location=player_entity.uuid, slot="body", defense_bonus=15
        )
        eq.equip(item_uuid=armor.uuid)

        _, ring = self._make_equippable_item(
            name="Ring", location=player_entity.uuid, slot="accessory", magic_bonus=5, hp_bonus=20
        )
        eq.equip(item_uuid=ring.uuid)

        result = eq.gear()

        bonuses = result["total_bonuses"]
        assert bonuses["attack"] == 10
        assert bonuses["defense"] == 15
        assert bonuses["magic"] == 5
        assert bonuses["hp"] == 20

    def test_get_stat_bonuses_callable(self):
        """Test get_stat_bonuses callable method."""
        eq, player_entity = self._make_player()

        # Equip an item
        _, item = self._make_equippable_item(
            name="Amulet", location=player_entity.uuid, slot="accessory", magic_bonus=10
        )
        eq.equip(item_uuid=item.uuid)

        result = eq.get_stat_bonuses()

        assert "bonuses" in result
        assert result["bonuses"]["magic"] == 10

    def test_degrade_durability(self):
        """Test degrading item durability."""
        eq, player_entity = self._make_player()

        # Equip an item with 100 durability
        _, item = self._make_equippable_item(
            name="Shield", location=player_entity.uuid, slot="held_off", defense_bonus=10, durability=50
        )
        eq.equip(item_uuid=item.uuid)

        result = eq.degrade_durability(slot="held_off", amount=10)

        assert result["status"] == "degraded"
        assert result["durability"] == 40

    def test_durability_zero_penalty(self):
        """Test that broken items (0 durability) have halved bonuses."""
        eq, player_entity = self._make_player()

        # Equip item with 0 durability (broken)
        _, item = self._make_equippable_item(
            name="Broken Sword",
            location=player_entity.uuid,
            slot="held_main",
            attack_bonus=10,
            durability=0,
        )
        eq.equip(item_uuid=item.uuid)

        result = eq.gear()
        bonuses = result["total_bonuses"]

        # 10 / 2 = 5 due to durability penalty
        assert bonuses["attack"] == 5

    def test_degrade_durability_breaks(self):
        """Test that item breaks when durability reaches 0."""
        eq, player_entity = self._make_player()

        # Equip item with 5 durability
        _, item = self._make_equippable_item(
            name="Worn Sword",
            location=player_entity.uuid,
            slot="held_main",
            attack_bonus=10,
            durability=5,
        )
        eq.equip(item_uuid=item.uuid)

        result = eq.degrade_durability(slot="held_main", amount=10)

        assert result["status"] == "broken"
        assert "breaks" in result["message"].lower()

    def test_degrade_invalid_slot(self):
        """Test degrade_durability with invalid slot returns error."""
        eq, _ = self._make_player()
        result = eq.degrade_durability(slot="invalid_slot")

        assert result["status"] == "error"
        assert "Unknown slot" in result["message"]

    def test_degrade_empty_slot(self):
        """Test degrade_durability on empty slot returns noop."""
        eq, _ = self._make_player()
        result = eq.degrade_durability(slot="head", amount=1)

        assert result["status"] == "noop"

    def test_equip_invalid_slot(self):
        """Test equipping item with invalid slot returns error."""
        eq, player_entity = self._make_player()

        # Create item with invalid slot
        _, item = self._make_equippable_item(
            name="Strange Item", location=player_entity.uuid, slot="not_a_real_slot"
        )

        result = eq.equip(item_uuid=item.uuid)

        assert result["type"] == "error"
        assert "Invalid slot" in result["message"]

    def test_equip_no_slot(self):
        """Test equipping item with no slot returns error."""
        eq, player_entity = self._make_player()

        from aspects.inventory import Inventory
        from aspects.thing import Entity

        # Create item without a slot field
        entity = Entity()
        entity.data["name"] = "Unslotted Item"
        entity.data["location"] = player_entity.uuid
        entity.data["aspects"] = ["Inventory"]
        entity.data["primary_aspect"] = "Inventory"
        entity._save()

        inv = Inventory()
        inv.data["uuid"] = entity.uuid
        inv.data["is_item"] = True
        inv.data["weight"] = 1
        # No slot field set
        inv._save()

        result = eq.equip(item_uuid=entity.uuid)

        assert result["type"] == "error"
        assert "cannot be equipped" in result["message"]

    def test_SLOTS_constant(self):
        """Test SLOTS constant has expected slots."""
        from aspects.equipment import SLOTS

        expected_slots = ["head", "body", "hands", "feet", "held_main", "held_off", "accessory"]
        for slot in expected_slots:
            assert slot in SLOTS
            assert "name" in SLOTS[slot]
            assert "description" in SLOTS[slot]

    def test_slot_label_helper(self):
        """Test _slot_label helper function."""
        from aspects.equipment import _slot_label

        assert _slot_label("head") == "Head"
        assert _slot_label("held_main") == "Main Hand"
        assert _slot_label("unknown") == "unknown"


if __name__ == "__main__":
    unittest.main()