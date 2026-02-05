# WebSocket Architecture (Revised)

## Critical Clarification

**The entity holds the connection.** The WebSocket is NOT an entity itself—it's just a pipe attached to an entity. Entities continue in the world whether connected or not.

---

## Authentication & Authorization

### Overview

The serverless-game WebSocket system uses JWT-based authentication with fine-grained authorization to ensure players can only control their own entities.

### Authentication Model

#### JWT as API Key

JWT tokens are passed as API keys in WebSocket connection headers during the `$connect` handshake:

```
WebSocket Connect Request:
  Headers:
    X-Api-Key: <JWT_TOKEN>
    
  Or via query parameter (fallback):
    wss://api.example.com/ws?token=<JWT_TOKEN>
```

**Key Design Decisions:**
1. **JWT in Headers:** Agents store and pass JWT like API credentials
2. **Future-Proof:** Can upgrade to OAuth 2.0 without changing architecture
3. **Stateless Auth:** No session storage required; JWT contains player identity

#### JWT Structure

```json
{
  "sub": "player_uuid",
  "iat": 1707158400,
  "exp": 1707162000,
  "iss": "serverless-game-auth",
  "aud": "serverless-game-ws",
  "claims": {
    "player_uuid": "player-abc-123",
    "is_admin": false
  }
}
```

### Authorization Rules

#### 1. Player Object Creation on First Connect

When a new WebSocket connects with a valid JWT:

1. **Extract Player Identity:** Parse JWT to get `player_uuid`
2. **Lookup or Create Player Entity:**
   - If player entity exists → attach connection to existing entity
   - If no player entity → create new `Player` entity (or appropriate aspect)
3. **Every Connection = New Possession:**
   - Even reconnections create new player object instances
   - Old entities remain in world (ghost mode) until timeout/cleanup

```python
# In connect_handler
from aspects.auth import verify_jwt, get_or_create_player

def connect_handler(event: dict, context: dict) -> dict:
    connection_id = event["requestContext"]["connectionId"]
    
    # Extract and verify JWT from headers
    headers = event.get("headers", {})
    token = headers.get("X-Api-Key") or headers.get("x-api-key")
    
    if not token:
        return {"statusCode": 401, "body": "Missing authentication"}
    
    # Verify JWT and extract player identity
    try:
        claims = verify_jwt(token)
        player_uuid = claims["sub"]
    except JWTError as e:
        return {"statusCode": 403, "body": f"Invalid token: {e}"}
    
    # Get or create player entity
    player = get_or_create_player(player_uuid, connection_id)
    
    logging.info(f"Player {player_uuid} connected: {connection_id}")
    return {"statusCode": 200}
```

#### 2. Possession Validation Logic

**Core Rule:** Players can only possess/connect to their own player objects.

```
Authorization Flow:

1. WebSocket connects (with JWT)
   ↓
2. Verify JWT → extract player_uuid
   ↓
3. Check if connection is attempting to possess an entity:
   - If entity.uuid == player_uuid → ALLOW
   - If entity.owner_uuid == player_uuid → ALLOW
   - If entity.is_system == True → DENY (system entities admin-only)
   - Otherwise → DENY with "Not your entity"
```

**Implementation in `websocket_handlers.py`:**

```python
def _validate_possession(player_uuid: str, entity_uuid: str, entity: Thing) -> bool:
    """
    Validate that a player can possess an entity.
    
    Rules:
    - Player can possess their own player entity
    - Player can possess entities they own (owner_uuid == player_uuid)
    - System entities cannot be possessed (is_system == True)
    """
    # System entities are never possessable by players
    if getattr(entity, 'is_system', False):
        return False
    
    # Player can possess their own entity
    if entity_uuid == player_uuid:
        return True
    
    # Player can possess entities they own
    if getattr(entity, 'owner_uuid', None) == player_uuid:
        return True
    
    return False


def command_handler(event: dict, context: dict) -> dict:
    connection_id = event["requestContext"]["connectionId"]
    body = json.loads(event.get("body", "{}"))
    
    command = body.get("command")
    entity_uuid = body.get("entity_uuid")
    
    # Get player identity from connection context (set during connect)
    player_uuid = _get_player_from_connection(connection_id)
    
    if command == "possess":
        entity = _load_entity(entity_uuid, body.get("entity_aspect"))
        
        if not _validate_possession(player_uuid, entity_uuid, entity):
            return {
                "statusCode": 403,
                "body": json.dumps({"error": "Not authorized to possess this entity"})
            }
        
        # Proceed with attachment...
        Call(
            tid=str(uuid4()),
            originator=connection_id,
            uuid=entity_uuid,
            aspect=body.get("entity_aspect"),
            action="attach_connection",
            connection_id=connection_id,
            _player_uuid=player_uuid  # Pass for authorization
        ).now()
```

