import boto3
from uuid import uuid4
import json
from os import environ
from typing import Dict, Any
from collections import UserDict
import copy
import logging
import importlib

EventType = Dict[str, Any]  # Actually needs to be json-able


class Call(UserDict):
    def __init__(self, tid: str, originator: str, uuid: str, aspect: str, action: str, **kwargs):
        self._topic = boto3.resource('sns').Topic(environ['THING_TOPIC'])
        self._originating_uuid = originator
        self.data['tid'] = tid
        self.data['aspect'] = aspect
        self.data['uuid'] = uuid
        self.data['action'] = action
        self.data['data'] = kwargs

    def thencall(self, aspect: str, action: str, uuid: str, **kwargs: Dict):
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

    def now(self) -> None:
        return self._topic.publish(
            Message=json.dumps(self.data),
            MessageStructure='json'
        )


class Thing(UserDict):
    " Thing objects have state (stored in dynamo) and know how to event and callback "
    _tableName: str = ''  # Set this in the subclass

    def __init__(self, uuid: str = None, tid: str = None):
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
    def _table(self):
        return boto3.resource('dynamodb').Table(environ[self._tableName])

    @property
    def _topic(self):
        return boto3.resource('sns').Topic(environ['THING_TOPIC'])

    def create(self) -> None:
        self._save()

    def destroy(self) -> None:
        self._table.delete_item(Key={'uuid': self.uuid})
        logging.debug("{} has been destroyed".format(self.uuid))

    def tick(self) -> None:
        " This should be called as a super call at the start of tick "
        self._tid = str(uuid4())  # Each new tick is a new transaction

    def aspect(self, aspect: str):
        return getattr(importlib.import_module(aspect.lower()), aspect)(self.uuid, self.tid)

    def _load(self, uuid: str) -> None:
        self.data: Dict = self._table.get_item(Key={'uuid': uuid}).get('Item', {})
        if not self.data:
            raise KeyError("load for non-existent item {}".format(uuid))

    def _save(self) -> None:
        self._table.put_item(Item=self.data)

    @property
    def tid(self) -> str:
        return self._tid

    @property
    def uuid(self) -> str:
        return str(self.data['uuid'])

    def _sendEvent(self, event: EventType) -> str:
        sendEvent: Dict = {
            'default': '',
            'tid': self.tid,
            'actor_uuid': self.data['uuid']
        }
        sendEvent.update(event or {})
        return self._topic.publish(
            Message=json.dumps(sendEvent),
            MessageStructure='json'
        )

    @classmethod
    def _createCallbackEvent(cls, response: Dict, event: Dict):
        event = copy.deepcopy(event['callback_data'])
        event.update(response)
        return event

    @classmethod
    def _action(cls, event: EventType):  # This is not state related
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

    def call(self, uuid: str, aspect: str, action: str, **kwargs):
        " call('42', 'mobile', 'arrive', destination='68').now() "
        return Call(self.tid, self.uuid, aspect, action, **kwargs)

    def callAspect(self, aspect: str, action: str, **kwargs):
        return self.call(self.uuid, aspect, action, **kwargs)

    def createAspect(self, aspect: str) -> None:
        self.call(self.uuid, aspect, 'create')
