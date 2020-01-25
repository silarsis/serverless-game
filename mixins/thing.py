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


class Call(UserDict):
    def __init__(self, tid: str, originator: IdType, uuid: IdType, aspect: str, action: str, **kwargs):
        self._topic = boto3.resource('sns').Topic(environ['THING_TOPIC'])
        self._originating_uuid = originator
        self._data['tid'] = tid
        self._data['aspect'] = aspect
        self._data['uuid'] = uuid
        self._data['action'] = action
        self._data['data'] = kwargs

    def thenCall(self, aspect: str, action: str, uuid: IdType, **kwargs: Dict) -> 'Call':
        assert(self._originating_uuid)
        callback = {
            'tid': self['tid'],
            'aspect': aspect,
            'action': action,
            'uuid': self._originating_uuid,
            'data': kwargs
        }
        d = self._data
        while 'callback' in d:
            d = d['callback']
        d['callback'] = callback
        return self

    def now(self) -> None:
        return self._topic.publish(
            Message=json.dumps(self._data),
            MessageStructure='json'
        )

    def after(self, seconds: int = 0) -> None:
        return self._topic.publish(
            Message=json.dumps(self._data),
            MessageStructure='json'
            # TODO: Add the step function delayer and use that
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
        if 'tick_delay' in self.data:
            return self.data['tick_delay']
        return 30

    @property
    def _table(self):
        return boto3.resource('dynamodb').Table(environ[self._tableName])

    def create(self) -> None:
        self._save()

    def destroy(self) -> None:
        self._table.delete_item(Key={'uuid': self.uuid})
        logging.debug("{} has been destroyed".format(self.uuid))

    def tick(self) -> None:
        self.schedule_next_tick()

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
        uuid = event['uuid']
        tid = str(event.get('tid') or uuid4())
        actor = cls(uuid, tid)
        response: EventType = getattr(actor, event['action'])(**event['data'])
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
        topic = boto3.resource('sns').Topic(environ['THING_TOPIC'])
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
