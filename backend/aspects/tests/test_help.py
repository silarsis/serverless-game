"""Tests for the help command on Thing and subclasses."""

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def dynamodb():
    """Set up mock DynamoDB tables."""
    with mock_aws():
        import os

        os.environ["LAND_TABLE"] = "land-table-test"
        os.environ["LOCATION_TABLE"] = "location-table-test"
        os.environ["THING_TABLE"] = "thing-table-test"

        client = boto3.resource("dynamodb", region_name="ap-southeast-1")

        # Thing table
        client.create_table(
            TableName="thing-table-test",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "uuid", "AttributeType": "S"}],
            ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
        )

        # Location table
        client.create_table(
            TableName="location-table-test",
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
                        "ReadCapacityUnits": 1,
                        "WriteCapacityUnits": 1,
                    },
                }
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
        )

        # Land table
        client.create_table(
            TableName="land-table-test",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
                {"AttributeName": "location", "AttributeType": "S"},
                {"AttributeName": "coordinates", "AttributeType": "S"},
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
                        "ReadCapacityUnits": 1,
                        "WriteCapacityUnits": 1,
                    },
                },
                {
                    "IndexName": "cartesian",
                    "KeySchema": [
                        {"AttributeName": "coordinates", "KeyType": "HASH"},
                        {"AttributeName": "uuid", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                    "ProvisionedThroughput": {
                        "ReadCapacityUnits": 1,
                        "WriteCapacityUnits": 1,
                    },
                },
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
        )

        yield client


class TestHelp:
    """Tests for the help command."""

    def test_help_on_land_returns_commands(self, dynamodb):
        """Help on a Land entity should list player commands like look, move."""
        from aspects.land import Land

        land = Land()
        land.coordinates = (0, 0, 0)

        result = land.help()
        assert result["type"] == "help"
        assert isinstance(result["commands"], list)
        assert len(result["commands"]) > 0

        # Should include look and move from Land
        cmd_names = [c["name"] for c in result["commands"]]
        assert "look" in cmd_names
        assert "move" in cmd_names
        # help itself should be listed
        assert "help" in cmd_names

    def test_help_on_communication_includes_say(self, dynamodb):
        """Help on a Communication entity should include say, whisper, emote."""
        from aspects.communication import Communication

        entity = Communication()
        result = entity.help()
        assert result["type"] == "help"

        cmd_names = [c["name"] for c in result["commands"]]
        assert "say" in cmd_names
        assert "whisper" in cmd_names
        assert "emote" in cmd_names

    def test_help_on_inventory_includes_take(self, dynamodb):
        """Help on an Inventory entity should include take, drop, examine, inventory."""
        from aspects.inventory import Inventory

        entity = Inventory()
        result = entity.help()
        assert result["type"] == "help"

        cmd_names = [c["name"] for c in result["commands"]]
        assert "take" in cmd_names
        assert "drop" in cmd_names
        assert "examine" in cmd_names
        assert "inventory" in cmd_names

    def test_help_detail_known_command(self, dynamodb):
        """Help with a specific command name should return its docstring."""
        from aspects.land import Land

        land = Land()
        land.coordinates = (0, 0, 0)

        result = land.help(command="look")
        assert result["type"] == "help_detail"
        assert result["command"] == "look"
        assert "Look around" in result["description"]

    def test_help_detail_unknown_command(self, dynamodb):
        """Help with an unknown command should return an error."""
        from aspects.land import Land

        land = Land()
        land.coordinates = (0, 0, 0)

        result = land.help(command="fly")
        assert result["type"] == "error"
        assert "Unknown command" in result["message"]

    def test_help_has_summaries(self, dynamodb):
        """Each command in help output should have a summary."""
        from aspects.land import Land

        land = Land()
        land.coordinates = (0, 0, 0)

        result = land.help()
        for cmd in result["commands"]:
            assert "name" in cmd
            assert "summary" in cmd
            assert len(cmd["summary"]) > 0