#### 3. System Entities (Admin-Only)

System entities are special infrastructure entities that cannot be possessed by players:

```python
# Example system entity
from aspects.decorators import system_entity, admin_only
from aspects.thing import Thing

@system_entity
class WorldTicker(Thing):
    """System entity that manages world ticks. Admin-only access."""
    
    @admin_only
    def shutdown(self, reason: str = "") -> dict:
        """Shutdown the world tick scheduler."""
        return {"status": "shutdown", "reason": reason}
    
    @callable
    def tick(self) -> dict:
        """Perform world tick - callable by other system entities."""
        return {"status": "ticked"}
```

**System Entity Properties:**
- `is_system = True` (set by @system_entity decorator)
- Cannot be possessed by players (connection attachment blocked)
- Can only be commanded by admin-authenticated connections
- Typically world managers, tick schedulers, zone controllers

### Command Security

#### @player_command Decorator

The `@player_command` decorator marks methods that can be invoked via WebSocket:

```python
from aspects.decorators import player_command
from aspects.thing import Thing

class Land(Thing):
    @player_command
    def move(self, direction: str) -> dict:
        """
        Move in a direction - callable by connected player via WebSocket.
        
        Security checks:
        - Validates caller owns this entity
        - Validates entity is not a system entity
        """
        self.location = self._calculate_new_location(direction)
        self.push_event({"event": "moved", "to": self.location})
        return {"status": "moved", "direction": direction}
    
    @player_command
    def say(self, message: str) -> dict:
        """Say something to nearby players."""
        self.broadcast_to_nearby({"event": "speech", "from": self.uuid, "text": message})
        return {"status": "said"}
    
    @callable  # Internal only - NOT exposed via WebSocket
    def internal_state_update(self, state: dict) -> dict:
        """Update internal state - only callable via SNS from other aspects."""
        self.state.update(state)
        return {"status": "updated"}
```

**Key Differences:**

| Decorator | WebSocket Access | SNS Access | Authorization |
|-----------|------------------|------------|---------------|
| `@player_command` | ✅ Yes | ✅ Yes | Player ownership validated |
| `@callable` | ❌ No | ✅ Yes | Internal only |
| `@admin_only` | ✅ Yes (admin only) | ✅ Yes (admin only) | Admin JWT required |

#### Command Routing with Authorization

When a command arrives via WebSocket, the flow includes authorization:

```python
def receive_command(self, command: str, **kwargs) -> Dict[str, Any]:
    """
    Entry point for WebSocket commands with authorization.
    
    Only routes to methods decorated with @player_command.
    @callable-only methods remain inaccessible from WebSocket.
    """
    method = getattr(self, command, None)
    
    # Security: Only allow @player_command methods from WebSocket
    if not method or not callable(method):
        return {"error": f"Unknown command: {command}"}
    
    if not hasattr(method, "_is_player_command"):
        # Method exists but is not exposed to players (internal @callable only)
        logger.warning(f"Blocked WebSocket access to internal method: {command}")
        return {"error": f"Command not available: {command}"}
    
    # Validate possession (caller must own this entity)
    caller_player = kwargs.get('_player_uuid')
    if caller_player != self.player_uuid:  # Assuming player_uuid stored on entity
        return {"error": "Not authorized to command this entity"}
    
    # Pass connection ID for validation in @player_command decorator
    kwargs['_caller_connection_id'] = kwargs.get('_connection_id')
    
    # Execute the player command
    return method(**kwargs)
```

### Security Summary

