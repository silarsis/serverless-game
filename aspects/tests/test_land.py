import unittest
from moto import mock_dynamodb2
from aspects.land import Land
from os import environ
import boto3


environ['LAND_TABLE'] = 'test_land_table'


class TestLand(unittest.TestCase):
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
                    'AttributeName': 'Land',
                    'AttributeType': 'S'
                },
                {
                    'AttributeName': 'coordinates',
                    'AttributeType': 'L'
                }
            ],
            TableName=environ['LAND_TABLE'],
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
                            'AttributeName': 'Land',
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
                },
                {
                    'IndexName': 'cartesian',
                    'KeySchema': [
                        {
                            'AttributeName': 'coordinates',
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

    def tearDown(self):
        [mock.stop() for mock in self.mocks]

    def test_init(self):
        loc = Land()
        self.assertEqual(Land(uuid=loc.uuid).uuid, loc.uuid)

    def test_add_exits(self):
        loc = Land()
        loc.coordinates = (0, 0, 0)
        north_loc = Land()
        north_loc.coordinates = (0, 1, 0)
        south_loc = Land()
        self.assertEqual(loc.exits, {})
        loc.add_exit('north', north_loc.uuid)
        self.assertEqual(loc.exits, {'north': north_loc.uuid})
        loc.add_exit('south', south_loc.uuid)
        self.assertEqual(loc.exits, {'north': north_loc.uuid, 'south': south_loc.uuid})
        exits = loc.add_exit('west', None)
        west_loc = Land(uuid=exits['west'])
        self.assertEqual(west_loc.coordinates, (-1, 0, 0))

    def test_remove_exits(self):
        loc = Land()
        loc.coordinates = (0, 0, 0)
        self.assertEqual(loc.exits, {})
        loc.remove_exit('north')
        self.assertEqual(loc.exits, {})
        exits = loc.add_exit('north', None)
        north_loc = Land(uuid=exits['north'])
        self.assertEqual(loc.exits, {'north': north_loc.uuid})
        self.assertEqual(north_loc.coordinates, (0, 1, 0))
        loc.remove_exit('north')
        self.assertEqual(loc.exits, {})

    def test_by_coordinates(self):
        loc_uuid = Land.by_coordinates((0, 0, 0))
        new_loc_uuid = Land.by_coordinates((0, 0, 0))
        self.assertEqual(loc_uuid, new_loc_uuid)

    def test_post_linkage(self):
        loc_uuid = Land.by_coordinates((0, 0, 0))
        north_loc_uuid = Land.by_coordinates((0, 1, 0))
        Land(uuid=loc_uuid).add_exit('north', None)
        self.assertEqual(Land(uuid=loc_uuid).exits['north'], north_loc_uuid)

    def test_by_direction(self):
        loc_uuid = Land.by_coordinates((0, 0, 0))
        new_loc_uuid = Land(uuid=loc_uuid).by_direction('north')
        Land(uuid=loc_uuid).add_exit('north', None)
        self.assertEqual(Land(uuid=loc_uuid).exits['north'], new_loc_uuid)
