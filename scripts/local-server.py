#!/usr/bin/env python3
"""Local game server for development.

Provides HTTP + WebSocket endpoints that replace AWS API Gateway + Lambda.
Talks to LocalStack for DynamoDB/SNS. Commands are routed directly to
aspect handlers in-process — no Lambda, no SNS needed for command flow.

Usage:
    # With docker compose (recommended):
    docker compose up

    # Standalone (requires LocalStack running separately):
    python scripts/local-server.py
"""

import asyncio
import json
import logging
import os
import sys
import time
from uuid import uuid4

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from aiohttp import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("local-server")

# ---------------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------------

from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", ".env.local")
if os.path.exists(env_path):
    load_dotenv(env_path)
    logger.info("Loaded environment from .env.local")

# Override LocalStack endpoint for Docker networking
# If LOCALSTACK_ENDPOINT is already set (e.g., from docker-compose env),
# it will be used; otherwise fall back to localhost.
os.environ.setdefault("LOCALSTACK_ENDPOINT", "http://localhost:4566")

# Import backend modules after env is loaded
from aspects import land, landCreator, location
from aspects.auth import _generate_jwt, verify_jwt
from aspects.aws_client import get_dynamodb_table
from aspects.land import Land
from aspects.thing import Call, Entity

# Try to import optional aspects
try:
    from aspects import communication, inventory, npc, identity
except ImportError as e:
    logger.warning(f"Optional aspect import failed (comms/inv/npc): {e}")
    communication = inventory = npc = None

try:
    from aspects import suggestion
except ImportError as e:
    logger.warning(f"Optional aspect import failed (suggestion): {e}")
    suggestion = None

# ---------------------------------------------------------------------------
# WebSocket connection registry
# ---------------------------------------------------------------------------

# Maps connection_id -> WebSocket response object
WS_CONNECTIONS: dict = {}


def _local_push_event(self, event):
    """Monkey-patched push_event that sends to local WebSocket connections."""
    conn_id = self.connection_id
    if not conn_id:
        return
    ws = WS_CONNECTIONS.get(conn_id)
    if ws is None or ws.closed:
        # Connection gone, clear it
        logger.info(f"Connection {conn_id} gone, clearing")
        self.data.pop("connection_id", None)
        self._save()
        return
    try:
        asyncio.get_event_loop().create_task(ws.send_json(event))
    except Exception as e:
        logger.error(f"Failed to push event to {conn_id}: {e}")


# Monkey-patch Entity.push_event to use local WebSocket instead of API Gateway
Entity.push_event = _local_push_event


# ---------------------------------------------------------------------------
# Aspect dispatch — Entity handles dispatch internally now
# ---------------------------------------------------------------------------


def dispatch_sns_event(event_data: dict):
    """Process an SNS event by routing it to Entity._action.

    In the entity table architecture, all events go through Entity._action
    which handles dispatch to the correct aspect.
    """
    try:
        Entity._action(event_data)
    except Exception as e:
        logger.error(f"Error handling {event_data.get('aspect')}.{event_data.get('action')}: {e}")


# Monkey-patch Call.now() to dispatch locally instead of via SNS
_original_call_now = Call.now


def _local_call_now(self):
    """Route Call.now() directly to Entity._action instead of SNS."""
    logger.debug(f"Local dispatch: {self.data.get('aspect')}.{self.data.get('action')}")
    dispatch_sns_event(self.data)


Call.now = _local_call_now

# Also patch Call.after() to execute immediately (no Step Functions delay)
_original_call_after = Call.after


def _local_call_after(self, seconds=0):
    """Execute delayed calls immediately in local mode."""
    if seconds > 0:
        logger.info(
            f"Skipping {seconds}s delay for {self.data.get('aspect')}.{self.data.get('action')}"
        )
    dispatch_sns_event(self.data)


Call.after = _local_call_after


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

DEV_USER_UID = "dev-user-001"
DEV_USER_NAME = "Developer"
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-key")


