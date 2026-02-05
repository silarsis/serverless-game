# WebSocket Implementation Summary

## Authentication & Authorization (New)

### JWT-Based Authentication

**Implementation:**
- JWT passed as `X-Api-Key` header in WebSocket `$connect` request
- JWT payload contains `sub` (player_uuid) and optional admin flags
- Agents store JWT like API credentials for reconnection

**New Files:**
- `backend/aspects/auth.py` - JWT verification and player identity extraction
- `backend/aspects/decorators.py` - `@player_command`, `@admin_only`, `@system_entity` decorators

**Connect Handler with Auth:**
```python
def connect_handler(event: dict, context: dict) -> dict:
    connection_id = event["requestContext"]["connectionId"]
    headers = event.get("headers", {})
    token = headers.get("X-Api-Key") or headers.get("x-api-key")
    
    if not token:
        return {"statusCode": 401, "body": "Missing authentication"}
    
    try:
        claims = verify_jwt(token)
        player_uuid = claims["sub"]
    except JWTError:
        return {"statusCode": 403, "body": "Invalid token"}
    
    # Get or create player entity
    player = get_or_create_player(player_uuid, connection_id)
    return {"statusCode": 200}
```

### Authorization Rules

| Rule | Implementation |
|------|----------------|
| Player possession | Player can only possess entities where `uuid == player_uuid` or `owner_uuid == player_uuid` |
| System entities | Entities with `is_system=True` cannot be possessed (admin-only) |
| No cross-entity claiming | Players cannot possess other players' entities (yet) |

### Command Security (@player_command)

**Decorator Implementation:**
```python
def player_command(func: Callable) -> Callable:
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # Block system entities
        if getattr(self, 'is_system', False):
            return {"error": "System entities cannot be player-controlled"}
        
        # Validate connection ownership
        caller = kwargs.pop('_caller_connection_id', None)
        if caller and caller != getattr(self, 'connection_id', None):
            return {"error": "Not authorized"}
        
        return func(self, *args, **kwargs)
    
    wrapper._is_player_command = True
    wrapper._is_callable = True
    return wrapper
```

**Usage in Aspect Classes:**
```python
class Land(Thing):
    @player_command  # Exposed via WebSocket
    def move(self, direction: str) -> dict:
        return {"status": "moved"}
    
    @callable  # Internal SNS only - NOT WebSocket
    def internal_update(self, data: dict) -> dict:
        return {"status": "updated"}
```

**Security Distinctions:**
- `@player_command` → WebSocket ✓ | SNS ✓ | Validates ownership
- `@callable` → WebSocket ✗ | SNS ✓ | Internal only
- `@admin_only` → WebSocket ✓ (admin) | SNS ✓ (admin) | Admin JWT required

---

## What Changed Based on Clarification

**Critical insight:** The entity holds the connection. No separate Connection aspect/table.

### Architecture Shift

```
BEFORE (wrong):
  WebSocket → Connection aspect → finds entity → routes
  
AFTER (correct):
  WebSocket ────────▶ entity (entity.connection_id = ws-id)
               ▲
               └──── entity.push_event() ──┘
```

---

## Files Changed

### 1. `backend/aspects/thing.py` - Add 4 methods + 1 property

**Lines to add (~50 lines):**

```python
from botocore.exceptions import ClientError
from aspects.aws_client import get_api_gateway_client

class Thing(UserDict):
    # ... existing code ...
    
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
    
    def push_event(self, event: EventType) -> None:
        """Send event to connected WebSocket if present."""
        if not self.connection_id:
            return
        try:
            api_gateway = get_api_gateway_client()
            api_gateway.post_to_connection(
                ConnectionId=self.connection_id,
                Data=json.dumps(event, cls=DecimalEncoder)
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "GoneException":
                self.connection_id = None
    
    @callable
    def attach_connection(self, connection_id: str) -> EventType:
        self.connection_id = connection_id
        return {"status": "connected"}
    
    @callable
    def detach_connection(self) -> EventType:
        self.connection_id = None
        return {"status": "disconnected"}
    
    @callable
    def receive_command(self, command: str, **kwargs) -> EventType:
        """WebSocket commands route here."""
        method = getattr(self, command, None)
        if method and callable(method) and hasattr(method, "_is_callable"):
            return method(**kwargs)
        return {"error": f"Unknown command: {command}"}
```

