"""Tests for the Communication aspect (say, whisper, emote).

Communication is now an Aspect subclass. Shared fields (name, location)
live on Entity. Tests create Entity records and wire them to Communication
aspects via the entity back-reference.
"""

import os
import unittest

from moto import mock_aws


@mock_aws
class TestCommunication(unittest.TestCase):
    """Test the Communication aspect."""

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

        # Location/Communication aspect table
        self.dynamodb.create_table(
            TableName="test-location",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )

    def _make_comm_with_entity(self, name="TestPlayer", location="loc-123"):
        """Helper: create an Entity + Communication aspect wired together."""
        from aspects.communication import Communication
        from aspects.thing import Entity

        entity = Entity()
        entity.data["name"] = name
        if location:
            entity.data["location"] = location
        entity.data["aspects"] = ["Communication"]
        entity.data["primary_aspect"] = "Communication"
        entity._save()

        comm = Communication()
        comm.data["uuid"] = entity.uuid  # sync UUIDs
        comm._save()
        comm.entity = entity
        return comm

    def test_say_no_message(self):
        """Test say with empty message returns error."""
        comm = self._make_comm_with_entity(location="some-location")
        result = comm.say(message="")
        assert result["type"] == "error"
        assert "Say what?" in result["message"]

    def test_say_no_location(self):
        """Test say when entity has no location."""
        comm = self._make_comm_with_entity(location=None)
        result = comm.say(message="hello")
        assert result["type"] == "error"

    def test_say_success(self):
        """Test successful say command."""
        comm = self._make_comm_with_entity(name="TestPlayer", location="loc-123")
        result = comm.say(message="Hello world!")
        assert result["type"] == "say_confirm"
        assert "Hello world!" in result["message"]

    def test_whisper_no_target(self):
        """Test whisper without target returns error."""
        comm = self._make_comm_with_entity()
        result = comm.whisper(target_uuid="", message="secret")
        assert result["type"] == "error"

    def test_whisper_no_message(self):
        """Test whisper without message returns error."""
        comm = self._make_comm_with_entity()
        result = comm.whisper(target_uuid="some-uuid", message="")
        assert result["type"] == "error"

    def test_emote_no_action(self):
        """Test emote without action returns error."""
        comm = self._make_comm_with_entity(location="loc-123")
        result = comm.emote(action="")
        assert result["type"] == "error"

    def test_emote_success(self):
        """Test successful emote command."""
        comm = self._make_comm_with_entity(name="TestPlayer", location="loc-123")
        result = comm.emote(action="waves cheerfully")
        assert result["type"] == "emote_confirm"
        assert "waves cheerfully" in result["message"]


if __name__ == "__main__":
    unittest.main()