| Feature | Implementation |
|---------|----------------|
| **Authentication** | JWT in WebSocket connect headers (X-Api-Key) |
| **Player Identity** | Extracted from JWT `sub` claim |
| **Player Creation** | Auto-created on first connect with valid JWT |
| **Possession** | Player can only possess entities where `entity.uuid == player_uuid` or `entity.owner_uuid == player_uuid` |
| **System Protection** | `is_system=True` entities reject all player possession |
| **Command Exposure** | `@player_command` decorator required for WebSocket access |
| **Internal Protection** | `@callable` methods not exposed via WebSocket |
| **Admin Access** | `@admin_only` decorator for admin commands |

---

## Critical Clarification

```
OLD (wrong):  Player → Connection aspect → Entity
NEW (right):  Player → WebSocket ────────▶ Entity (holds connection_id)
                    ▲                      │
                    └──────────────────────┘
                          (entity pushes events up)
```

---

## Revised Architecture

### Entity (Thing) Changes

The `Thing` base class gets two new fields and methods:

```python
class Thing(UserDict):
    """
    Thing objects have state (stored in dynamo) and know how to event and callback.
    NEW: Can optionally have a WebSocket connection for real-time I/O.
    """
    _tableName: str = ""

    @property
    def connection_id(self) -> Optional[str]:
        """The WebSocket connection ID if connected, None otherwise."""
        return self.data.get("connection_id")

    @connection_id.setter
    def connection_id(self, value: Optional[str]) -> None:
        """Set or clear the WebSocket connection."""
        if value:
            self.data["connection_id"] = value
        else:
            self.data.pop("connection_id", None)
        self._save()

    def push_event(self, event: Dict[str, Any]) -> None:
        """
        Push an event to the connected WebSocket client.
        Called by the entity when something happens that the player should see.
        If no connection, this is a no-op (event still flows through SNS normally).
        """
        if not self.connection_id:
            return  # No connection, no problem—world continues

        try:
            api_gateway = get_api_gateway_client()
            api_gateway.post_to_connection(
                ConnectionId=self.connection_id,
                Data=json.dumps(event, cls=DecimalEncoder)
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "GoneException":
                # Connection died, clean it up
                self.connection_id = None
            else:
                logging.error(f"Failed to push event: {e}")

    @callable
    def receive_command(self, command: str, **kwargs) -> Dict[str, Any]:
        """
        Receive a command from the WebSocket.
        Processes as if it were a local method call.
        Override in subclasses for custom command handling.
        """
        # Default: treat command as a callable method name
        method = getattr(self, command, None)
        if method and callable(method) and hasattr(method, "_is_callable"):
            return method(**kwargs)
        return {"error": f"Unknown command: {command}"}
```

### Minimal Changes to Thing Class

**File:** `backend/aspects/thing.py`

```python
# Add to imports
from typing import Optional
from botocore.exceptions import ClientError

# Add to Thing class (after __init__):

    @property
    def connection_id(self) -> Optional[str]:
        return self.data.get("connection_id")

    @connection_id.setter
    def connection_id(self, value: Optional[str]) -> None:
        if value:
            self.data["connection_id"] = value
        else:
            self.data.pop("connection_id", None)
        self._save()

    def push_event(self, event: Dict[str, Any]) -> None:
        """Push event to connected WebSocket if present."""
        if not self.connection_id:
            return
        try:
            api_gateway = get_api_gateway_client()
            api_gateway.post_to_connection(
                ConnectionId=self.connection_id,
                Data=json.dumps(event, cls=DecimalEncoder)
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "GoneException":
                self.connection_id = None  # Connection died
            else:
                raise

    @callable
    def receive_command(self, command: str, **kwargs) -> Optional[Dict]:
        """Entry point for WebSocket commands."""
        method = getattr(self, command, None)
        if method and callable(method) and hasattr(method, "_is_callable"):
            return method(**kwargs)
        return {"error": f"Unknown command: {command}"}

    @callable  
    def attach_connection(self, connection_id: str) -> Dict[str, str]:
        """Attach a WebSocket connection to this entity."""
        self.connection_id = connection_id
        return {"status": "connected", "entity_uuid": self.uuid}

    @callable
    def detach_connection(self) -> Dict[str, str]:
        """Detach the WebSocket connection from this entity."""
        self.connection_id = None
        return {"status": "disconnected", "entity_uuid": self.uuid}
```

---

## WebSocket Handlers

### Lambda Functions (No Connection Aspect Needed!)

**File:** `backend/aspects/websocket_handlers.py`

