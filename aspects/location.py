from aspects.thing import Thing, IdType, callable
import boto3
from os import environ
from boto3.dynamodb.conditions import Key
from aspects.handler import lambdaHandler
from typing import List, Dict, Optional


ExitsType = Dict[str, IdType]


class Location(Thing):
    " All location aware things will have a Location aspect "
    _tableName = 'LOCATION_TABLE'

    def __init__(self, uuid: IdType = None, tid: str = None):
        super().__init__(uuid, tid)
        self._locationsTable = boto3.resource('dynamodb').Table(environ['LOCATIONS_TABLE'])
        self._locationCondition = Key('uuid').eq(self.uuid)
        self._contentsCondition = Key('location').eq(self.uuid)

    @property
    def exits(self) -> ExitsType:
        return self.data['exits']

    @callable
    def add_exit(self, direction: str, destination: IdType) -> ExitsType:
        self.data['exits'][direction] = destination
        self._save()
        return self.data['exits']

    @callable
    def remove_exit(self, direction: str) -> ExitsType:
        if direction in self.data['exits']:
            del(self.data['exits'][direction])
            self._save()
        return self.data['exits']

    @property
    def contents(self) -> List[IdType]:
        return [  # TODO: factor this out to deal with large response sets
            item['uuid']
            for item in self._locationsTable.query(
                IndexName='contents',
                Select='ALL_PROJECTED_ATTRIBUTES',
                KeyConditionExpression=self._contentsCondition
            )['Items']
        ]

    @property
    def location(self) -> Optional[IdType]:
        return self._locationsTable.get_item(Key={'uuid': self.uuid}).get('Item', {})['location']

    @location.setter
    def location(self, loc_id: IdType):
        print("set location {}".format(loc_id))
        self._locationsTable.put_item(Item={'uuid': self.uuid, 'location': loc_id})

    @callable
    def create(self) -> None:
        self.data['exits'] = {}
        super().create()

    @callable
    def destroy(self):
        dest = self.location or 'Nowhere'  # TODO: Figure out a better location for dropping objects
        for item in self.contents:
            Location(item, self.tid).location = dest
        self.location = 'Destroyed'


handler = lambdaHandler(Location)