### 2. `backend/aspects/aws_client.py` - Add 1 function

```python
def get_api_gateway_client():
    """Get API Gateway Management API client for WebSocket post_to_connection."""
    callback_url = os.environ.get("WEBSOCKET_API_ENDPOINT")
    endpoint = get_localstack_endpoint()
    
    if endpoint:
        return boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=f"{endpoint}/_aws/execute-api",
            region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        )
    
    if callback_url:
        return boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=callback_url,
            region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1"),
        )
    
    raise ValueError("WEBSOCKET_API_ENDPOINT not set")
```

### 3. `backend/aspects/websocket_handlers.py` - NEW FILE

**Purpose:** Lambda handlers for WebSocket $connect, $disconnect, and custom commands.

**Key functions:**
- `connect_handler`: Accept connection (no entity binding yet)
- `disconnect_handler`: Find entity with this connection_id, call `detach_connection()`
- `command_handler`: Route commands to `entity.receive_command()`

**Special `possess` command:**
```json
{"action": "command", "command": "possess", "data": {"entity_uuid": "abc", "entity_aspect": "Land"}}
```
This binds the WebSocket to an entity by setting `entity.connection_id`.

### 4. `backend/serverless.yml` - Add WebSocket API + 3 Lambda functions

**Add to `provider.environment`:**
```yaml
WEBSOCKET_API_ENDPOINT: !GetAtt WebSocketApi.ApiEndpoint
```

**Add to `functions`:**
```yaml
ws-connect:
  handler: aspects/websocket_handlers.connect_handler
  events:
    - websocket:
        route: $connect

ws-disconnect:
  handler: aspects/websocket_handlers.disconnect_handler
  events:
    - websocket:
        route: $disconnect

ws-command:
  handler: aspects/websocket_handlers.command_handler
  events:
    - websocket:
        route: command
```

**Add to `resources`:**
- `WebSocketApi` (AWS::ApiGatewayV2::Api)
- `WebSocketDeployment`
- `WebSocketStage`
- Routes and integrations for $connect, $disconnect, command

---

## How It Works

### Entity Pushes Events (No Breaking Changes)

```python
@callable
def some_action(self) -> EventType:
    # Existing: SNS event flow
    self.call(other_uuid, "Aspect", "action", data).now()
    
    # NEW: Also push to connected player if present
    self.push_event({
        "event": "something_happened",
        "to_you": True,
        "details": "..."
    })
    
    return {"status": "done"}
```

**Key point:** `push_event()` is additive. If no connection, it's a no-op. Existing SNS flow unchanged.

### Commands Flow In

```
Player sends: {"action": "command", "command": "move", "data": {"direction": "north"}}
    ↓
API Gateway → ws-command Lambda
    ↓
Find entity where connection_id = ws-connection-id
    ↓
SNS: Call(entity_uuid, aspect, "receive_command", command="move", direction="north")
    ↓
Entity Lambda → entity.receive_command("move", direction="north")
    ↓
entity.move(direction="north")  # routed to callable method
    ↓
pushes event back: "You moved north"
```

---

## Answers to Original Questions

### 1. Revised Design
✅ **Entity-centric:** Entity holds `connection_id` field. WebSocket is just a pipe.

### 2. Minimal Changes to Thing Class
✅ **4 methods + 1 property:** `connection_id` (property), `push_event()`, `attach_connection()`, `detach_connection()`, `receive_command()`

### 3. WebSocket Handlers
✅ **3 handlers:** `connect`, `disconnect`, `command`. No Connection aspect needed.

### 4. Entity Pushes Events Without Breaking Flow
✅ **Additive approach:** `push_event()` called inside callable methods. If no connection, no-op. SNS flow continues unchanged.

### 5. API Gateway Client Location
✅ **`aws_client.py`:** `get_api_gateway_client()` function. Used by `push_event()` in Thing class.

---

## Production Considerations

### Finding Entity by Connection ID

Current implementation scans the Thing table. For production:

```yaml
# Add GSI to ThingDynamoDBTable in serverless.yml
GlobalSecondaryIndexes:
  - IndexName: connection-index
    KeySchema:
      - AttributeName: connection_id
        KeyType: HASH
    Projection:
      ProjectionType: KEYS_ONLY
```

