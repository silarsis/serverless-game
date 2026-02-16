"""Tests for the Identity aspect (name, describe, appearance, inspect, profile, title).

Identity is an Aspect subclass. Tests create Entity records and wire them to Identity
aspects via the entity back-reference.
"""

import os
import unittest

from moto import mock_aws


@mock_aws
class TestIdentity(unittest.TestCase):
    """Test the Identity aspect."""

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

        # Location/Identity aspect table
        self.dynamodb.create_table(
            TableName="test-location",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )

    def _make_player(self, name="TestPlayer", location="room-1"):
        """Create Entity + Identity aspect for a player."""
        from aspects.identity import Identity
        from aspects.thing import Entity

        entity = Entity()
        entity.data["name"] = name
        if location is not None:
            entity.data["location"] = location
        entity.data["aspects"] = ["Identity"]
        entity.data["primary_aspect"] = "Identity"
        entity._save()

        identity = Identity()
        identity.data["uuid"] = entity.uuid
        identity._save()
        identity.entity = entity

        return entity, identity

    def test_name_empty_rejected(self):
        """Test that empty name is rejected."""
        _, identity = self._make_player()
        result = identity.name("")
        self.assertEqual(result["type"], "error")
        self.assertIn("empty", result["message"].lower())

    def test_name_whitespace_rejected(self):
        """Test that whitespace-only name is rejected."""
        _, identity = self._make_player()
        result = identity.name("   ")
        self.assertEqual(result["type"], "error")
        self.assertIn("empty", result["message"].lower())

    def test_name_too_long_rejected(self):
        """Test that name over 50 chars is rejected."""
        _, identity = self._make_player()
        result = identity.name("x" * 51)
        self.assertEqual(result["type"], "error")
        self.assertIn("50", result["message"])

    def test_name_valid(self):
        """Test that valid name is accepted."""
        entity, identity = self._make_player()
        result = identity.name("Thornwick")
        self.assertEqual(result["type"], "name_changed")
        self.assertEqual(result["new_name"], "Thornwick")
        self.assertEqual(entity.name, "Thornwick")

    def test_name_history_tracked(self):
        """Test that name changes are tracked in history."""
        _, identity = self._make_player(name="original")
        identity.name("Thornwick")
        history = identity.data.get("name_history", [])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["old_name"], "original")
        self.assertEqual(history[0]["new_name"], "Thornwick")

    def test_name_history_capped(self):
        """Test that name history is capped at 100 entries."""
        _, identity = self._make_player(name="start")
        for i in range(105):
            identity.name(f"name{i}")
        history = identity.data.get("name_history", [])
        self.assertEqual(len(history), 100)
        # Oldest should be gone
        self.assertEqual(history[0]["new_name"], "name5")
        self.assertEqual(history[-1]["new_name"], "name104")

    def test_describe_empty_rejected(self):
        """Test that empty description is rejected."""
        _, identity = self._make_player()
        result = identity.describe("")
        self.assertEqual(result["type"], "error")
        self.assertIn("what", result["message"].lower())

    def test_describe_valid(self):
        """Test that description is set."""
        _, identity = self._make_player()
        desc = "A gaunt humanoid in grey robes."
        result = identity.describe(desc)
        self.assertEqual(result["type"], "description_updated")
        self.assertEqual(identity.data["description"], desc)

    def test_describe_truncated(self):
        """Test that description over 1000 chars is truncated."""
        _, identity = self._make_player()
        long_desc = "x" * 1500
        result = identity.describe(long_desc)
        self.assertEqual(len(identity.data["description"]), 1000)

    def test_appearance_list_empty(self):
        """Test listing appearance when none set."""
        _, identity = self._make_player()
        result = identity.appearance()
        self.assertEqual(result["type"], "appearance")
        self.assertEqual(result["attributes"], {})

    def test_appearance_set_attribute(self):
        """Test setting an appearance attribute."""
        _, identity = self._make_player()
        result = identity.appearance("race", "Elf")
        self.assertEqual(result["type"], "appearance_updated")
        self.assertEqual(result["attributes"]["race"], "Elf")

    def test_appearance_clear_attribute(self):
        """Test clearing an appearance attribute."""
        _, identity = self._make_player()
        identity.appearance("race", "Elf")
        result = identity.appearance("race", "")
        self.assertEqual(result["type"], "appearance_updated")
        self.assertNotIn("race", result["attributes"])

    def test_appearance_invalid_key_rejected(self):
        """Test that invalid attribute key is rejected."""
        _, identity = self._make_player()
        result = identity.appearance("123invalid", "value")
        self.assertEqual(result["type"], "error")

    def test_appearance_max_attributes(self):
        """Test that max 20 attributes is enforced."""
        _, identity = self._make_player()
        for i in range(21):
            result = identity.appearance(f"attr{i}", f"value{i}")
        # 21st should fail
        self.assertEqual(result["type"], "error")
        self.assertIn("maximum", result["message"].lower())

    def test_shortdesc_valid(self):
        """Test setting short description."""
        _, identity = self._make_player()
        result = identity.shortdesc("A weathered wanderer.")
        self.assertEqual(result["type"], "shortdesc_updated")
        self.assertEqual(identity.data["short_description"], "A weathered wanderer.")

    def test_shortdesc_truncated(self):
        """Test short description truncation."""
        _, identity = self._make_player()
        result = identity.shortdesc("x" * 150)
        self.assertEqual(len(identity.data["short_description"]), 100)

    def test_title_set(self):
        """Test setting a title."""
        _, identity = self._make_player()
        identity.name("Thornwick")
        result = identity.title("the Grey")
        self.assertEqual(result["type"], "title_updated")
        self.assertEqual(result["title"], "the Grey")
        self.assertIn("Thornwick", result["full_display"])

    def test_title_clear(self):
        """Test clearing a title."""
        _, identity = self._make_player()
        identity.name("Thornwick")
        identity.title("the Grey")
        result = identity.title("")
        self.assertEqual(result["type"], "title_updated")
        self.assertEqual(result["title"], "")

    def test_title_truncated(self):
        """Test title truncation."""
        _, identity = self._make_player()
        identity.name("Test")
        result = identity.title("x" * 60)
        self.assertEqual(len(identity.data["title"]), 50)

    def test_profile_self(self):
        """Test viewing own profile."""
        _, identity = self._make_player(name="Original")
        identity.name("Thornwick")
        identity.describe("A wanderer.")
        identity.appearance("race", "Human")
        result = identity.profile()
        self.assertEqual(result["type"], "profile")
        self.assertEqual(result["name"], "Thornwick")
        self.assertEqual(result["description"], "A wanderer.")
        self.assertEqual(result["attributes"]["race"], "Human")

    def test_profile_self_heal(self):
        """Test that profile self-heals Entity.name."""
        entity, identity = self._make_player(name="Original")
        identity.data["display_name"] = "FixedName"
        identity.data["created_at"] = 1234567890
        identity._save()
        # Entity still has old name
        entity.name = "Original"
        entity._save()
        # Load fresh
        identity2 = entity.aspect("Identity")
        result = identity2.profile()
        # Should have corrected entity name
        self.assertEqual(entity.name, "FixedName")

    def test_inspect_self_redirects_to_profile(self):
        """Test that inspecting self redirects to profile."""
        entity, identity = self._make_player()
        result = identity.inspect(entity.uuid)
        self.assertEqual(result["type"], "profile")

    def test_inspect_no_target_uuid(self):
        """Test inspect with no target."""
        _, identity = self._make_player()
        result = identity.inspect("")
        self.assertEqual(result["type"], "error")

    def test_inspect_target_not_found(self):
        """Test inspect with non-existent target."""
        _, identity = self._make_player()
        result = identity.inspect("does-not-exist")
        self.assertEqual(result["type"], "error")

    def test_inspect_target_different_location(self):
        """Test inspect target at different location."""
        entity1, identity1 = self._make_player(location="room-1")
        entity2, _ = self._make_player(name="Other", location="room-2")
        result = identity1.inspect(entity2.uuid)
        self.assertEqual(result["type"], "error")
        self.assertIn("can't see", result["message"].lower())

    def test_inspect_target_no_identity(self):
        """Test inspecting entity without Identity aspect."""
        from aspects.thing import Entity

        entity1, identity1 = self._make_player(location="room-1")
        # Create another entity without Identity
        entity2 = Entity()
        entity2.data["name"] = "OtherPlayer"
        entity2.data["location"] = "room-1"
        entity2.data["aspects"] = ["Inventory"]
        entity2.data["primary_aspect"] = "Inventory"
        entity2._save()

        result = identity1.inspect(entity2.uuid)
        self.assertEqual(result["type"], "inspect")
        self.assertEqual(result["name"], "OtherPlayer")

    def test_inspect_target_with_identity(self):
        """Test inspecting entity with full Identity."""
        from aspects.identity import Identity

        entity1, identity1 = self._make_player(location="room-1")
        # Create another entity with Identity
        entity2 = Entity()
        entity2.data["name"] = "OtherPlayer"
        entity2.data["location"] = "room-1"
        entity2.data["aspects"] = ["Identity"]
        entity2.data["primary_aspect"] = "Identity"
        entity2._save()

        identity2 = Identity()
        identity2.data["uuid"] = entity2.uuid
        identity2.data["display_name"] = "Thornwick"
        identity2.data["title"] = "the Wise"
        identity2.data["description"] = "An old wizard."
        identity2.data["attributes"] = {"race": "Human", "build": " gaunt"}
        identity2._save()
        identity2.entity = entity2

        result = identity1.inspect(entity2.uuid)
        self.assertEqual(result["type"], "inspect")
        self.assertEqual(result["name"], "Thornwick")
        self.assertEqual(result["title"], "the Wise")
        self.assertIn("old wizard", result["description"])

    def test_sync_entity_name_callable(self):
        """Test the _sync_entity_name callable."""
        _, identity = self._make_player(name="Original")
        result = identity._sync_entity_name("SyncedName")
        self.assertEqual(result["status"], "synced")
        self.assertEqual(identity.entity.name, "SyncedName")

    def test_on_equipment_change_callable(self):
        """Test the on_equipment_change callable."""
        _, identity = self._make_player()
        result = identity.on_equipment_change("Wielding a sword.", [{"slot": "hand", "name": "sword"}])
        self.assertEqual(result["status"], "updated")
        self.assertEqual(identity.data["equipment_summary"], "Wielding a sword.")


if __name__ == "__main__":
    unittest.main()