def dev_login() -> dict:
    """Create a dev user and return a JWT — no Google OAuth needed."""
    # Ensure dev user exists in DynamoDB
    try:
        table = get_dynamodb_table("USERS_TABLE")
        table.put_item(
            Item={
                "google_uid": DEV_USER_UID,
                "email": "dev@localhost",
                "name": DEV_USER_NAME,
                "picture": "",
                "created_at": int(time.time()),
                "last_login": int(time.time()),
            },
            ConditionExpression="attribute_not_exists(google_uid)",
        )
        logger.info("Created dev user")
    except Exception:
        # Already exists — update last login
        try:
            table.update_item(
                Key={"google_uid": DEV_USER_UID},
                UpdateExpression="SET last_login = :t",
                ExpressionAttributeValues={":t": int(time.time())},
            )
        except Exception:
            pass

    jwt_token = _generate_jwt(DEV_USER_UID)
    return {
        "success": True,
        "jwt": jwt_token,
        "user": {
            "google_uid": DEV_USER_UID,
            "email": "dev@localhost",
            "name": DEV_USER_NAME,
            "picture": "",
        },
    }


def dev_api_key_login(api_key: str) -> dict:
    """Handle API key login, or accept 'dev' as a dev key."""
    if api_key == "dev":
        jwt_token = _generate_jwt(DEV_USER_UID, bot_name="dev-bot")
        return {
            "success": True,
            "jwt": jwt_token,
            "user": {
                "google_uid": DEV_USER_UID,
                "bot_name": "dev-bot",
            },
        }
    # Try real API key lookup
    from aspects.auth import login

    return login(api_key=api_key)


# ---------------------------------------------------------------------------
# Player entity management
# ---------------------------------------------------------------------------


def get_or_create_player_entity(user_id: str, name: str = "Player") -> dict:
    """Get or create a mobile player entity located at the origin room.

    The player entity is an Entity record with Land, Inventory, Communication,
    and Suggestion aspects. It is located at the origin room.

    Returns {uuid} for the possess command.
    """
    import uuid as uuid_module

    entity_uuid = str(uuid_module.uuid5(uuid_module.NAMESPACE_DNS, "player-" + user_id))

    # Try to load existing player entity from entity table
    try:
        entity = Entity(uuid=entity_uuid)
        logger.info(f"Found existing player entity {entity_uuid}")

        # Ensure Identity aspect is present for Feature 21
        aspects = entity.data.get("aspects", [])
        if "Identity" not in aspects:
            entity.data["aspects"] = aspects + ["Identity"]
            entity._save()

        return {"uuid": entity_uuid}
    except (KeyError, Exception):
        pass

    # Create new player entity at the origin room.
    origin_uuid = Land.by_coordinates((0, 0, 0))
    logger.info(f"Creating player entity {entity_uuid} at origin {origin_uuid}")

    # Write entity record to entity table
    entity_table = get_dynamodb_table("ENTITY_TABLE")
    entity_table.put_item(
        Item={
            "uuid": entity_uuid,
            "name": name,
            "location": origin_uuid,
            "aspects": ["Land", "Inventory", "Communication", "Suggestion", "Identity"],
            "primary_aspect": "Land",
        }
    )

    # Create inventory aspect record for the player (carry capacity)
    loc_table = get_dynamodb_table("LOCATION_TABLE")
    loc_table.put_item(
        Item={
            "uuid": entity_uuid,
            "carry_capacity": 50,  # weight units the player can carry
        }
    )

    return {"uuid": entity_uuid}


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------


async def handle_login(request):
    """POST /api/auth/login — authenticate and return JWT."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    token = body.get("token")
    api_key = body.get("api_key")

    if api_key:
        result = dev_api_key_login(api_key)
    elif token == "dev" or not token:
        # Dev mode login — no Google OAuth
        result = dev_login()
    else:
        # Try real Google OAuth
        from aspects.auth import login

        result = login(token=token)

    status = 200 if result.get("success") else 401

    # If login succeeded, also create/retrieve player entity
    if result.get("success"):
        user = result.get("user", {})
        user_id = user.get("google_uid", DEV_USER_UID)
        user_name = user.get("name") or user.get("bot_name") or "Player"
        entity_info = get_or_create_player_entity(user_id, user_name)
        result["entity"] = entity_info

    return web.json_response(result, status=status, headers={"Access-Control-Allow-Origin": "*"})


async def handle_generate_key(request):
    """POST /api/auth/keys — generate an API key."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return web.json_response({"error": "Missing Authorization"}, status=401)
    try:
        claims = verify_jwt(auth_header[7:])
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=401)

    body = await request.json()
    bot_name = body.get("bot_name", "unnamed-bot")

    from aspects.auth import generate_api_key

    result = generate_api_key(claims["sub"], bot_name)
    return web.json_response(result, headers={"Access-Control-Allow-Origin": "*"})


