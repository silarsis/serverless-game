"""WebSocket Lambda handlers - bridge between API Gateway and entities."""

import json
import logging
from typing import Dict, Optional
from urllib.parse import parse_qs
from uuid import uuid4

from aspects.auth import verify_jwt
from aspects.aws_client import get_dynamodb_table
from aspects.thing import Call


def connect_handler(event: dict, context: dict) -> dict:
    """Handle WebSocket $connect.

    Verifies JWT from query string before accepting the connection.
    Entity binding happens separately via 'possess' command.
    """
    connection_id = event["requestContext"]["connectionId"]

    # Extract JWT from query string (?token=xxx)
    query_params = event.get("queryStringParameters") or {}
    token = query_params.get("token")

    if not token:
        logging.warning(f"WebSocket connect rejected: no token from {connection_id}")
        return {"statusCode": 401, "body": "Missing token"}

    try:
        claims = verify_jwt(token)
        logging.info(f"WebSocket connected: {connection_id} user={claims.get('sub')}")
        return {"statusCode": 200}
    except ValueError as e:
        logging.warning(f"WebSocket connect rejected: {e}")
        return {"statusCode": 401, "body": "Invalid token"}


def disconnect_handler(event: dict, context: dict) -> dict:
    """Handle WebSocket $disconnect.

    Find the entity with this connection_id and clear it.
    """
    connection_id = event["requestContext"]["connectionId"]
    logging.info(f"WebSocket disconnected: {connection_id}")

    entity_info = _find_entity_by_connection(connection_id)
    if entity_info:
        # Detach connection from entity via SNS (preserves event flow)
        Call(
            tid=str(uuid4()),
            originator="",
            uuid=entity_info["uuid"],
            aspect=entity_info["aspect"],
            action="detach_connection",
        ).now()

    return {"statusCode": 200}


def command_handler(event: dict, context: dict) -> dict:
    """Handle WebSocket command messages.

    Routes to entity.receive_command() via SNS.
    """
    connection_id = event["requestContext"]["connectionId"]
    body = json.loads(event.get("body", "{}"))

    command = body.get("command")
    data = body.get("data", {})

    if not command:
        return {"statusCode": 400, "body": json.dumps({"error": "Missing command"})}

    # Special case: 'possess' binds connection to entity
    if command == "possess":
        return _handle_possess(connection_id, data)

    # Find entity by connection_id
    entity_info = _find_entity_by_connection(connection_id)
    if not entity_info:
        return {
            "statusCode": 403,
            "body": json.dumps({"error": "Not possessing any entity. Send 'possess' first."}),
        }

    # Route command to entity via SNS
    Call(
        tid=str(uuid4()),
        originator=connection_id,
        uuid=entity_info["uuid"],
        aspect=entity_info["aspect"],
        action="receive_command",
        command=command,
        **data,
    ).now()

    return {"statusCode": 200}


def _handle_possess(connection_id: str, data: dict) -> dict:
    """Bind WebSocket connection to an entity."""
    entity_uuid = data.get("entity_uuid")
    entity_aspect = data.get("entity_aspect")

    if not entity_uuid or not entity_aspect:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "possess requires entity_uuid and entity_aspect"}),
        }

    # First, detach this connection from any existing entity
    existing = _find_entity_by_connection(connection_id)
    if existing:
        Call(
            tid=str(uuid4()),
            originator="",
            uuid=existing["uuid"],
            aspect=existing["aspect"],
            action="detach_connection",
        ).now()

    # Attach to new entity
    Call(
        tid=str(uuid4()),
        originator=connection_id,
        uuid=entity_uuid,
        aspect=entity_aspect,
        action="attach_connection",
        connection_id=connection_id,
    ).now()

    return {
        "statusCode": 200,
        "body": json.dumps({"status": "possessing", "entity_uuid": entity_uuid}),
    }


def _find_entity_by_connection(connection_id: str) -> Optional[Dict]:
    """Find entity that has this connection_id."""
    table = get_dynamodb_table("THING_TABLE")

    # Scan for entity with this connection_id
    # NOTE: In production, add a GSI on connection_id for efficiency
    response = table.scan(
        FilterExpression="connection_id = :cid",
        ExpressionAttributeValues={":cid": connection_id},
    )

    items = response.get("Items", [])
    if items:
        item = items[0]
        return {"uuid": item["uuid"], "aspect": item.get("aspect", "Thing")}
    return None
