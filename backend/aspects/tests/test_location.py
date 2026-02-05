import unittest
from os import environ

import boto3
from moto import mock_dynamodb

from aspects.location import Location

environ["LOCATION_TABLE"] = "test_location_table"
environ["AWS_DEFAULT_REGION"] = "ap-southeast-1"


class TestLocation(unittest.TestCase):
    def setUp(self):
        self.mocks = [mock_dynamodb()]
        [mock.start() for mock in self.mocks]
        boto3.resource(
            "dynamodb"
        ).create_table(  # TODO: Can we extract this from yaml and generate it?
            AttributeDefinitions=[
                {"AttributeName": "uuid", "AttributeType": "S"},
                {"AttributeName": "location", "AttributeType": "S"},
            ],
            TableName=environ["LOCATION_TABLE"],
            KeySchema=[{"AttributeName": "uuid", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "contents",
                    "KeySchema": [
                        {"AttributeName": "location", "KeyType": "HASH"},
                        {"AttributeName": "uuid", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                }
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
        )

    def tearDown(self):
        [mock.stop() for mock in self.mocks]

    def test_init(self):
        loc = Location()
        self.assertEqual(Location(uuid=loc.uuid).uuid, loc.uuid)

    def test_add_exits(self):
        loc = Location()
        north_loc = Location()
        south_loc = Location()
        self.assertEqual(loc.exits, {})
        loc.add_exit("north", north_loc.uuid)
        self.assertEqual(loc.exits, {"north": north_loc.uuid})
        loc.add_exit("south", south_loc.uuid)
        self.assertEqual(loc.exits, {"north": north_loc.uuid, "south": south_loc.uuid})

    def test_remove_exits(self):
        loc = Location()
        self.assertEqual(loc.exits, {})
        loc.remove_exit("north")
        self.assertEqual(loc.exits, {})
        north_loc = Location()
        loc.add_exit("north", north_loc.uuid)
        self.assertEqual(loc.exits, {"north": north_loc.uuid})
        loc.remove_exit("north")
        self.assertEqual(loc.exits, {})

    def test_set_location(self):
        loc = Location()
        container = Location()
        loc.location = container.uuid
        self.assertEqual(loc.location, container.uuid)
        self.assertEqual(container.contents, [loc.uuid])

    def test_reset_location(self):
        loc = Location()
        first_container = Location()
        second_container = Location()
        loc.location = first_container.uuid
        self.assertEqual(loc.location, first_container.uuid)
        loc.location = second_container.uuid
        self.assertEqual(loc.location, second_container.uuid)
        self.assertEqual(first_container.contents, [])
        self.assertEqual(second_container.contents, [loc.uuid])
