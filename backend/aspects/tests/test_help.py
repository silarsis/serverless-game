"""Tests for the help command on Entity with aspects.

Help now lives on Entity and scans all aspects for @player_command methods.
Tests create Entity records with aspect lists and call entity.help().
"""

import os

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def dynamodb():
    """Set up mock DynamoDB tables."""
    with mock_aws():
        os.environ["ENTITY_TABLE"] = "entity-table-test"
        os.environ["LAND_TABLE"] = "land-table-test"
        os.environ["LOCATION_TABLE"] = "location-table-test"

        client = boto3.resource("dynamodb", region_name="ap-southeast-1")

        # Entity table with contents GSI
        client.create_table(
            TableName="entity-table-test",
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

        # Land aspect table with cartesian GSI
        client.create_table(
            TableName="land-table-test",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
                {"AttributeName": "coordinates", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
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

        # Location aspect table
        client.create_table(
            TableName="location-table-test",
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
        )

        yield client


def _make_entity_with_aspects(aspects, primary=None):
    """Create an Entity with the given aspects list."""
    from aspects.thing import Entity

    entity = Entity()
    entity.data["aspects"] = aspects
    entity.data["primary_aspect"] = primary or (aspects[0] if aspects else "")
    entity._save()
    return entity


class TestHelp:
    """Tests for the help command on Entity."""

    def test_help_on_land_entity(self, dynamodb):
        """Help on an entity with Land aspect should list look, move."""
        entity = _make_entity_with_aspects(["Land"])

        result = entity.help()
        assert result["type"] == "help"
        assert isinstance(result["commands"], list)
        assert len(result["commands"]) > 0

        # Should include look and move from Land
        cmd_names = [c["name"] for c in result["commands"]]
        assert "look" in cmd_names
        assert "move" in cmd_names
        # help itself should be listed
        assert "help" in cmd_names

    def test_help_on_communication_entity(self, dynamodb):
        """Help on an entity with Communication aspect should include say, whisper, emote."""
        entity = _make_entity_with_aspects(["Communication"])

        result = entity.help()
        assert result["type"] == "help"

        cmd_names = [c["name"] for c in result["commands"]]
        assert "say" in cmd_names
        assert "whisper" in cmd_names
        assert "emote" in cmd_names

    def test_help_on_inventory_entity(self, dynamodb):
        """Help on an entity with Inventory aspect should include take, drop, etc."""
        entity = _make_entity_with_aspects(["Inventory"])

        result = entity.help()
        assert result["type"] == "help"

        cmd_names = [c["name"] for c in result["commands"]]
        assert "take" in cmd_names
        assert "drop" in cmd_names
        assert "examine" in cmd_names
        assert "inventory" in cmd_names

    def test_help_multi_aspect_entity(self, dynamodb):
        """Help on a player entity with multiple aspects should include all commands."""
        entity = _make_entity_with_aspects(
            ["Land", "Inventory", "Communication"], primary="Land"
        )

        result = entity.help()
        assert result["type"] == "help"

        cmd_names = [c["name"] for c in result["commands"]]
        # Land commands
        assert "look" in cmd_names
        assert "move" in cmd_names
        # Inventory commands
        assert "take" in cmd_names
        assert "drop" in cmd_names
        # Communication commands
        assert "say" in cmd_names
        assert "whisper" in cmd_names

    def test_help_detail_known_command(self, dynamodb):
        """Help with a specific command name should return its docstring."""
        entity = _make_entity_with_aspects(["Land"])

        result = entity.help(command="look")
        assert result["type"] == "help_detail"
        assert result["command"] == "look"
        assert "Look around" in result["description"]

    def test_help_detail_unknown_command(self, dynamodb):
        """Help with an unknown command should return an error."""
        entity = _make_entity_with_aspects(["Land"])

        result = entity.help(command="fly")
        assert result["type"] == "error"
        assert "Unknown command" in result["message"]

    def test_help_has_summaries(self, dynamodb):
        """Each command in help output should have a summary."""
        entity = _make_entity_with_aspects(["Land"])

        result = entity.help()
        for cmd in result["commands"]:
            assert "name" in cmd
            assert "summary" in cmd
            assert len(cmd["summary"]) > 0
