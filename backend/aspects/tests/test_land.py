"""Tests for Land aspect module."""

import unittest
from os import environ

import boto3
from moto import mock_dynamodb

from aspects.land import Land

environ["LAND_TABLE"] = "test_land_table"
environ["AWS_DEFAULT_REGION"] = "ap-southeast-1"


class TestLand(unittest.TestCase):
    """Unit tests for the Land aspect."""

    def setUp(self):
        """Set up mocked DynamoDB resources for testing."""
        self.mocks = [mock_dynamodb()]
        [mock.start() for mock in self.mocks]
        boto3.resource(
            "dynamodb"
        ).create_table(  # TODO: Can we extract this from yaml and generate it?
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
                {"AttributeName": "Land", "AttributeType": "S"},
                {"AttributeName": "coordinates", "AttributeType": "S"},
            ],
            TableName=environ["LAND_TABLE"],
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "contents",
                    "KeySchema": [
                        {"AttributeName": "Land", "KeyType": "HASH"},
                        {"AttributeName": "uuid", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                },
                {
                    "IndexName": "cartesian",
                    "KeySchema": [
                        {"AttributeName": "coordinates", "KeyType": "HASH"},
                        {"AttributeName": "uuid", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                },
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
        )

    def tearDown(self):
        """Tear down mocked resources after testing."""
        [mock.stop() for mock in self.mocks]

    def test_init(self):
        """Test initialization of Land object."""
        loc = Land()
        self.assertEqual(Land(uuid=loc.uuid).uuid, loc.uuid)

    def test_add_exits(self):
        """Test adding exits to a Land object."""
        loc = Land()
        loc.coordinates = (0, 0, 0)
        north_loc = Land()
        north_loc.coordinates = (0, 1, 0)
        south_loc = Land()
        self.assertEqual(loc.exits, {})
        loc.add_exit("north", north_loc.uuid)
        self.assertEqual(
            loc.exits,
            {"north": north_loc.uuid},
        )
        loc.add_exit("south", south_loc.uuid)
        self.assertEqual(
            loc.exits,
            {
                "north": north_loc.uuid,
                "south": south_loc.uuid,
            },
        )

        exits = loc.add_exit("west", None)
        west_loc = Land(uuid=exits["west"])
        self.assertEqual(
            west_loc.coordinates,
            (-1, 0, 0),
        )

    def test_remove_exits(self):
        """Test removing exits from a Land object."""
        loc = Land()
        loc.coordinates = (0, 0, 0)
        self.assertEqual(loc.exits, {})
        loc.remove_exit("north")
        self.assertEqual(loc.exits, {})
        exits = loc.add_exit("north", None)
        north_loc = Land(uuid=exits["north"])
        self.assertEqual(
            loc.exits,
            {"north": north_loc.uuid},
        )

        self.assertEqual(
            north_loc.coordinates,
            (0, 1, 0),
        )

        loc.remove_exit("north")
        self.assertEqual(loc.exits, {})

    def test_by_coordinates(self):
        """Test that Land.by_coordinates returns consistent UUID for same coordinates."""
        loc_uuid = Land.by_coordinates((0, 0, 0))
        new_loc_uuid = Land.by_coordinates((0, 0, 0))
        self.assertEqual(loc_uuid, new_loc_uuid)

    def test_post_linkage(self):
        """Test that after linkage, exit points to the computed location."""
        loc_uuid = Land.by_coordinates((0, 0, 0))
        north_loc_uuid = Land.by_coordinates((0, 1, 0))
        Land(uuid=loc_uuid).add_exit("north", None)
        self.assertEqual(
            Land(uuid=loc_uuid).exits["north"],
            north_loc_uuid,
        )

    def test_by_direction(self):
        """Test that by_direction creates or finds the correct location."""
        loc_uuid = Land.by_coordinates((0, 0, 0))
        new_loc_uuid = Land(uuid=loc_uuid).by_direction("north")
        Land(uuid=loc_uuid).add_exit("north", None)
        self.assertEqual(
            Land(uuid=loc_uuid).exits["north"],
            new_loc_uuid,
        )