```python
"""WebSocket Lambda handlers - bridge between API Gateway and entities."""

import json
import logging
import os
from uuid import uuid4

from aspects.aws_client import get_dynamodb_table, get_api_gateway_client
from aspects.thing import Call

# Optional: Map connection_id to entity_uuid for quick lookups
# This avoids scanning tables on every command
# Could use DynamoDB, ElastiCache, or just store in entity itself (our choice!)


def connect_handler(event: dict, context: dict) -> dict:
    """
    Handle WebSocket $connect.
    Just accepts the connection—entity binding happens separately via command.
    """
    connection_id = event["requestContext"]["connectionId"]
    logging.info(f"WebSocket connected: {connection_id}")
    
    # Connection is accepted but not yet bound to any entity
    # Client must send a "possess" command to attach to an entity
    return {"statusCode": 200}


def disconnect_handler(event: dict, context: dict) -> dict:
    """
    Handle WebSocket $disconnect.
    Find the entity with this connection_id and clear it.
    """
    connection_id = event["requestContext"]["connectionId"]
    logging.info(f"WebSocket disconnected: {connection_id}")
    
    # Find entity with this connection and detach
    # Since connection_id is stored on the entity, we need to scan
    # OR: maintain an index (see serverless.yml changes)
    _detach_connection_from_entity(connection_id)
    
    return {"statusCode": 200}


def command_handler(event: dict, context: dict) -> dict:
    """
    Handle WebSocket messages.
    Routes to entity.receive_command() via SNS (preserves event flow).
    """
    connection_id = event["requestContext"]["connectionId"]
    body = json.loads(event.get("body", "{}"))
    
    command = body.get("command")
    entity_uuid = body.get("entity_uuid")  # For "possess" command
    entity_aspect = body.get("entity_aspect")  # e.g., "Land", "Location"
    data = body.get("data", {})
    
    if not command:
        return {"statusCode": 400, "body": json.dumps({"error": "Missing command"})}
    
    # Special case: "possess" command to bind connection to entity
    if command == "possess":
        if not entity_uuid or not entity_aspect:
            return {
                "statusCode": 400, 
                "body": json.dumps({"error": "possess requires entity_uuid and entity_aspect"})
            }
        
        # Route attach_connection to the entity
        Call(
            tid=str(uuid4()),
            originator=connection_id,
            uuid=entity_uuid,
            aspect=entity_aspect,
            action="attach_connection",
            connection_id=connection_id
        ).now()
        
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "possessing", "entity_uuid": entity_uuid})
        }
    
    # For all other commands: find entity by connection_id and route to it
    entity_info = _find_entity_by_connection(connection_id)
    if not entity_info:
        return {
            "statusCode": 403,
            "body": json.dumps({"error": "Connection not bound to any entity. Send 'possess' first."})
        }
    
    # Route to entity.receive_command via SNS
    Call(
        tid=str(uuid4()),
        originator=connection_id,
        uuid=entity_info["uuid"],
        aspect=entity_info["aspect"],
        action="receive_command",
        command=command,
        **data
    ).now()
    
    return {"statusCode": 200}


def _find_entity_by_connection(connection_id: str) -> Optional[dict]:
    """
    Find entity with given connection_id.
    Uses the connection-entity GSI (see serverless.yml).
    """
    # Query using the GSI on the thing table
    table = get_dynamodb_table("THING_TABLE")
    
    # Scan with filter (inefficient but works for now)
    # OR use GSI if we add one
    # For now: iterate through possible aspects or use a Connection table as index
    
    # BETTER APPROACH: Add GSI to thing-table for connection_id lookup
    response = table.scan(
        FilterExpression="connection_id = :cid",
        ExpressionAttributeValues={":cid": connection_id}
    )
    
    if response.get("Items"):
        item = response["Items"][0]
        return {"uuid": item["uuid"], "aspect": item.get("aspect", "Thing")}
    return None


def _detach_connection_from_entity(connection_id: str) -> None:
    """Clear connection_id from whatever entity has it."""
    entity_info = _find_entity_by_connection(connection_id)
    if entity_info:
        Call(
            tid=str(uuid4()),
            originator="",
            uuid=entity_info["uuid"],
            aspect=entity_info["aspect"],
            action="detach_connection"
        ).now()
```

---

## Serverless.yml Changes

**Add to `provider.environment`:**
```yaml
WEBSOCKET_API_ENDPOINT: !GetAtt WebSocketApi.ApiEndpoint
```