Then in `_find_entity_by_connection()`:
```python
response = table.query(
    IndexName="connection-index",
    KeyConditionExpression=Key("connection_id").eq(connection_id)
)
```

### Connection Cleanup on Zombie Connections

The `push_event()` method handles `GoneException` by setting `connection_id = None`. This automatically cleans up dead connections.

### Multiple Connections Per Entity

Current design: one connection per entity. For multiple observers:
- Entity pushes to all connections
- Or use a separate pub/sub system

---

## Local Development

```yaml
# docker-compose.yml - add apigateway
services:
  localstack:
    environment:
      - SERVICES=dynamodb,sns,stepfunctions,lambda,apigateway
```

WebSocket endpoint in LocalStack: `ws://localhost:4566/_aws/execute-api/{api-id}/{stage}`

---

## Example: Aspect with @player_command

```python
"""Example player-controllable entity with WebSocket security."""

from aspects.thing import Thing
from aspects.decorators import player_command, callable, system_entity, admin_only

class PlayerCharacter(Thing):
    """A player-controlled character in the game world."""
    
    @classmethod
    def create_for_player(cls, player_uuid: str, connection_id: str) -> "PlayerCharacter":
        """Factory method to create a new player character on first connect."""
        return cls(
            uuid=player_uuid,  # Entity UUID matches player UUID
            player_uuid=player_uuid,
            connection_id=connection_id,
            location="spawn_point",
            health=100
        )
    
    @player_command
    def move(self, direction: str) -> dict:
        """
        Move in a direction - exposed to WebSocket.
        
        Can only be called by the player who owns this character.
        """
        old_location = self.location
        self.location = self._calculate_move(direction)
        
        # Push event to the connected player
        self.push_event({
            "event": "you_moved",
            "from": old_location,
            "to": self.location,
            "direction": direction
        })
        
        return {"status": "moved", "location": self.location}
    
    @player_command
    def say(self, message: str) -> dict:
        """Say something - exposed to WebSocket."""
        self.broadcast_to_nearby({
            "event": "speech",
            "from": self.uuid,
            "text": message
        })
        return {"status": "said", "message": message}
    
    @player_command
    def look(self) -> dict:
        """Look around - exposed to WebSocket."""
        surroundings = self._get_surroundings()
        return {"status": "looked", "surroundings": surroundings}
    
    @callable  # NOT @player_command - internal only
    def take_damage(self, amount: int, source: str) -> dict:
        """Take damage - only callable via SNS from other aspects."""
        self.health -= amount
        
        # Notify player if connected
        self.push_event({
            "event": "damaged",
            "amount": amount,
            "source": source,
            "health_remaining": self.health
        })
        
        return {"status": "damaged", "health": self.health}
    
    @callable  # Internal only
    def heal(self, amount: int) -> dict:
        """Heal - only callable via SNS from other aspects."""
        self.health = min(100, self.health + amount)
        return {"status": "healed", "health": self.health}


@system_entity
class WorldManager(Thing):
    """System entity - cannot be possessed by players."""
    
    @admin_only
    def shutdown(self, reason: str = "") -> dict:
        """Shutdown the world - admin only."""
        return {"status": "shutdown_initiated", "reason": reason}
    
    @callable
    def tick(self) -> dict:
        """Perform world tick - callable by other system entities."""
        return {"status": "world_ticked"}
```

---

## File Summary

| File | Status | Purpose |
|------|--------|---------|
| `WEBSOCKET_DESIGN.md` | ✅ Updated | Full architecture + auth section |
| `WEBSOCKET_IMPLEMENTATION_SUMMARY.md` | ✅ New | Quick reference with auth details |
| `backend/aspects/websocket_handlers.py` | ✅ New | WebSocket Lambda handlers |
| `backend/aspects/decorators.py` | ✅ New | `@player_command`, `@admin_only`, `@system_entity` |
| `backend/aspects/auth.py` | 📝 Needed | JWT verification, `get_or_create_player()` |
| `backend/aspects/thing_websocket_patch.py` | ✅ New | Thing.py changes reference |
| `backend/aspects/aws_client.py` | 📝 Modified | Added `get_api_gateway_client()` |
| `backend/aspects/thing.py` | ⏳ Pending | Apply patch from thing_websocket_patch.py |
| `backend/serverless.yml` | ⏳ Pending | Add WebSocket API, auth headers, handlers |
