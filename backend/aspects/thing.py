"""Core entity and aspect system for serverless-game backend.

Design Principles:

    Explicit is better than implicit.
        Cross-aspect data access uses self.entity.aspect("Inventory").data["carry_capacity"],
        never self.data["carry_capacity"] from a different aspect. This makes dependencies
        between aspects visible in code.

    Lazy creation.
        Entity creation writes only the entity table record. Aspect records are created on
        first access — no multi-table write transactions needed for entity creation.

    Each aspect owns its data.
        An aspect's table stores only the data that aspect needs. The entity table stores
        universally shared fields: uuid, name, location, connection_id, aspects.

All game objects are entities — rows in a central entity table holding identity (uuid, name),
spatial data (location), connectivity (connection_id), and a list of aspects. An entity is not
a Land or an Inventory — it is an entity that *has* aspects. A player entity has Land, Inventory,
Communication, and Suggestion aspects. A room has a Land aspect. An item has an Inventory aspect.
"""

import decimal
import importlib
import json
import logging
from collections import UserDict
from os import environ
from typing import Any, Dict, List, Optional
from uuid import uuid4

from boto3.dynamodb.conditions import Key
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


# --- Aspect Registry ---

_ASPECT_CLASS_CACHE: Dict[str, type] = {}


def get_aspect_class(aspect_name: str) -> type:
    """Get an aspect class by name, with caching.

    Uses importlib to lazily import aspect modules, avoiding circular imports.
    """
    if aspect_name in _ASPECT_CLASS_CACHE:
        return _ASPECT_CLASS_CACHE[aspect_name]
    try:
        module = importlib.import_module(f"aspects.{aspect_name.lower()}")
        cls = getattr(module, aspect_name)
        _ASPECT_CLASS_CACHE[aspect_name] = cls
        return cls
    except (ImportError, AttributeError) as e:
        raise ValueError(f"Unknown aspect: {aspect_name}") from e


# --- Aspect Base Class ---


class Aspect(UserDict):
    """Base class for aspect data. Each aspect has its own DynamoDB table.

    Aspects store only aspect-specific data. Shared entity fields (name, location,
    connection_id) live on the Entity and are accessed via self.entity.

    Attributes:
        _tableName: Environment variable name for the DynamoDB table.
        entity: Back-reference to the owning Entity instance.
    """

    _tableName: str = ""  # Set by subclass

    def __init__(self, uuid: IdType = None):
        """Initialize an Aspect, optionally loading from its table."""
        super().__init__()
        self.entity: Optional["Entity"] = None
        if uuid:
            self._load(uuid)
        else:
            self.data["uuid"] = str(uuid4())

    @property
    def _table(self):
        """Return the DynamoDB table for this aspect's data."""
        return get_dynamodb_table(self._tableName)

    @property
    def uuid(self) -> IdType:
        """Return the UUID of this aspect's entity."""
        return str(self.data.get("uuid", ""))

    def _load(self, uuid: IdType) -> None:
        """Load aspect data from its DynamoDB table."""
        result = self._table.get_item(Key={"uuid": uuid})
        self.data = result.get("Item", {})
        if not self.data:
            raise KeyError(f"Aspect record {uuid} not found in {self._tableName}")

    def _save(self) -> None:
        """Save aspect data to its DynamoDB table."""
        self._table.put_item(Item=self.data)


# --- Entity Class ---


