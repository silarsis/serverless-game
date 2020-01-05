import json
import log
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
        log.debug("{} has arrived in {}".format(source_uuid, self.uuid))

    def leave(self):
        source_uuid = self.event['source_uuid']
        log.debug("{} has left {}".format(source_uuid, self.uuid))


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
