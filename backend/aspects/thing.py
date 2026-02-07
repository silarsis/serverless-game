"""Core thing and event/callback logic for serverless-game backend."""

import decimal
import importlib
import json
import logging
from collections import UserDict
from os import environ
from typing import Any, Dict
from uuid import uuid4

from botocore.exceptions import ClientError

from aspects.aws_client import (
    get_api_gateway_client,
    get_dynamodb_table,
    get_sns_topic,
    get_stepfunctions_client,
)

EventType = Dict[str, Any]  # Actually needs to be json-able
IdType = str  # This is a UUID cast to a str, but I want to identify it for typing purposes


def callable(func):
    """Mark a method as callable via the event system."""

    def wrapper(*args, **kwargs):
        logging.info("Calling {} with {}, {}".format(str(func), str(args), str(kwargs)))
        result = func(*args, **kwargs)
        assert isinstance(result, dict) or result is None
        return result

    wrapper._is_callable = True  # Mark for _get_allowed_actions
    return wrapper


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder for Decimal types."""

    def default(self, obj):
        """Encode Decimal as int for JSON serialization."""
        if isinstance(obj, decimal.Decimal):
            return int(obj)
        return super(DecimalEncoder, self).default(obj)


class Call(UserDict):
    """Representation of an event call and its reply/callback stack."""

    def __init__(
        self,
        tid: str,
        originator: IdType,
        uuid: IdType,
        aspect: str,
        action: str,
        **kwargs,
    ):
        """Initialize a Call instance."""
        super().__init__()
        self._originating_uuid = originator
        self.data["tid"] = tid
        self.data["aspect"] = aspect
        self.data["uuid"] = uuid
        self.data["action"] = action
        self.data["data"] = kwargs

    def thenCall(self, aspect: str, action: str, uuid: IdType, **kwargs: Dict) -> "Call":
        """Add a callback to be executed after the main action."""
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
        """Publish this call immediately via SNS."""
        sns = get_sns_topic("THING_TOPIC_ARN")
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
        """Start this call after a given number of seconds via Step Functions."""
        sfn = get_stepfunctions_client()
        return sfn.start_execution(
            stateMachineArn=environ["MESSAGE_DELAYER_ARN"],
            input=json.dumps({"delay_seconds": seconds, "data": self.data}, cls=DecimalEncoder),
        )


class Thing(UserDict):
    """Base class for game objects. Objects have state (stored in DynamoDB) and handle event/callback logic."""

    _tableName: str = ""  # Set this in the subclass

    @classmethod
    def _get_allowed_actions(cls) -> frozenset:
        """Get set of allowed action names for this class. Only @callable methods allowed."""
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
        """Initialize a Thing with a UUID and transaction ID, loading or creating state."""
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
        """Get or initialize the tick delay for the object."""
        if "tick_delay" not in self.data:
            self.data["tick_delay"] = 30
            self._save()
        return self.data["tick_delay"]

    @property
    def _table(self):
        """Return the DynamoDB table for the object's state."""
        return get_dynamodb_table(self._tableName)

    @callable
    def create(self) -> None:
        """Create object in the backing store (DynamoDB)."""
        self._save()

    @callable
    def destroy(self) -> None:
        """Delete this object by UUID."""
        self._table.delete_item(Key={"uuid": self.uuid})
        logging.info("{} has been destroyed".format(self.uuid))

    @callable
    def tick(self) -> None:
        """Schedule this object's next tick."""
        self.schedule_next_tick()

    @callable
    def schedule_next_tick(self) -> None:
        """Schedule the object's next tick after tickDelay seconds."""
        Call(str(uuid4()), self.uuid, self.uuid, self.aspectName, "tick").after(
            seconds=self.tickDelay
        )

    def aspect(self, aspect: str) -> "Thing":
        """Return an aspect handler for this object by aspect name."""
        return getattr(importlib.import_module(aspect.lower()), aspect)(self.uuid, self.tid)  # type: ignore

    @property
    def aspectName(self) -> str:
        """Return the object's aspect (class name)."""
        return self.__class__.__name__

    def _load(self, uuid: IdType) -> None:
        """Load object state from DynamoDB by UUID."""
        self.data: Dict = self._table.get_item(Key={"uuid": uuid}).get("Item", {})  # type: ignore
        if not self.data:
            raise KeyError(f"load for non-existent item {uuid}")

    def _save(self) -> None:
        """Save object state to DynamoDB."""
        self._table.put_item(Item=self.data)

    @property
    def tid(self) -> str:
        """Return the transaction/request ID for this object."""
        return self._tid

    @property
    def uuid(self) -> IdType:
        """Return the UUID of this object as a string."""
        return str(self.data["uuid"])

    _allowed_actions: frozenset = frozenset()
    """Allowed actions for use with the event system."""

    @classmethod
    def _action(cls, event: EventType):
        """Process an incoming action/event on this object, enforcing security."""
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

    @property
    def connection_id(self):
        """Get the WebSocket connection ID if this entity is connected."""
        return self.data.get("connection_id")

    @connection_id.setter
    def connection_id(self, value):
        """Set or clear the WebSocket connection ID."""
        if value:
            self.data["connection_id"] = value
        else:
            self.data.pop("connection_id", None)
        self._save()

    def push_event(self, event: Dict) -> None:
        """Push an event to the connected WebSocket, if any."""
        if not self.connection_id:
            return
        try:
            client = get_api_gateway_client()
            client.post_to_connection(
                ConnectionId=self.connection_id,
                Data=json.dumps(event, cls=DecimalEncoder).encode("utf-8"),
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "GoneException":
                logging.info(f"Connection {self.connection_id} gone, clearing")
                self.connection_id = None
            else:
                raise

    @callable
    def attach_connection(self, connection_id: str) -> dict:
        """Attach a WebSocket connection to this entity."""
        self.data["connection_id"] = connection_id
        self._save()
        return {"status": "connected", "entity_uuid": self.uuid}

    @callable
    def detach_connection(self) -> dict:
        """Detach the WebSocket connection from this entity."""
        self.data.pop("connection_id", None)
        self._save()
        return {"status": "disconnected", "entity_uuid": self.uuid}

    @callable
    def receive_command(self, command: str, **kwargs) -> dict:
        """Receive and route a command from WebSocket to a @player_command method."""
        method = getattr(self, command, None)
        if method is None:
            result = {"error": f"Unknown command: {command}"}
            self.push_event(result)
            return result
        # Check if the method is marked as player-callable
        if not hasattr(method, "_is_player_command") and not hasattr(method, "_is_callable"):
            result = {"error": f"Command '{command}' is not available"}
            self.push_event(result)
            return result
        result = method(**kwargs)
        if result:
            self.push_event(result)
        return result

    @callable
    def help(self, command=None) -> dict:
        """List available commands, or get details on a specific command.

        Args:
            command: Optional command name to get details for.

        Returns:
            dict with help info.
        """
        commands = {}
        for cls in type(self).__mro__:
            for attr_name in vars(cls):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(cls, attr_name, None)
                if attr is None:
                    continue
                if hasattr(attr, "_is_player_command") and attr._is_player_command:
                    if attr_name not in commands:
                        doc = getattr(attr, "__doc__", "") or ""
                        first_line = doc.strip().split("\n")[0] if doc.strip() else "No description."
                        commands[attr_name] = {
                            "name": attr_name,
                            "summary": first_line,
                            "doc": doc.strip(),
                        }

        if command:
            cmd_info = commands.get(command)
            if cmd_info:
                return {
                    "type": "help_detail",
                    "command": command,
                    "description": cmd_info["doc"],
                }
            return {"type": "error", "message": f"Unknown command: {command}"}

        return {
            "type": "help",
            "commands": [
                {"name": c["name"], "summary": c["summary"]}
                for c in sorted(commands.values(), key=lambda x: x["name"])
            ],
        }

    # Mark help as a player command (can't use @player_command decorator due to import cycle)
    help._is_player_command = True

    def broadcast_location_event(self, event: Dict) -> None:
        """Broadcast an event to all connected entities at the same location as this entity.

        Requires the entity to have a 'location' field in its data.
        Skips self.
        """
        location_uuid = self.data.get("location")
        if not location_uuid:
            return

        # Import here to avoid circular imports
        from aspects.aws_client import get_dynamodb_table

        table = get_dynamodb_table("LOCATION_TABLE")
        try:
            from boto3.dynamodb.conditions import Key

            result = table.query(
                IndexName="contents",
                Select="ALL_PROJECTED_ATTRIBUTES",
                KeyConditionExpression=Key("location").eq(location_uuid),
            )
            for item in result.get("Items", []):
                if item["uuid"] == self.uuid:
                    continue
                try:
                    entity = Thing(uuid=item["uuid"])
                    entity.push_event(event)
                except (KeyError, Exception):
                    pass
        except Exception as e:
            logging.debug(f"Could not broadcast to location {location_uuid}: {e}")

    def _sendEvent(self, event: EventType) -> str:
        """Send an event to the SNS topic with current object's tid and uuid."""
        sendEvent: Dict = {
            "default": "",
            "tid": self.tid,
            "actor_uuid": self.data["uuid"],
        }
        sendEvent.update(event or {})
        topic = get_sns_topic("THING_TOPIC_ARN")
        return topic.publish(Message=json.dumps(sendEvent), MessageStructure="json")

    def call(self, uuid: IdType, aspect: str, action: str, **kwargs):
        """Build a Call object to target another aspect/action."""
        return Call(self.tid, self.uuid, uuid, aspect, action, **kwargs)  # type: ignore

    def callAspect(self, aspect: str, action: str, **kwargs):
        """Call an aspect on this object."""
        return self.call(self.uuid, aspect, action, **kwargs)  # type: ignore

    def createAspect(self, aspect: str) -> None:
        """Create a new aspect for this object's uuid."""
        self.call(self.uuid, aspect, "create")