async def handle_list_keys(request):
    """GET /api/auth/keys — list API keys."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return web.json_response({"error": "Missing Authorization"}, status=401)
    try:
        claims = verify_jwt(auth_header[7:])
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=401)

    from aspects.auth import list_api_keys

    keys = list_api_keys(claims["sub"])
    return web.json_response({"keys": keys}, headers={"Access-Control-Allow-Origin": "*"})


async def handle_delete_key(request):
    """DELETE /api/auth/keys/{key} — delete an API key."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return web.json_response({"error": "Missing Authorization"}, status=401)
    try:
        claims = verify_jwt(auth_header[7:])
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=401)

    api_key = request.match_info.get("key", "")
    from aspects.auth import delete_api_key

    result = delete_api_key(claims["sub"], api_key)
    status = 200 if result.get("success") else 403
    return web.json_response(result, status=status, headers={"Access-Control-Allow-Origin": "*"})


async def handle_cors_preflight(request):
    """Handle CORS preflight requests."""
    return web.Response(
        status=204,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "86400",
        },
    )


# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------


async def handle_websocket(request):
    """Handle WebSocket connections — replaces API Gateway WebSocket."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Authenticate from query param
    token = request.query.get("token")
    if not token:
        await ws.send_json({"type": "error", "message": "Missing token"})
        await ws.close()
        return ws

    try:
        claims = verify_jwt(token)
    except ValueError as e:
        await ws.send_json({"type": "error", "message": f"Auth failed: {e}"})
        await ws.close()
        return ws

    # Generate a unique connection ID
    connection_id = str(uuid4())
    WS_CONNECTIONS[connection_id] = ws
    user_id = claims.get("sub", "unknown")
    bot_name = claims.get("bot_name")
    logger.info(f"WebSocket connected: {connection_id} user={user_id} bot={bot_name}")

    await ws.send_json(
        {
            "type": "system",
            "message": f"Connected as {bot_name or user_id}. Use 'possess' to bind to an entity.",
            "connection_id": connection_id,
        }
    )

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    command = data.get("command")
                    cmd_data = data.get("data", {})

                    if not command:
                        await ws.send_json({"type": "error", "message": "Missing command"})
                        continue

                    await _handle_ws_command(ws, connection_id, command, cmd_data, claims)

                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "message": "Invalid JSON"})
                except Exception as e:
                    logger.error(f"Command error: {e}", exc_info=True)
                    await ws.send_json({"type": "error", "message": str(e)})

            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f"WebSocket error: {ws.exception()}")
    finally:
        # Clean up
        WS_CONNECTIONS.pop(connection_id, None)
        logger.info(f"WebSocket disconnected: {connection_id}")

        # Detach connection from any entity
        _detach_connection(connection_id)

    return ws


async def _handle_ws_command(ws, connection_id, command, data, claims):
    """Route a WebSocket command to the appropriate handler."""
    if command == "possess":
        entity_uuid = data.get("entity_uuid")

        if not entity_uuid:
            # Auto-create player entity
            user_id = claims.get("sub", DEV_USER_UID)
            user_name = claims.get("bot_name") or claims.get("name") or "Player"
            entity_info = get_or_create_player_entity(user_id, user_name)
            entity_uuid = entity_info["uuid"]

        # Detach from any current entity
        _detach_connection(connection_id)

        # Attach to new entity — if the requested entity doesn't exist
        # (e.g. after a server restart wiped LocalStack), create a fresh one.
        try:
            entity = Entity(uuid=entity_uuid)
        except (KeyError, Exception):
            logger.warning(f"Entity {entity_uuid} not found, creating new player entity")
            user_id = claims.get("sub", DEV_USER_UID)
            user_name = claims.get("bot_name") or claims.get("name") or "Player"
            entity_info = get_or_create_player_entity(user_id, user_name)
            entity_uuid = entity_info["uuid"]
            entity = Entity(uuid=entity_uuid)

        entity.data["connection_id"] = connection_id
        entity._save()

        await ws.send_json(
            {
                "type": "system",
                "message": f"Now controlling entity {entity.name} [{entity_uuid[:8]}]",
            }
        )

        # Auto-look on possess
        try:
            land_aspect = entity.aspect("Land")
            result = land_aspect.look()
            if result:
                await ws.send_json(result)
        except Exception as e:
            logger.warning(f"Auto-look failed: {e}")

        return

    # For all other commands, find the entity by connection_id
    entity_uuid = _find_entity_by_connection(connection_id)
    if not entity_uuid:
        await ws.send_json(
            {
                "type": "error",
                "message": "Not possessing any entity. Send 'possess' first.",
            }
        )
        return

    # Load the entity and run the command through receive_command
    try:
        entity = Entity(uuid=entity_uuid)
    except KeyError:
        await ws.send_json({"type": "error", "message": "Entity not found"})
        return

    # Route through receive_command on Entity
    result = entity.receive_command(command=command, **data)
    # receive_command already calls push_event for the calling entity,
    # but if it returned something and push_event didn't fire (no connection),
    # send it directly.
    if result and not entity.connection_id:
        await ws.send_json(result)


def _find_entity_by_connection(connection_id: str) -> str:
    """Find entity UUID with this connection_id via by_connection GSI."""
    try:
        table = get_dynamodb_table("ENTITY_TABLE")
        response = table.query(
            IndexName="by_connection",
            KeyConditionExpression="connection_id = :cid",
            ExpressionAttributeValues={":cid": connection_id},
        )
        items = response.get("Items", [])
        if items:
            return items[0]["uuid"]
    except Exception as e:
        logger.debug(f"Error querying entity table for connection: {e}")
    return None


def _detach_connection(connection_id: str):
    """Clear connection_id from any entity that has it."""
    try:
        table = get_dynamodb_table("ENTITY_TABLE")
        response = table.query(
            IndexName="by_connection",
            KeyConditionExpression="connection_id = :cid",
            ExpressionAttributeValues={":cid": connection_id},
        )
        for item in response.get("Items", []):
            table.update_item(
                Key={"uuid": item["uuid"]},
                UpdateExpression="REMOVE connection_id",
            )
            logger.info(f"Detached connection {connection_id} from entity {item['uuid']}")
    except Exception as e:
        logger.error(f"Error detaching connection from entity table: {e}")


# ---------------------------------------------------------------------------
# LocalStack health check
# ---------------------------------------------------------------------------


async def wait_for_localstack():
    """Wait until LocalStack DynamoDB is ready."""
    import boto3

    endpoint = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
    logger.info(f"Waiting for LocalStack at {endpoint}...")

    for attempt in range(30):
        try:
            client = boto3.client(
                "dynamodb",
                endpoint_url=endpoint,
                region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1"),
                aws_access_key_id="test",
                aws_secret_access_key="test",
            )
            tables = client.list_tables()
            table_names = tables.get("TableNames", [])
            logger.info(f"LocalStack ready. Tables: {table_names}")

            # Check if our tables exist (entity table is the key one now)
            required = [
                "entity-table-local",
                "thing-table-local",
                "location-table-local",
                "land-table-local",
            ]
            missing = [t for t in required if t not in table_names]
            if missing:
                logger.warning(f"Missing tables: {missing}. Waiting for init script...")
                await asyncio.sleep(2)
                continue

            return True
        except Exception as e:
            logger.info(f"Attempt {attempt + 1}/30: {e}")
            await asyncio.sleep(2)

    logger.error("LocalStack not available after 60 seconds")
    return False


# ---------------------------------------------------------------------------
# Ensure origin world exists
# ---------------------------------------------------------------------------


def ensure_origin_world():
    """Create the origin land tile (0,0,0) if it doesn't exist.

    Uses the worldgen system to generate the origin room with proper
    biome, exits, terrain, and description.
    """
    try:
        origin_uuid = Land.by_coordinates((0, 0, 0))
        origin = Land(uuid=origin_uuid)
        logger.info(f"Origin land exists: {origin_uuid}")

        # If origin hasn't been generated yet, run worldgen
        if not origin.data.get("generated"):
            _generate_origin(origin)

    except Exception as e:
        logger.info(f"Creating origin world: {e}")
        origin = Land()
        origin.coordinates = (0, 0, 0)
        # Also create entity record for the origin room
        entity = Entity()
        entity.data["uuid"] = origin.uuid
        entity.data["name"] = "The Origin"
        entity.data["aspects"] = ["Land"]
        entity.data["primary_aspect"] = "Land"
        entity._save()
        _generate_origin(origin)
        logger.info(f"Created origin land: {origin.uuid}")


def _generate_origin(origin):
    """Generate the origin room using the worldgen system."""
    from aspects.worldgen import generate_room
    from aspects.worldgen.base import GenerationContext

    context = GenerationContext(
        came_from=None,
        came_from_description=None,
        came_from_biome=None,
    )

    try:
        blueprint = generate_room((0, 0, 0), context)

        # Override description for the origin — it's special
        origin.data["description"] = (
            "The starting point. A crossroads of paths stretching "
            "into the unknown. " + (blueprint.description or "")
        ).strip()

        # Apply exits (resolve coords → UUIDs, bidirectional)
        opposite = {
            "north": "south",
            "south": "north",
            "east": "west",
            "west": "east",
            "up": "down",
            "down": "up",
        }
        for direction, dest_coords in blueprint.exits.items():
            if direction in origin.exits:
                continue
            try:
                dest_uuid = Land.by_coordinates(dest_coords)
                origin.add_exit(direction, dest_uuid)
                neighbor = Land(uuid=dest_uuid)
                reverse = opposite.get(direction)
                if reverse and reverse not in neighbor.exits:
                    neighbor.add_exit(reverse, origin.uuid)
            except Exception as ex:
                logger.debug(f"Could not create exit {direction}: {ex}")

        # Create terrain entities
        for terrain_spec in blueprint.terrain:
            Land._create_terrain_entity(origin, terrain_spec)

        # Store metadata
        origin.data["biome"] = blueprint.biome
        origin.data["scale"] = blueprint.scale
        origin.data["tags"] = blueprint.tags
        origin.data["distant_features"] = blueprint.distant_features
        if blueprint.landmark:
            origin.data["landmark"] = blueprint.landmark
        origin.data["generated"] = True
        origin._save()

        logger.info(
            f"Generated origin room: biome={blueprint.biome}, "
            f"exits={list(blueprint.exits.keys())}"
        )

    except Exception as e:
        logger.warning(f"Worldgen failed for origin, using fallback: {e}")
        origin.data["description"] = (
            "The starting point. A crossroads of paths stretching into the unknown."
        )
        # Ensure at least 4 cardinal exits
        opposite = {
            "north": "south",
            "south": "north",
            "east": "west",
            "west": "east",
        }
        for direction in ["north", "south", "east", "west"]:
            if direction not in origin.exits:
                try:
                    new_coord = Land._new_coords_by_direction((0, 0, 0), direction)
                    dest_uuid = Land.by_coordinates(new_coord)
                    origin.add_exit(direction, dest_uuid)
                    neighbor = Land(uuid=dest_uuid)
                    if opposite[direction] not in neighbor.exits:
                        neighbor.add_exit(opposite[direction], origin.uuid)
                except Exception as ex:
                    logger.debug(f"Could not create exit {direction}: {ex}")
        origin.data["generated"] = True
        origin._save()
        logger.info(f"Created origin with fallback: exits={list(origin.exits.keys())}")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app():
    """Create the aiohttp application."""
    app = web.Application()

    # CORS preflight
    app.router.add_route("OPTIONS", "/{path:.*}", handle_cors_preflight)

    # Auth endpoints
    app.router.add_post("/api/auth/login", handle_login)
    app.router.add_post("/api/auth/keys", handle_generate_key)
    app.router.add_get("/api/auth/keys", handle_list_keys)
    app.router.add_delete("/api/auth/keys/{key}", handle_delete_key)

    # WebSocket
    app.router.add_get("/ws", handle_websocket)

    # Health check
    app.router.add_get("/health", lambda r: web.json_response({"status": "ok"}))

    return app


async def main():
    """Start the local game server."""
    # Wait for LocalStack
    ready = await wait_for_localstack()
    if not ready:
        logger.error("Cannot start without LocalStack. Exiting.")
        sys.exit(1)

    # Ensure the world exists
    ensure_origin_world()

    # Create and run the app
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))

    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info(f"Game server running on http://{host}:{port}")
    logger.info(f"  HTTP API: http://{host}:{port}/api/auth/login")
    logger.info(f"  WebSocket: ws://{host}:{port}/ws")
    logger.info(f"  Health: http://{host}:{port}/health")
    logger.info("")
    logger.info('Dev login: POST /api/auth/login with {"token": "dev"}')
    logger.info('Dev bot:   POST /api/auth/login with {"api_key": "dev"}')

    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