class Entity(UserDict):
    """Central entity record. All game objects are entities.

    An entity lives in the entity table and holds shared fields: uuid, name,
    location, connection_id, aspects, primary_aspect. Aspect-specific data
    is stored in per-aspect tables and accessed via self.aspect("AspectName").
    """

    _tableName: str = "ENTITY_TABLE"

    def __init__(self, uuid: IdType = None, tid: str = None):
        """Initialize an Entity, loading from the entity table if uuid provided."""
        super().__init__()
        self._tid: str = tid or str(uuid4())
        self._aspect_cache: Dict[str, Aspect] = {}
        if uuid:
            self._load(uuid)
        else:
            self.data["uuid"] = str(uuid4())
            self.data["aspects"] = []
            self.data["primary_aspect"] = ""

    @property
    def _table(self):
        """Return the DynamoDB table for entity records."""
        return get_dynamodb_table(self._tableName)

    @property
    def uuid(self) -> IdType:
        """Return the UUID of this entity."""
        return str(self.data["uuid"])

    @property
    def tid(self) -> str:
        """Return the transaction/request ID."""
        return self._tid

    @property
    def name(self) -> str:
        """Return the display name of this entity."""
        return self.data.get("name", self.uuid[:8])

    @name.setter
    def name(self, value: str):
        """Set the display name."""
        self.data["name"] = value

    @property
    def location(self) -> Optional[IdType]:
        """Return the location UUID (containing entity/room)."""
        return self.data.get("location")

    @location.setter
    def location(self, loc_id: IdType):
        """Set the location, notifying departure and arrival."""
        old_location = self.data.get("location")
        self.data["location"] = loc_id
        self._save()

        entity_name = self.name

        # Notify departure from old location
        if old_location and old_location != loc_id:
            self.broadcast_to_location(
                old_location,
                {
                    "type": "depart",
                    "actor": entity_name,
                    "actor_uuid": self.uuid,
                },
            )

        # Notify arrival at new location
        if loc_id and loc_id != old_location:
            self.broadcast_to_location(
                loc_id,
                {
                    "type": "arrive",
                    "actor": entity_name,
                    "actor_uuid": self.uuid,
                },
            )

    @property
    def connection_id(self) -> Optional[str]:
        """Get the WebSocket connection ID if this entity is connected."""
        return self.data.get("connection_id")

    @connection_id.setter
    def connection_id(self, value: Optional[str]):
        """Set or clear the WebSocket connection ID."""
        if value:
            self.data["connection_id"] = value
        else:
            self.data.pop("connection_id", None)
        self._save()

    @property
    def contents(self) -> List[IdType]:
        """Return UUIDs of all entities whose location is this entity's UUID.

        Uses the contents GSI on the entity table.
        """
        return [
            item["uuid"]
            for item in self._table.query(
                IndexName="contents",
                Select="ALL_PROJECTED_ATTRIBUTES",
                KeyConditionExpression=Key("location").eq(self.uuid),
            )["Items"]
        ]

    @property
    def tickDelay(self):
        """Get the tick delay for the entity (default 30 seconds)."""
        return self.data.get("tick_delay", 30)

    def _load(self, uuid: IdType) -> None:
        """Load entity state from the entity table."""
        self.data = self._table.get_item(Key={"uuid": uuid}).get("Item", {})
        if not self.data:
            raise KeyError(f"Entity {uuid} not found")

    def _save(self) -> None:
        """Save entity state to the entity table."""
        self._table.put_item(Item=self.data)

    # --- Aspect Management ---

    def aspect(self, aspect_name: str) -> Aspect:
        """Load or lazily create an aspect for this entity.

        If the aspect record doesn't exist in its table yet, an empty record
        is created automatically (lazy creation principle).

        Args:
            aspect_name: Name of the aspect class (e.g., "Land", "Inventory").

        Returns:
            Aspect instance with entity back-reference set.
        """
        if aspect_name in self._aspect_cache:
            return self._aspect_cache[aspect_name]

        aspect_cls = get_aspect_class(aspect_name)
        try:
            instance = aspect_cls(uuid=self.uuid)
        except KeyError:
            # Lazy creation — auto-create empty aspect record
            instance = aspect_cls.__new__(aspect_cls)
            UserDict.__init__(instance)
            instance.entity = None
            instance.data = {"uuid": self.uuid}
            instance._save()

        instance.entity = self
        self._aspect_cache[aspect_name] = instance
        return instance

    # --- Command Dispatch ---

    @callable
    def receive_command(self, command: str, **kwargs) -> dict:
        """Receive and route a command to the appropriate aspect.

        Scans aspect classes for the method *before* loading aspect data,
        avoiding unnecessary reads. Primary aspect is checked first.
        """
        # Check for 'help' on Entity itself
        if command == "help":
            result = self.help(**kwargs)
            if result:
                self.push_event(result)
            return result

        # Build aspect search order: primary first, then others
        primary = self.data.get("primary_aspect", "")
        aspects = self.data.get("aspects", [])
        aspect_order = []
        if primary:
            aspect_order.append(primary)
        for a in aspects:
            if a != primary and a not in aspect_order:
                aspect_order.append(a)

        for aspect_name in aspect_order:
            try:
                aspect_cls = get_aspect_class(aspect_name)
            except ValueError:
                continue

            # Scan class for the method without loading data
            method = getattr(aspect_cls, command, None)
            if method and (
                hasattr(method, "_is_player_command") or hasattr(method, "_is_callable")
            ):
                # Found it — now load the aspect data
                aspect_instance = self.aspect(aspect_name)
                bound_method = getattr(aspect_instance, command)
                result = bound_method(**kwargs)
                if result:
                    self.push_event(result)
                return result

        # Not found
        result = {"type": "error", "message": f"Unknown command: {command}"}
        self.push_event(result)
        return result

    @callable
    def help(self, command=None) -> dict:
        """List available commands from all aspects, or get details on one.

        Args:
            command: Optional command name to get details for.

        Returns:
            dict with help info.
        """
        commands = {}

        # Scan all aspects for @player_command methods
        aspects = self.data.get("aspects", [])
        for aspect_name in aspects:
            try:
                aspect_cls = get_aspect_class(aspect_name)
            except ValueError:
                continue

            for cls in aspect_cls.__mro__:
                if cls is UserDict or cls is object or cls is Aspect:
                    continue
                for attr_name in vars(cls):
                    if attr_name.startswith("_"):
                        continue
                    attr = getattr(cls, attr_name, None)
                    if attr is None:
                        continue
                    if hasattr(attr, "_is_player_command") and attr._is_player_command:
                        if attr_name not in commands:
                            doc = getattr(attr, "__doc__", "") or ""
                            first_line = (
                                doc.strip().split("\n")[0] if doc.strip() else "No description."
                            )
                            commands[attr_name] = {
                                "name": attr_name,
                                "summary": first_line,
                                "doc": doc.strip(),
                            }

        # Always include help itself
        if "help" not in commands:
            commands["help"] = {
                "name": "help",
                "summary": "List available commands, or get details on a specific command.",
                "doc": "List available commands, or get details on a specific command.",
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

    # Mark help as a player command
    help._is_player_command = True

    # --- WebSocket / Connection ---

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

    # --- Location Broadcasting ---

    def broadcast_to_location(
        self, location_uuid: IdType, event: Dict, exclude_self: bool = True
    ) -> None:
        """Broadcast an event to all connected entities at a location.

        Uses the entity table's contents GSI to find entities at the location.
        """
        if not location_uuid:
            return
        try:
            loc_entity = Entity(uuid=location_uuid)
            for entity_uuid in loc_entity.contents:
                if exclude_self and entity_uuid == self.uuid:
                    continue
                try:
                    other = Entity(uuid=entity_uuid)
                    other.push_event(event)
                except (KeyError, Exception):
                    pass
        except (KeyError, Exception) as e:
            logging.debug(f"Could not broadcast to location {location_uuid}: {e}")

    # --- SNS Event System ---

    @classmethod
    def _action(cls, event: EventType):
        """Process an incoming SNS action/event on an entity."""
        action = event.get("action", "")

        if action.startswith("_"):
            raise ValueError(f"Action '{action}' is not allowed (private methods are prohibited)")

        uuid = event.get("uuid")
        if not uuid:
            if action != "create":
                raise ValueError("UUID is required for non-create actions")
        tid = str(event.get("tid") or uuid4())

        # Load the entity
        entity = Entity(uuid, tid)

        # Check if it's an entity-level action
        method = getattr(entity, action, None)
        if method and hasattr(method, "_is_callable"):
            response = method(**event.get("data", {}))
            if event.get("callback"):
                c = event["callback"]
                data = c["data"]
                data.update(response or {})
                Call(c["tid"], "", c["uuid"], c["aspect"], c["action"], **data).now()
            entity._save()
            return

        # Otherwise dispatch to the right aspect
        aspect_name = event.get("aspect", "")
        if aspect_name:
            try:
                aspect_instance = entity.aspect(aspect_name)
                aspect_method = getattr(aspect_instance, action, None)
                if aspect_method and hasattr(aspect_method, "_is_callable"):
                    response = aspect_method(**event.get("data", {}))
                    if event.get("callback"):
                        c = event["callback"]
                        data = c["data"]
                        data.update(response or {})
                        Call(c["tid"], "", c["uuid"], c["aspect"], c["action"], **data).now()
                    aspect_instance._save()
                    entity._save()
                    return
            except ValueError:
                pass

        raise ValueError(f"Action '{action}' not found on entity or aspect '{aspect_name}'")

    # --- Tick System ---

    @callable
    def tick(self) -> None:
        """Schedule this entity's next tick."""
        self.schedule_next_tick()

    @callable
    def schedule_next_tick(self) -> None:
        """Schedule the entity's next tick after tickDelay seconds."""
        primary = self.data.get("primary_aspect", "Entity")
        Call(str(uuid4()), self.uuid, self.uuid, primary, "tick").after(seconds=self.tickDelay)

    # --- Call Helpers ---

    def call(self, uuid: IdType, aspect: str, action: str, **kwargs):
        """Build a Call object to target another entity's aspect/action."""
        return Call(self.tid, self.uuid, uuid, aspect, action, **kwargs)

    def callAspect(self, aspect: str, action: str, **kwargs):
        """Call an aspect on this entity."""
        return self.call(self.uuid, aspect, action, **kwargs)

    # --- Destroy ---

    @callable
    def destroy(self) -> None:
        """Delete this entity and all its aspect records."""
        # Delete aspect records
        for aspect_name in self.data.get("aspects", []):
            try:
                aspect_cls = get_aspect_class(aspect_name)
                table = get_dynamodb_table(aspect_cls._tableName)
                table.delete_item(Key={"uuid": self.uuid})
            except (ValueError, Exception) as e:
                logging.debug(f"Could not delete aspect {aspect_name}: {e}")

        # Delete entity record
        self._table.delete_item(Key={"uuid": self.uuid})
        logging.info(f"{self.uuid} has been destroyed")


# Backward compatibility alias
Thing = Entity
