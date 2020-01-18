from .thing import Thing
import boto3
from boto3.dynamodb.conditions import Key
import logging
from .handler import lambdaHandler


class Location(Thing):
    " All location aware things will have a Location mixin "
    _tableName = 'LOCATION_TABLE'

    def __init__(self, uuid: str = None, tid: str = None):
        super().__init__(uuid, tid)
        self._contents = boto3.resource('dynamodb').Table('CONTENTS_TABLE')
        self._condition = Key('uuid').eq(self.uuid)

    @property
    def exits(self) -> dict:
        return self.data['exits']

    @exits.setter
    def exits(self, value: dict):
        self.data['exits'] = value
        self.dirty = True

    def add_exit(self, direction: str, destination: str):
        self.data['exits'][direction] = destination
        self.dirty = True

    @property
    def contents(self):
        c = self._contents.query(KeyConditionExpression=self._condition)
        return [item['contains'] for item in c['Items']]

    @contents.setter
    def contents(self, value: list):
        raise AttributeError("Should not set contents - arrive and leave items")

    def arrive(self):
        actor_uuid = self.event['actor_uuid']
        self._content.put_item(
            Item={'uuid': self.uuid, 'contains': actor_uuid})
        logging.debug("{} has arrived in {}".format(actor_uuid, self.uuid))

    def left(self):
        actor_uuid = self.event['actor_uuid']
        self._content.delete_item(
            Key={'uuid': self.uuid, 'contains': actor_uuid})
        logging.debug("{} has left {}".format(actor_uuid, self.uuid))

    def create(self):
        self.exits = {}
        super().create()

    def destroy(self):
        for uuid in self.contents:
            self.tell('mob', uuid).to('leave', location=self.uuid)


handler = lambdaHandler(Location)
