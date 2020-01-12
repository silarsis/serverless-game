import json
import logging
import boto3
from os import environ
from contextlib import contextmanager

from location import Location
from overground import Overground

table = boto3.resource('dynamodb').Table(environ.get('LOC_TABLE'))


class Action():
    def __init__(self, loc: Location, action: str, event: dict):
        self.loc = loc
        self.event = event
        getattr(self, action)()

    def arrive(self):
        source_uuid = self.event['source_uuid']
        logging.debug("{} has arrived in {}".format(source_uuid, self.uuid))

    def leave(self):
        source_uuid = self.event['source_uuid']
        logging.debug("{} has left {}".format(source_uuid, self.uuid))

    def create(self):
        logging.debug("creating a new location")
        if self.event['type'] == 'Overground':
            new_loc = Overground({})
        else:
            raise TypeError(self.event)
        if 'back_direction' in self.event:
            new_loc.add_exit(self.event['back_direction'], self.loc.uuid)
        self.loc.add_exit(self.event['direction'], new_loc.uuid)
        table.put_item(Item=new_loc)


@contextmanager
def location(loc_uuid: str):
    data = table.get_item(Key={'uuid': loc_uuid}).get('Item', {})
    if data['type'] == 'Overground':
        loc = Overground(data)
    else:
        raise TypeError(data)
    yield loc
    if loc.dirty:
        table.put_item(Item=loc.data)


def ingest_event(event: dict):
    with location(event['target_uuid']) as loc:
        Action(loc, event['action'], event)


def lambda_handler(event: dict, context: dict):
    print("Received event: " + json.dumps(event, indent=2))
    return [ingest_event(e['Sns']['Message']) for e in event['Records']]
