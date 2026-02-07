#!/usr/bin/env python3
"""Reference AI agent for the serverless game.

Authenticates via API key, connects to WebSocket, possesses an entity,
and interacts with the world using the same interface as human players.

Usage:
    python ai_agent.py --api-key YOUR_API_KEY --api-url https://your-api.com
    python ai_agent.py --api-key YOUR_API_KEY --api-url http://localhost:4566
"""

import argparse
import json
import logging
import sys
import time
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


def authenticate(api_url: str, api_key: str) -> dict:
    """Authenticate with the game API using an API key.

    Args:
        api_url: Base URL of the game API.
        api_key: API key for bot authentication.

    Returns:
        dict with jwt and user info.
    """
    import urllib.request

    url = f"{api_url}/api/auth/login"
    body = json.dumps({"api_key": api_key}).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    if not result.get("success"):
        raise RuntimeError(f"Authentication failed: {result}")

    logger.info(f"Authenticated as {result['user'].get('bot_name', 'unknown')}")
    return result


class GameBot:
    """A simple AI agent that explores the world."""

    def __init__(self, jwt: str, entity_uuid: str, ws_url: str):
        """Initialize the bot.

        Args:
            jwt: Internal JWT from authentication.
            entity_uuid: UUID of the entity to possess.
            ws_url: WebSocket URL of the game server.
        """
        self.jwt = jwt
        self.entity_uuid = entity_uuid
        self.ws_url = ws_url
        self.ws = None
        self.running = False
        self.command_history = []
        self.current_location = None
        self.available_exits = []

    def connect(self):
        """Connect to the game WebSocket."""
        try:
            import websocket
        except ImportError:
            logger.error("websocket-client package required: pip install websocket-client")
            sys.exit(1)

        url = f"{self.ws_url}?{urlencode({'token': self.jwt})}"
        self.ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self.running = True
        self.ws.run_forever()

    def _on_open(self, ws):
        """Handle WebSocket connection opened."""
        logger.info("Connected to game server")
        # Possess our entity
        self._send_command("possess", entity_uuid=self.entity_uuid, entity_aspect="Land")
        time.sleep(0.5)
        # Look around
        self._send_command("look")

    def _on_message(self, ws, message):
        """Handle incoming game events."""
        try:
            event = json.loads(message)
        except json.JSONDecodeError:
            logger.warning(f"Received non-JSON message: {message}")
            return

        event_type = event.get("type", "unknown")
        logger.info(f"Event: {event_type} - {json.dumps(event, indent=2)}")

        # React to events
        if event_type == "look":
            self._handle_look(event)
        elif event_type == "move":
            self._handle_move(event)
        elif event_type == "say":
            self._handle_say(event)
        elif event_type == "arrive":
            self._handle_arrive(event)
        elif event_type == "error":
            logger.warning(f"Error from server: {event.get('message')}")

    def _on_error(self, ws, error):
        """Handle WebSocket errors."""
        logger.error(f"WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket disconnection."""
        logger.info(f"Disconnected: {close_status_code} {close_msg}")
        self.running = False

    def _send_command(self, command: str, **data):
        """Send a command to the game server."""
        msg = json.dumps({"command": command, "data": data})
        self.command_history.append(command)
        if self.ws:
            self.ws.send(msg)
            logger.debug(f"Sent: {command} {data}")

    def _handle_look(self, event):
        """Process look results and decide next action."""
        self.current_location = event.get("coordinates")
        self.available_exits = event.get("exits", [])
        desc = event.get("description", "")
        logger.info(f"Location: {self.current_location} - {desc}")
        logger.info(f"Exits: {self.available_exits}")

        # Simple exploration: pick a random exit and move
        self._explore()

    def _handle_move(self, event):
        """Process movement results."""
        self.current_location = event.get("coordinates")
        self.available_exits = event.get("exits", [])
        desc = event.get("description", "")
        logger.info(f"Moved to: {self.current_location} - {desc}")

        # Continue exploring after a delay
        time.sleep(2)
        self._explore()

    def _handle_say(self, event):
        """React to speech from other entities."""
        speaker = event.get("speaker", "someone")
        message = event.get("message", "")
        logger.info(f'{speaker} says: "{message}"')

        # Simple response: greet back
        if any(word in message.lower() for word in ["hello", "hi", "greet", "met"]):
            self._send_command("say", message=f"Hello, {speaker}! I'm just exploring.")

    def _handle_arrive(self, event):
        """React to someone arriving at our location."""
        actor = event.get("actor", "someone")
        logger.info(f"{actor} arrives.")
        self._send_command("say", message=f"Hello there, {actor}!")

    def _explore(self):
        """Pick a direction and move."""
        import random

        if not self.available_exits:
            logger.info("No exits available, waiting...")
            time.sleep(5)
            self._send_command("look")
            return

        direction = random.choice(self.available_exits)
        logger.info(f"Exploring: moving {direction}")
        self._send_command("move", direction=direction)


def main():
    """Run the AI agent."""
    parser = argparse.ArgumentParser(description="Serverless Game AI Agent")
    parser.add_argument("--api-key", required=True, help="API key for bot authentication")
    parser.add_argument(
        "--api-url",
        default="http://localhost:4566",
        help="Base URL of the game API",
    )
    parser.add_argument(
        "--ws-url",
        default=None,
        help="WebSocket URL (auto-detected from API if not set)",
    )
    parser.add_argument(
        "--entity-uuid",
        default=None,
        help="UUID of entity to possess (creates new if not set)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Authenticate
    auth_result = authenticate(args.api_url, args.api_key)
    jwt = auth_result["jwt"]
    entity_uuid = args.entity_uuid or auth_result["user"].get("entity_uuid", "")

    if not entity_uuid:
        logger.error("No entity UUID provided and none returned from auth. Use --entity-uuid.")
        sys.exit(1)

    # Determine WebSocket URL
    ws_url = args.ws_url
    if not ws_url:
        # Default: assume same host as API but with wss:// scheme
        ws_url = args.api_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = ws_url.rstrip("/") + "/ws"

    logger.info(f"Connecting to {ws_url}")

    # Connect and run
    bot = GameBot(jwt=jwt, entity_uuid=entity_uuid, ws_url=ws_url)
    try:
        bot.connect()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
