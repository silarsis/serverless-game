from .thing import Thing
import boto3
from boto3.dynamodb.conditions import Key
import logging
from .handler import lambdaHandler
from typing import List, Dict


class Location(Thing):
    " All location aware things will have a Location aspect "
    _tableName = 'LOCATION_TABLE'

    def __init__(self, uuid: str = None, tid: str = None):
        super().__init__(uuid, tid)
        self._contents = boto3.resource('dynamodb').Table('CONTENTS_TABLE')
        self._locations = boto3.resource('dynamodb').Table('LOCATIONS_TABLE')
        self._condition = Key('uuid').eq(self.uuid)

    @property
    def exits(self) -> Dict[str, str]:
        return self.data['exits']

    def add_exit(self, direction: str, destination: str) -> Dict[str, str]:
        self.data['exits'][direction] = destination
        self.dirty = True
        return self.data['exits']

    def remove_exit(self, direction: str) -> Dict[str, str]:
        if direction in self.data['exits']:
            del(self.data['exits'][direction])
            self.dirty = True
        return self.data['exits']

    @property
    def contents(self) -> List[str]:
        contents = self._contents.query(KeyConditionExpression=self._condition)
        return [item['contains'] for item in contents['Items']]

    def add_contents(self, value: str) -> None:
        self._contents.put_item(
            Item={'uuid': self.uuid, 'contains': value}
        )
        logging.debug("{} now contains {}".format(self.uuid, value))

    def remove_contents(self, value: str) -> None:
        self._contents.delete_item(
            Key={'uuid': self.uuid, 'contains': value}
        )
        logging.debug("{} no longer contains {}".format(self.uuid, value))

    @property
    def locations(self) -> List[str]:
        locations = self._locations.get_item(KeyConditionExpression=self._condition)
        return [item['location'] for item in locations['Items']]

    def add_location(self, value: str):
        self._locations.put_item(
            Item={'uuid': self.uuid, 'location': value}
        )
        logging.debug("{} is now located in {}".format(self.uuid, value))

    def remove_location(self, value: str):
        self._locations.delete_item(
            Key={'uuid': self.uuid, 'location': value}
        )
        logging.debug("{} is no longer located in {}".format(self.uuid, value))

    def move(self, from_loc: str, to_loc: str):
        self.add_location(to_loc)
        self.remove_location(from_loc)

    def create(self):
        self.data['exits'] = {}
        super().create()

    def destroy(self):
        for uuid in self.contents:
            self.tell('mob', uuid).to('leave', location=self.uuid)


handler = lambdaHandler(Location)