**Add Lambda functions:**
```yaml
functions:
  # ... existing aspects ...

  ws-connect:
    handler: aspects/websocket_handlers.connect_handler
    iamRoleStatements:
      - Effect: Allow
        Action:
          - execute-api:ManageConnections
        Resource: 
          - "arn:aws:execute-api:#{AWS::Region}:#{AWS::AccountId}:#{WebSocketApi}/*"
    events:
      - websocket:
          route: $connect

  ws-disconnect:
    handler: aspects/websocket_handlers.disconnect_handler
    iamRoleStatements:
      - Effect: Allow
        Action:
          - execute-api:ManageConnections
        Resource: 
          - "arn:aws:execute-api:#{AWS::Region}:#{AWS::AccountId}:#{WebSocketApi}/*"
    events:
      - websocket:
          route: $disconnect

  ws-command:
    handler: aspects/websocket_handlers.command_handler
    iamRoleStatements:
      - Effect: Allow
        Action:
          - execute-api:ManageConnections
          - dynamodb:Scan  # For finding entity by connection_id
        Resource: 
          - "arn:aws:execute-api:#{AWS::Region}:#{AWS::AccountId}:#{WebSocketApi}/*"
          - { "Fn::GetAtt": ["ThingDynamoDBTable", "Arn" ] }
    events:
      - websocket:
          route: command
```

**Add WebSocket API resource:**
```yaml
resources:
  Resources:
    # ... existing tables ...

    WebSocketApi:
      Type: AWS::ApiGatewayV2::Api
      Properties:
        Name: ${self:service}-websocket-${self:provider.stage}
        ProtocolType: WEBSOCKET
        RouteSelectionExpression: "$request.body.action"

    WebSocketDeployment:
      Type: AWS::ApiGatewayV2::Deployment
      DependsOn:
        - WsConnectRoute
        - WsDisconnectRoute
        - WsCommandRoute
      Properties:
        ApiId: !Ref WebSocketApi

    WebSocketStage:
      Type: AWS::ApiGatewayV2::Stage
      Properties:
        StageName: ${self:provider.stage}
        ApiId: !Ref WebSocketApi
        DeploymentId: !Ref WebSocketDeployment

    WsConnectRoute:
      Type: AWS::ApiGatewayV2::Route
      Properties:
        ApiId: !Ref WebSocketApi
        RouteKey: $connect
        AuthorizationType: NONE
        Target: !Join ["/", ["integrations", !Ref WsConnectIntegration]]

    WsConnectIntegration:
      Type: AWS::ApiGatewayV2::Integration
      Properties:
        ApiId: !Ref WebSocketApi
        IntegrationType: AWS_PROXY
        IntegrationUri: 
          Fn::Join:
            - ""
            - - "arn:aws:apigateway:"
              - Ref: AWS::Region
              - ":lambda:path/2015-03-31/functions/"
              - Fn::GetAtt: [WsConnectLambdaFunction, Arn]
              - "/invocations"

    # ... similar for disconnect and command ...
```

---

## Where API Gateway Client Lives

**File:** `backend/aspects/aws_client.py`

```python
def get_api_gateway_client():
    """Get API Gateway Management API client for WebSocket operations."""
    endpoint = get_localstack_endpoint()
    
    # WebSocket endpoint is different per connection
    # We need the callback URL from environment
    callback_url = os.environ.get("WEBSOCKET_API_ENDPOINT")
    
    if endpoint:
        # LocalStack mode
        return boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=f"{endpoint}/ws",
            region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        )
    
    # Real AWS - use the WebSocket API endpoint
    if callback_url:
        return boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=callback_url,
            region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1"),
        )
    
    raise ValueError("WEBSOCKET_API_ENDPOINT not set")
```

---

## How Entity Pushes Events Without Breaking Existing Flow

**Key insight:** The event flow through SNS is unchanged. `push_event()` is an **additional** side channel for real-time delivery.

