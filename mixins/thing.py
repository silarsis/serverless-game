import boto3
import uuid
from os import environ
from typing import Dict, Any


class Thing:
    _tableName = ''  # Set this in the subclass

    def __init__(self, uuid: str = None):
        assert(self._tableName)
        self.table = boto3.resource('dynamodb').Table(environ[self._tableName])
        self.data: Dict[str, Any] = {}
        if uuid:
            self._load(uuid)
        else:
            self._create()
        assert(self.data)
        assert(self.uuid)

    def _create(self) -> None:
        self.uuid = uuid.uuid4()
        self._save()

    def _save(self) -> None:
        self.table.put_item(Item=self.data)

    def _load(self, uuid: str) -> None:
        self.data = self.table.get_item(Key={'uuid': uuid}).get('Item', {})

    @property
    def uuid(self) -> str:
        return str(self.data['uuid'])

    @uuid.setter
    def uuid(self, value: str) -> None:
        self.data['uuid'] = value

    def _sendEvent(self, event: Dict[str, Any], origEvent: Dict[str, Any]):
        tid = str(origEvent.get('tid') or uuid.uuid4())
        sendEvent = {
            'tid': tid,
            'actor_uuid': self.data['uuid']
        }
        sendEvent.update(event)
        # Send the actual event onto the SNS bus

    @classmethod
    def _action(cls, event: Dict):  # This is not state related
        uuid = event['actor_uuid']
        actor = cls(uuid)
        response = getattr(actor, event['action'])(event)
        if response:
            actor._sendEvent(response, event)
        actor._save()
