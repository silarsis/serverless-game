import boto3
from uuid import uuid4
import json
from os import environ
from typing import Dict, Any
from collections import UserDict
import logging
import importlib

EventType = Dict[str, Any]  # Actually needs to be json-able
IdType = str  # This is a UUID cast to a str, but I want to identify it for typing purposes


def callable(func):
    def wrapper(*args, **kwargs):
        logging.debug("Calling {} with {}, {}".format(str(func), str(args), str(kwargs)))
        result = func(*args, **kwargs)
        assert(isinstance(result, dict) or result is None)
        return result
    return wrapper


class Call(UserDict):
    def __init__(self, tid: str, originator: IdType, uuid: IdType, aspect: str, action: str, **kwargs):
        super().__init__()
        self._originating_uuid = originator
        self.data['tid'] = tid
        self.data['aspect'] = aspect
        self.data['uuid'] = uuid
        self.data['action'] = action
        self.data['data'] = kwargs

    def thenCall(self, aspect: str, action: str, uuid: IdType, **kwargs: Dict) -> 'Call':
        assert(self._originating_uuid)
        callback = {
            'tid': self['tid'],
            'aspect': aspect,
            'action': action,
            'uuid': self._originating_uuid,
            'data': kwargs
        }
        d = self.data
        while 'callback' in d:
            d = d['callback']
        d['callback'] = callback
        return self

    def now(self) -> None:
        sns = boto3.resource('sns').Topic(environ['THING_TOPIC_ARN'])
        logging.debug(self.data)
        return sns.publish(
            Message=json.dumps(self.data),
            MessageStructure='json',
            MessageAttributes={
                'aspect': {
                    'DataType': 'String',
                    'StringValue': self.data['aspect']
                }
            }
        )

    def after(self, seconds: int = 0) -> None:
        self.data['delay_seconds'] = seconds
        sfn = boto3.client('stepfunctions')
        return sfn.start_execution(
            stateMachineArn=environ['MESSAGE_DELAYER_ARN'],
            input=json.dumps({
                'delay_seconds': seconds,
                'data': self.data
            })
        )


class Thing(UserDict):
    " Thing objects have state (stored in dynamo) and know how to event and callback "
    _tableName: str = ''  # Set this in the subclass

    def __init__(self, uuid: IdType = None, tid: str = None):
        super().__init__()
        assert(self._tableName)
        self._tid: str = tid or str(uuid4())
        self.data['uuid'] = uuid or str(uuid4())
        if uuid:
            self._load(uuid)
        else:
            self.create()
        assert(self.data)
        assert(self.uuid)

    @property
    def tickDelay(self):
        if 'tick_delay' not in self.data:
            self.data['tick_delay'] = 30
            self._save()
        return self.data['tick_delay']

    @property
    def _table(self):
        return boto3.resource('dynamodb').Table(environ[self._tableName])

    @callable
    def create(self) -> None:
        self._save()

    @callable
    def destroy(self) -> None:
        self._table.delete_item(Key={'uuid': self.uuid})
        logging.debug("{} has been destroyed".format(self.uuid))

    @callable
    def tick(self) -> None:
        self.schedule_next_tick()

    @callable
    def schedule_next_tick(self) -> None:
        Call(str(uuid4()), self.uuid, self.uuid, self.aspectName, 'tick').after(seconds=self.tickDelay)

    def aspect(self, aspect: str) -> 'Thing':
        return getattr(importlib.import_module(aspect.lower()), aspect)(self.uuid, self.tid)

    @property
    def aspectName(self) -> str:
        return self.__class__.__name__

    def _load(self, uuid: IdType) -> None:
        self.data: Dict = self._table.get_item(Key={'uuid': uuid}).get('Item', {})
        if not self.data:
            raise KeyError("load for non-existent item {}".format(uuid))

    def _save(self) -> None:
        self._table.put_item(Item=self.data)

    @property
    def tid(self) -> str:
        return self._tid

    @property
    def uuid(self) -> IdType:
        return str(self.data['uuid'])

    @classmethod
    def _action(cls, event: EventType):  # This is not state related, this is the entry point for the object
        assert(not event['action'].startswith('_'))
        uuid = event.get('uuid')  # Allowing for no uuid for creation
        if not uuid:
            assert(event['action'] == 'create')
        tid = str(event.get('tid') or uuid4())
        actor = cls(uuid, tid)
        response: EventType = getattr(actor, event['action'])(**event.get('data', {}))
        if event.get('callback'):
            c = event['callback']
            data = c['data']
            data.update(response or {})
            Call(c['tid'], '', c['uuid'], c['aspect'], c['action'], **data).now()
        actor._save()

    # Below here are questionable for this class

    def _sendEvent(self, event: EventType) -> str:
        sendEvent: Dict = {
            'default': '',
            'tid': self.tid,
            'actor_uuid': self.data['uuid']
        }
        sendEvent.update(event or {})
        topic = boto3.resource('sns').Topic(environ['THING_TOPIC_ARN'])
        return topic.publish(
            Message=json.dumps(sendEvent),
            MessageStructure='json'
        )

    def call(self, uuid: IdType, aspect: str, action: str, **kwargs):
        " call('42', 'mobile', 'arrive', kwargs={'destination': '68'}).now() "
        return Call(self.tid, self.uuid, uuid, aspect, action, **kwargs)

    def callAspect(self, aspect: str, action: str, **kwargs):
        return self.call(self.uuid, aspect, action, **kwargs)

    def createAspect(self, aspect: str) -> None:
        self.call(self.uuid, aspect, 'create')
