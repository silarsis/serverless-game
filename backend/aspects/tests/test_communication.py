"""Tests for the Communication aspect (say, whisper, emote)."""

import os
import unittest

from moto import mock_aws


@mock_aws
class TestCommunication(unittest.TestCase):
    """Test the Communication aspect."""

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

    def test_say_no_message(self):
        """Test say with empty message returns error."""
        from aspects.communication import Communication

        comm = Communication()
        comm.data["location"] = "some-location"
        result = comm.say(message="")
        assert result["type"] == "error"
        assert "Say what?" in result["message"]

    def test_say_no_location(self):
        """Test say when entity has no location."""
        from aspects.communication import Communication

        comm = Communication()
        comm.data["location"] = None
        result = comm.say(message="hello")
        assert result["type"] == "error"

    def test_say_success(self):
        """Test successful say command."""
        from aspects.communication import Communication

        comm = Communication()
        comm.data["location"] = "loc-123"
        comm.data["name"] = "TestPlayer"
        result = comm.say(message="Hello world!")
        assert result["type"] == "say_confirm"
        assert "Hello world!" in result["message"]

    def test_whisper_no_target(self):
        """Test whisper without target returns error."""
        from aspects.communication import Communication

        comm = Communication()
        result = comm.whisper(target_uuid="", message="secret")
        assert result["type"] == "error"

    def test_whisper_no_message(self):
        """Test whisper without message returns error."""
        from aspects.communication import Communication

        comm = Communication()
        result = comm.whisper(target_uuid="some-uuid", message="")
        assert result["type"] == "error"

    def test_emote_no_action(self):
        """Test emote without action returns error."""
        from aspects.communication import Communication

        comm = Communication()
        comm.data["location"] = "loc-123"
        result = comm.emote(action="")
        assert result["type"] == "error"

    def test_emote_success(self):
        """Test successful emote command."""
        from aspects.communication import Communication

        comm = Communication()
        comm.data["location"] = "loc-123"
        comm.data["name"] = "TestPlayer"
        result = comm.emote(action="waves cheerfully")
        assert result["type"] == "emote_confirm"
        assert "waves cheerfully" in result["message"]


if __name__ == "__main__":
    unittest.main()
