"""
MINIMAL CHANGES TO thing.py for WebSocket support

This file shows the exact changes needed to add WebSocket support to the Thing class.
Apply these changes to backend/aspects/thing.py
"""

# ===== 1. ADD TO IMPORTS =====

from typing import Optional  # Already imported, just add Optional if not present
from botocore.exceptions import ClientError
from aspects.aws_client import get_api_gateway_client  # Add this import


# ===== 2. ADD TO Thing CLASS =====

class Thing(UserDict):
    # ... existing code ...

    # ===== ADD THESE METHODS =====

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

    def push_event(self, event: EventType) -> None:
        """
        Push an event to the connected WebSocket client.
        Called when something happens that the player should see.
        If no connection, this is a no-op (world continues normally).
        """
        if not self.connection_id:
            return

        try:
            api_gateway = get_api_gateway_client()
            api_gateway.post_to_connection(
                ConnectionId=self.connection_id,
                Data=json.dumps(event, cls=DecimalEncoder)
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code == "GoneException":
                # Connection died, clean it up
                self.connection_id = None
            else:
                logging.error(f"Failed to push event to {self.connection_id}: {e}")

    @callable
    def attach_connection(self, connection_id: str) -> EventType:
        """Attach a WebSocket connection to this entity."""
        self.connection_id = connection_id
        return {"status": "connected", "entity_uuid": self.uuid}

    @callable
    def detach_connection(self) -> EventType:
        """Detach the WebSocket connection from this entity."""
        self.connection_id = None
        return {"status": "disconnected", "entity_uuid": self.uuid}

    @callable
    def receive_command(self, command: str, **kwargs) -> EventType:
        """
        Receive a command from the WebSocket.
        Routes to the named callable method.
        Override in subclasses for custom command handling.
        """
        method = getattr(self, command, None)
        if method and callable(method) and hasattr(method, "_is_callable"):
            return method(**kwargs)
        return {"error": f"Unknown command: {command}"}

    # ... rest of existing code ...


# ===== USAGE EXAMPLE in subclass =====

class Location(Thing):
    @callable
    def move(self, destination: str) -> EventType:
        """Move to a new location."""
        old_location = self.location
        self.location = destination

        # Broadcast to world via SNS (existing pattern)
        self.call(self.uuid, "Location", "notify_move",
                  old=old_location, new=destination).now()

        # Push directly to connected player (NEW)
        self.push_event({
            "event": "you_moved",
            "from": old_location,
            "to": destination,
            "timestamp": "2025-01-01T00:00:00Z"
        })

        return {"status": "moved", "to": destination}
