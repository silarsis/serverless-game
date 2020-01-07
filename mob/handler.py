import json
import log
import boto3
from os import environ
from contextlib import contextmanager

from mob import Mob

table = boto3.resource('dynamodb').Table(environ.get('MOB_TABLE'))


class Action():
    def __init__(self, mob: Mob, action: str, event: dict):
        self.mob = mob
        self.event = event
        getattr(self, action)()

    def create(self):
        log.debug("creating a new mob")
        if self.event['type'] == 'Mob':
            new_mob = Mob({})
        else:
            raise TypeError(self.event)
        table.put_item(Item=new_mob)


@contextmanager
def thing(mob_uuid: str):
    data = table.get_item(Key={'uuid': mob_uuid}).get('Item', {})
    if data['type'] == 'Mob':
        mob = Mob(data)
    else:
        raise TypeError(data)
    yield mob
    if mob.dirty:
        table.put_item(Item=mob.data)


def ingest_event(event: dict):
    with thing(event['target_uuid']) as mob:
        Action(mob, event['action'], event)


def lambda_handler(event: dict, context: dict):
    print("Received event: " + json.dumps(event, indent=2))
    return [ingest_event(e['Sns']['Message']) for e in event['Records']]
