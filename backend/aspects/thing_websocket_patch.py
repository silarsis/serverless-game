"""WebSocket patch for Thing: adds connection management, push, and routing methods."""

import json
import logging
from collections import UserDict
from typing import Optional
from botocore.exceptions import ClientError
from aspects.aws_client import get_api_gateway_client


class Thing(UserDict):
    """Adds WebSocket support to the Thing class for real-time client connections."""

    @property
    def connection_id(self) -> Optional[str]:
        """Get the WebSocket connection ID if connected, else None."""
        return self.data.get("connection_id")

    @connection_id.setter
    def connection_id(self, value: Optional[str]) -> None:
        """Set or clear the WebSocket connection ID."""
        if value:
            self.data["connection_id"] = value
        else:
            self.data.pop("connection_id", None)
        self._save()

    def push_event(self, event: dict) -> None:
        """Push an event to the connected WebSocket client if connection exists."""
        from aspects.thing import DecimalEncoder  # avoid import loops

        if not self.connection_id:
            return
        try:
            api_gateway = get_api_gateway_client()
            api_gateway.post_to_connection(
                ConnectionId=self.connection_id,
                Data=json.dumps(event, cls=DecimalEncoder),
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code == "GoneException":
                self.connection_id = None
            else:
                logging.error(f"Failed to push event to {self.connection_id}: {e}")

    @callable
    def attach_connection(self, connection_id: str) -> dict:
        """Attach a WebSocket connection to this entity."""
        self.connection_id = connection_id
        return {"status": "connected", "entity_uuid": self.uuid}

    @callable
    def detach_connection(self) -> dict:
        """Detach the WebSocket connection from this entity."""
        self.connection_id = None
        return {"status": "disconnected", "entity_uuid": self.uuid}

    @callable
    def receive_command(self, command: str, **kwargs) -> dict:
        """Route a received command from WebSocket to a callable method, if defined."""
        method = getattr(self, command, None)
        if method and callable(method) and hasattr(method, "_is_callable"):
            return method(**kwargs)
        return {"error": f"Unknown command: {command}"}


class Location(Thing):
    """Example subclass: adds movement and event push capability with WebSocket."""

    @callable
    def move(self, destination: str) -> dict:
        """Move to a new location and notify via SNS and WebSocket."""
        old_location = self.location
        self.location = destination
        self.call(self.uuid, "Location", "notify_move", old=old_location, new=destination).now()
        self.push_event(
            {
                "event": "you_moved",
                "from": old_location,
                "to": destination,
                "timestamp": "2025-01-01T00:00:00Z",
            }
        )
        return {"status": "moved", "to": destination}
