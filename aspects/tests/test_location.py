import unittest
from moto import mock_dynamodb2
from aspects.location import Location
from os import environ
import boto3


environ['LOCATION_TABLE'] = 'test_location_table'
environ['LOCATIONS_TABLE'] = 'test_locations_table'

mock_dynamodb2_instance = mock_dynamodb2()
mock_dynamodb2_instance.start()


class TestLocation(unittest.TestCase):
    def setUp(self):
        self.mocks = [mock_dynamodb2()]
        [mock.start() for mock in self.mocks]
        boto3.resource('dynamodb').create_table(  # TODO: Can we extract this from yaml and generate it?
            AttributeDefinitions=[
                {
                    'AttributeName': 'uuid',
                    'AttributeType': 'S'
                },
                {
                    'AttributeName': 'location',
                    'AttributeType': 'S'
                }
            ],
            TableName=environ['LOCATIONS_TABLE'],
            KeySchema=[
                {
                    'AttributeName': 'uuid',
                    'KeyType': 'HASH'
                }
            ],
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'contents',
                    'KeySchema': [
                        {
                            'AttributeName': 'location',
                            'KeyType': 'HASH'
                        },
                        {
                            'AttributeName': 'uuid',
                            'KeyType': 'RANGE'
                        }
                    ],
                    'Projection': {
                        'ProjectionType': 'KEYS_ONLY'
                    }
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 1,
                'WriteCapacityUnits': 1
            }
        )
        boto3.resource('dynamodb').create_table(
            AttributeDefinitions=[
                {
                    'AttributeName': 'uuid',
                    'AttributeType': 'S'
                }
            ],
            KeySchema=[
                {
                    'AttributeName': 'uuid',
                    'KeyType': 'HASH'
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 1,
                'WriteCapacityUnits': 1
            },
            TableName=environ['LOCATION_TABLE']
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
        loc.add_exit('north', north_loc.uuid)
        self.assertEqual(loc.exits, {'north': north_loc.uuid})
        loc.add_exit('south', south_loc.uuid)
        self.assertEqual(loc.exits, {'north': north_loc.uuid, 'south': south_loc.uuid})

    def test_remove_exits(self):
        loc = Location()
        self.assertEqual(loc.exits, {})
        loc.remove_exit('north')
        self.assertEqual(loc.exits, {})
        north_loc = Location()
        loc.add_exit('north', north_loc.uuid)
        self.assertEqual(loc.exits, {'north': north_loc.uuid})
        loc.remove_exit('north')
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
