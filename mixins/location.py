from .thing import Thing
import boto3
from boto3.dynamodb.conditions import Key
import logging
from .handler import lambdaHandler


class Location(Thing):
    _tableName = 'LOCATION_TABLE'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
        return c['Items']

    @contents.setter
    def contents(self, value: list):
        raise AttributeError("Cannot set contents")

    def arrive(self):
        source_uuid = self.event['source_uuid']
        logging.debug("{} has arrived in {}".format(source_uuid, self.uuid))

    def leave(self):
        source_uuid = self.event['source_uuid']
        logging.debug("{} has left {}".format(source_uuid, self.uuid))


handler = lambdaHandler(Location)