```python
# Existing flow (unchanged):
Call(tid, originator, uuid, aspect, action, **data).now()
  ↓
SNS Topic
  ↓
Location Lambda, Land Lambda, etc.
  ↓
DynamoDB

# New: Within any callable method, entity can push to WebSocket:
@callable
def move(self, destination: str) -> None:
    old_location = self.location
    self.location = destination
    
    # Existing: Broadcast via SNS
    self.call(self.uuid, "Location", "notify_move", 
              old=old_location, new=destination).now()
    
    # NEW: Also push directly to connected player
    self.push_event({
        "event": "you_moved",
        "from": old_location,
        "to": destination,
        "timestamp": datetime.utcnow().isoformat()
    })
```

**Events that entities might push:**
- Movement confirmation ("You moved north")
- Combat results ("You hit the goblin for 5 damage")
- Inventory changes
- Chat messages directed at the player
- System messages

**Viewport handling:** Since the entity knows what the player should see, it decides what to push. No complex viewport query system needed!

---

## Connection Flow Summary

```
1. PLAYER connects WebSocket
   ↓
   ws-connect Lambda accepts connection
   ↓
   Player gets connection_id (transparent to them)

2. PLAYER sends: {"action": "command", "command": "possess", 
                 "entity_uuid": "abc-123", "entity_aspect": "LandCreator"}
   ↓
   ws-command Lambda routes to entity
   ↓
   entity.attach_connection(connection_id) sets entity.connection_id

3. ENTITY does something (tick, move, etc.)
   ↓
   SNS event flows to other aspects
   ↓
   entity.push_event() sends to WebSocket if connected

4. PLAYER sends command: {"action": "command", "command": "move", 
                         "data": {"direction": "north"}}
   ↓
   ws-command Lambda finds entity by connection_id
   ↓
   Routes to entity.receive_command("move", direction="north")
   ↓
   Entity processes command via its callable methods

5. PLAYER disconnects (or connection drops)
   ↓
   ws-disconnect Lambda fires
   ↓
   Finds entity by connection_id, calls entity.detach_connection()
   ↓
   entity.connection_id = None
   ↓
   Entity continues existing in the world
```

---

## Files to Create/Modify

### Modified Files

| File | Changes |
|------|---------|
| `backend/aspects/thing.py` | Add `connection_id` property, `push_event()`, `receive_command()`, `attach_connection()`, `detach_connection()` |
| `backend/aspects/aws_client.py` | Add `get_api_gateway_client()` |
| `backend/serverless.yml` | Add WebSocket API, 3 Lambda handlers, IAM permissions |

### New Files

| File | Purpose |
|------|---------|
| `backend/aspects/websocket_handlers.py` | `connect_handler`, `disconnect_handler`, `command_handler` |

---

## Key Differences from Old Design

| Aspect | Old (Wrong) | New (Right) |
|--------|-------------|-------------|
| Connection state | Stored in separate `Connection` table | Stored directly on entity (`entity.connection_id`) |
| Connection aspect | Separate `Connection` aspect subscribed to all SNS events | No Connection aspect—entities push their own events |
| Viewport logic | Complex GSI queries for "who can see this" | Entity decides what to push to its connection |
| Command routing | Connection aspect looked up entity, then routed | WebSocket handler finds entity by connection_id, routes directly |
| Disconnect cleanup | Delete Connection record | Clear `entity.connection_id` |
| World continuity | Entity might be "owned" by connection | Entity exists independently—connection is just I/O |

---

## LocalStack Support

Add `apigateway` to LocalStack services:

```yaml
# docker-compose.yml
services:
  localstack:
    image: localstack/localstack
    environment:
      - SERVICES=dynamodb,sns,stepfunctions,lambda,apigateway
    ports:
      - "4566:4566"
      - "4510-4559:4510-4559"  # WebSocket ports
```

For local development without WebSocket:
- Simulate `push_event()` by logging to stdout
- Commands via HTTP POST to `ws-command` Lambda
- Poll for events via separate endpoint

---

## Summary

| Question | Answer |
|----------|--------|
| **Who holds connection?** | The entity (`entity.connection_id`) |
| **WebSocket is entity?** | No—it's just a pipe |
| **How push events?** | Entity calls `self.push_event()` inside callable methods |
| **How receive commands?** | `entity.receive_command()` routes to callable methods |
| **API Gateway client?** | `aws_client.get_api_gateway_client()` |
| **Find entity by connection?** | Scan thing-table for `connection_id` (or add GSI) |
| **Connection lifecycle?** | `attach_connection()` on possess, `detach_connection()` on disconnect |
| **Existing event flow?** | Unchanged—WebSocket is additive |
