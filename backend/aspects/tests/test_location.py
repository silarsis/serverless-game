"""Tests for Location aspect module.

Location is now a thin Aspect subclass that owns exit management.
Shared fields (location, contents) live on Entity.
"""

import unittest
from os import environ

import boto3
from moto import mock_aws

from aspects.location import Location
from aspects.thing import Entity

environ["ENTITY_TABLE"] = "test-entity-table"
environ["LOCATION_TABLE"] = "test_location_table"
environ["AWS_DEFAULT_REGION"] = "ap-southeast-1"


class TestLocation(unittest.TestCase):
    """Unit tests for the Location aspect."""

    def setUp(self):
        """Set up mocked DynamoDB resources for testing."""
        self.mock = mock_aws()
        self.mock.start()
        db = boto3.resource("dynamodb")

        # Entity table with contents GSI
        db.create_table(
            TableName=environ["ENTITY_TABLE"],
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

        # Location aspect table
        db.create_table(
            TableName=environ["LOCATION_TABLE"],
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )

    def tearDown(self):
        """Tear down mocked resources after testing."""
        self.mock.stop()

    def test_init(self):
        """Test initialization of Location aspect."""
        loc = Location()
        loc._save()
        self.assertEqual(Location(uuid=loc.uuid).uuid, loc.uuid)

    def test_add_exits(self):
        """Test adding exits to a Location aspect."""
        loc = Location()
        north_loc = Location()
        south_loc = Location()
        self.assertEqual(loc.exits, {})
        loc.add_exit("north", north_loc.uuid)
        self.assertEqual(loc.exits, {"north": north_loc.uuid})
        loc.add_exit("south", south_loc.uuid)
        self.assertEqual(loc.exits, {"north": north_loc.uuid, "south": south_loc.uuid})

    def test_remove_exits(self):
        """Test removing exits from a Location aspect."""
        loc = Location()
        self.assertEqual(loc.exits, {})
        loc.remove_exit("north")
        self.assertEqual(loc.exits, {})
        north_loc = Location()
        loc.add_exit("north", north_loc.uuid)
        self.assertEqual(loc.exits, {"north": north_loc.uuid})
        loc.remove_exit("north")
        self.assertEqual(loc.exits, {})

    def test_set_location_on_entity(self):
        """Test setting the container location for an Entity (shared field)."""
        # Location/contents now live on Entity, not on Location aspect
        entity = Entity()
        entity._save()
        container = Entity()
        container._save()
        entity.location = container.uuid
        self.assertEqual(entity.location, container.uuid)
        self.assertEqual(container.contents, [entity.uuid])

    def test_reset_location_on_entity(self):
        """Test resetting the container location for an Entity."""
        entity = Entity()
        entity._save()
        first_container = Entity()
        first_container._save()
        second_container = Entity()
        second_container._save()
        entity.location = first_container.uuid
        self.assertEqual(entity.location, first_container.uuid)
        entity.location = second_container.uuid
        self.assertEqual(entity.location, second_container.uuid)
        self.assertEqual(first_container.contents, [])
        self.assertEqual(second_container.contents, [entity.uuid])
