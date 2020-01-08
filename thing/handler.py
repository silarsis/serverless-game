import json
import log
import boto3
from os import environ
from contextlib import contextmanager
from thing import Thing

table = boto3.resource('dynamodb').Table(environ.get('THING_TABLE'))


class Action():
    def __init__(self, target: Thing, action: str, event: dict):
        self.target = target
        self.event = event
        self.dispatch(action)
        getattr(self, action)()

    def dispatch(self, action: str):
        mixin, verb = action.split('.')
        if mixin in self.target.mixins:
            self.target.mixins[mixin](verb, self.event)

    def create(self):
        log.debug("creating a new thing")
        new_thing = Thing({})
        new_thing._save()


@contextmanager
def thing_state(uuid: str):
    " Retrieve from database, write to database "
    data = table.get_item(Key={'uuid': uuid}).get('Item', {})
    this_thing = Thing(data)
    yield this_thing
    this_thing._save()


def ingest_event(event: dict):
    with thing_state(event['target_uuid']) as target:
        Action(target, event['action'], event)


def handler(event: dict, context: dict):
    print(json.dumps(event, indent=2))
    return [ingest_event(e['Sns']['Message']) for e in event['Records']]
