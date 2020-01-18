import boto3
from uuid import uuid4
import json
from os import environ
from typing import Dict, Any
from collections import UserDict
import copy

EventType = Dict[str, Any]  # Actually needs to be json-able


class Tell:
    def __init__(self, _sendEvent, _callback, aspect, uuid):
        self._sendEvent = _sendEvent
        self._callback = _callback
        self.aspect = aspect
        self.uuid = uuid

    def to(self, action, **kwargs):
        event = {
            'actor_uuid': self.uuid,
            'aspect': self.aspect,
            'action': action
        }
        event.update(kwargs)
        self._sendEvent(event)

    def for(self, action, **kwargs):
        event = {
            'actor_uuid': self.uuid,
            'aspect': self.aspect,
            'action': action
        }
        event.update(kwargs)
        self._callback(event)

    def now(self):
        send



class Thing(UserDict):
    " Thing objects have state (stored in dynamo) and know how to event and callback "
    _tableName: str = ''  # Set this in the subclass

    def __init__(self, uuid: str = None, tid: str = None):
        super().__init__()
        assert(self._tableName)
        self._table = boto3.resource('dynamodb').Table(environ[self._tableName])
        self._topic = boto3.resource('sns').Topic(environ['THING_TOPIC'])
        self._tid: str = tid or str(uuid4())
        if uuid:
            self._load(uuid)
        else:
            self.create()
        assert(self.data)
        assert(self.uuid)

    def create(self) -> None:
        " Generally subclasses of Thing will set up data in their own create() then call super().create() "
        self.uuid = str(uuid4())
        self._save()

    def destroy(self) -> None:
        self._table.delete_item(Key={'uuid': self.uuid})

    def tick(self) -> None:
        pass

    def _load(self, uuid: str) -> None:
        self.data: Dict = self._table.get_item(Key={'uuid': uuid}).get('Item', {})

    def _save(self) -> None:
        self._table.put_item(Item=self.data)

    @property
    def tid(self) -> str:
        return self._tid

    @property
    def uuid(self) -> str:
        return str(self.data['uuid'])

    @uuid.setter
    def uuid(self, value: str) -> None:
        self.data['uuid'] = value

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

    def _callback(self, event: EventType, callback: str, data: EventType = {}) -> str:
        """
        Send an event, request a callback when done.

        event: the event to call
        callback: our action to call when done
        data: the data to add to the callback to carry state
        """
        callback_data = copy.deepcopy(data)
        callback_data.setdefault('actor_uuid', self.uuid)
        sendEvent: Dict = {
            'callback': callback,
            'callback_data': callback_data
        }
        sendEvent.update(event)
        return self._sendEvent(event)

    @classmethod
    def _createCallbackEvent(cls, response: Dict, event: Dict):
        event = copy.deepcopy(event['callback_data'])
        event.update(response)
        return event

    @classmethod
    def _action(cls, event: EventType):  # This is not state related
        uuid = event['actor_uuid']
        tid = str(event.get('tid') or uuid4())
        actor = cls(uuid, tid)
        response: EventType = getattr(actor, event['action'])(event)
        if event.get('callback'):
            actor._sendEvent(cls._createCallbackEvent(response, event))
        event.get('callback', actor._sendEvent)(response)
        actor._save()

    def tell(self, aspect, uuid):
        return Tell(self._sendEvent, aspect, uuid)
