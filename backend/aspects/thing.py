import decimal
import importlib
import json
import logging
from collections import UserDict
from os import environ
from typing import Any, Dict
from uuid import uuid4

import boto3

EventType = Dict[str, Any]  # Actually needs to be json-able
IdType = str  # This is a UUID cast to a str, but I want to identify it for typing purposes


def callable(func):
    """Decorator to mark a method as callable via the event system."""

    def wrapper(*args, **kwargs):
        logging.info("Calling {} with {}, {}".format(str(func), str(args), str(kwargs)))
        result = func(*args, **kwargs)
        assert isinstance(result, dict) or result is None
        return result

    wrapper._is_callable = True  # Mark for _get_allowed_actions
    return wrapper


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return int(obj)
        return super(DecimalEncoder, self).default(obj)


class Call(UserDict):
    def __init__(
        self, tid: str, originator: IdType, uuid: IdType, aspect: str, action: str, **kwargs
    ):
        super().__init__()
        self._originating_uuid = originator
        self.data["tid"] = tid
        self.data["aspect"] = aspect
        self.data["uuid"] = uuid
        self.data["action"] = action
        self.data["data"] = kwargs

    def thenCall(self, aspect: str, action: str, uuid: IdType, **kwargs: Dict) -> "Call":
        assert self._originating_uuid
        callback = {
            "tid": self["tid"],
            "aspect": aspect,
            "action": action,
            "uuid": self._originating_uuid,
            "data": kwargs,
        }
        d = self.data
        while "callback" in d:
            d = d["callback"]
        d["callback"] = callback
        return self

    def now(self) -> None:
        sns = boto3.resource("sns").Topic(environ["THING_TOPIC_ARN"])
        logging.info(self.data)
        return sns.publish(
            Message=json.dumps(self.data, cls=DecimalEncoder),
            MessageAttributes={
                "aspect": {"DataType": "String", "StringValue": self.data["aspect"]},
                "action": {"DataType": "String", "StringValue": self.data["action"]},
                "uuid": {"DataType": "String", "StringValue": self.data["uuid"]},
            },
        )

    def after(self, seconds: int = 0) -> None:
        sfn = boto3.client("stepfunctions")
        return sfn.start_execution(
            stateMachineArn=environ["MESSAGE_DELAYER_ARN"],
            input=json.dumps({"delay_seconds": seconds, "data": self.data}, cls=DecimalEncoder),
        )


class Thing(UserDict):
    "Thing objects have state (stored in dynamo) and know how to event and callback"

    _tableName: str = ""  # Set this in the subclass

    @classmethod
    def _get_allowed_actions(cls) -> frozenset:
        """Get set of allowed action names for this class.

        This is for security - only methods decorated with @callable are allowed.
        """
        # Start with parent class allowed actions if any
        allowed: set = set()
        for base in cls.__bases__:
            if hasattr(base, "_get_allowed_actions"):
                allowed.update(base._get_allowed_actions())

        # Add methods decorated with @callable from this class
        for attr_name in dir(cls):
            if not attr_name.startswith("_"):
                attr = getattr(cls, attr_name)
                if callable(attr) and hasattr(attr, "_is_callable"):
                    allowed.add(attr_name)

        return frozenset(allowed)

    def __init__(self, uuid: IdType = None, tid: str = None):
        super().__init__()
        assert self._tableName
        self._tid: str = tid or str(uuid4())
        self.data["uuid"] = uuid or str(uuid4())
        if uuid:
            self._load(uuid)
        else:
            self.create()
        assert self.data
        assert self.uuid

    @property
    def tickDelay(self):
        if "tick_delay" not in self.data:
            self.data["tick_delay"] = 30
            self._save()
        return self.data["tick_delay"]

    @property
    def _table(self):
        return boto3.resource("dynamodb").Table(environ[self._tableName])

    @callable
    def create(self) -> None:
        self._save()

    @callable
    def destroy(self) -> None:
        self._table.delete_item(Key={"uuid": self.uuid})
        logging.info("{} has been destroyed".format(self.uuid))

    @callable
    def tick(self) -> None:
        self.schedule_next_tick()

    @callable
    def schedule_next_tick(self) -> None:
        Call(str(uuid4()), self.uuid, self.uuid, self.aspectName, "tick").after(
            seconds=self.tickDelay
        )

    def aspect(self, aspect: str) -> "Thing":
        return getattr(importlib.import_module(aspect.lower()), aspect)(self.uuid, self.tid)

    @property
    def aspectName(self) -> str:
        return self.__class__.__name__

    def _load(self, uuid: IdType) -> None:
        self.data: Dict = self._table.get_item(Key={"uuid": uuid}).get("Item", {})
        if not self.data:
            raise KeyError("load for non-existent item {}".format(uuid))

    def _save(self) -> None:
        self._table.put_item(Item=self.data)

    @property
    def tid(self) -> str:
        return self._tid

    @property
    def uuid(self) -> IdType:
        return str(self.data["uuid"])

    # Define allowed actions as a class variable for security
    _allowed_actions: frozenset = frozenset()

    @classmethod
    def _action(
        cls, event: EventType
    ):  # This is not state related, this is the entry point for the object
        action = event.get("action", "")

        # Security: Validate action is not private and is in allowed actions
        if action.startswith("_"):
            raise ValueError(f"Action '{action}' is not allowed (private methods are prohibited)")

        # Get allowed actions for this class (combine parent and current class allowed actions)
        allowed = cls._get_allowed_actions()
        if action not in allowed:
            raise ValueError(f"Action '{action}' is not in allowed actions: {allowed}")

        uuid = event.get("uuid")  # Allowing for no uuid for creation
        if not uuid:
            if action != "create":
                raise ValueError("UUID is required for non-create actions")
        tid = str(event.get("tid") or uuid4())
        actor = cls(uuid, tid)

        # Get the method - we know it exists and is allowed
        method = getattr(actor, action, None)
        if method is None or not callable(method):
            raise ValueError(f"Action '{action}' is not a valid callable method")

        response: EventType = method(**event.get("data", {}))
        if event.get("callback"):
            c = event["callback"]
            data = c["data"]
            data.update(response or {})
            Call(c["tid"], "", c["uuid"], c["aspect"], c["action"], **data).now()
        actor._save()

    # Below here are questionable for this class

    def _sendEvent(self, event: EventType) -> str:
        sendEvent: Dict = {"default": "", "tid": self.tid, "actor_uuid": self.data["uuid"]}
        sendEvent.update(event or {})
        topic = boto3.resource("sns").Topic(environ["THING_TOPIC_ARN"])
        return topic.publish(Message=json.dumps(sendEvent), MessageStructure="json")

    def call(self, uuid: IdType, aspect: str, action: str, **kwargs):
        "call('42', 'mobile', 'arrive', kwargs={'destination': '68'}).now()"
        return Call(self.tid, self.uuid, uuid, aspect, action, **kwargs)

    def callAspect(self, aspect: str, action: str, **kwargs):
        return self.call(self.uuid, aspect, action, **kwargs)

    def createAspect(self, aspect: str) -> None:
        self.call(self.uuid, aspect, "create")
