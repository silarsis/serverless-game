#!/usr/bin/env python3
"""Reference AI agent for the serverless game.

Authenticates via API key, connects to WebSocket, possesses an entity,
explores the world, and periodically submits suggestions based on what
it encounters.

Usage:
    python ai_agent.py --api-key YOUR_API_KEY --api-url https://your-api.com
    python ai_agent.py --api-key dev --api-url http://localhost:8000
"""

import argparse
import json
import logging
import random
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
        dict with jwt, user info, and optionally entity info.
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


# ---------------------------------------------------------------------------
# Suggestion templates — used when the agent doesn't have an LLM available
# ---------------------------------------------------------------------------

SUGGESTION_TEMPLATES = [
    "It would be nice if there were weather effects that change the room descriptions",
    "A day/night cycle would make exploration more interesting",
    "Allow players to leave notes or signs in rooms for others to find",
    "Add ambient sounds or text-based atmosphere descriptions",
    "Let entities build simple structures at locations",
    "A map command that shows explored areas would be helpful",
    "Trading or bartering between entities would add interaction depth",
    "Quests or objectives that generate dynamically from the world state",
    "Allow customizing your entity's appearance and description",
    "Add a journal or log command to review what happened recently",
    "It would be fun to have seasonal events or changes",
    "Allow naming locations so you can navigate by name",
    "Portals or fast-travel between distant locations",
    "Riddles or puzzles in some rooms for extra rewards",
    "The ability to plant seeds and grow things over time",
]


class GameBot:
    """An AI agent that explores the world and submits suggestions."""

    def __init__(self, jwt: str, entity_uuid: str, ws_url: str, suggest_interval: int = 10):
        """Initialize the bot.

        Args:
            jwt: Internal JWT from authentication.
            entity_uuid: UUID of the entity to possess (empty to auto-create).
            ws_url: WebSocket URL of the game server.
            suggest_interval: Rooms explored between suggestions.
        """
        self.jwt = jwt
        self.entity_uuid = entity_uuid
        self.ws_url = ws_url
        self.ws = None
        self.running = False
        self.command_history = []
        self.current_location = None
        self.available_exits = []
        self.rooms_explored = 0
        self.suggest_interval = suggest_interval
        self.suggestions_made = set()
        self.known_suggestions = []

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
        # Possess our entity (or let server auto-create)
        if self.entity_uuid:
            self._send_command("possess", entity_uuid=self.entity_uuid, entity_aspect="Land")
        else:
            self._send_command("possess")
        time.sleep(0.5)
        # Discover commands
        self._send_command("help")
        time.sleep(0.3)
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
        logger.info(f"Event: {event_type} - {json.dumps(event, indent=2)[:200]}")

        # React to events
        if event_type == "look":
            self._handle_look(event)
        elif event_type == "move":
            self._handle_move(event)
        elif event_type == "say":
            self._handle_say(event)
        elif event_type == "arrive":
            self._handle_arrive(event)
        elif event_type == "help":
            self._handle_help(event)
        elif event_type == "suggestions":
            self._handle_suggestions_list(event)
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
        logger.info(f"Location: {self.current_location} - {desc[:80]}")

        # Explore
        self._explore()

    def _handle_move(self, event):
        """Process movement results."""
        self.current_location = event.get("coordinates")
        self.available_exits = event.get("exits", [])
        self.rooms_explored += 1

        logger.info(f"Moved to: {self.current_location} (rooms explored: {self.rooms_explored})")

        # Maybe submit a suggestion
        if self.rooms_explored % self.suggest_interval == 0:
            self._maybe_suggest()

        # Maybe check existing suggestions and vote
        if self.rooms_explored % (self.suggest_interval * 2) == 0:
            self._check_and_vote()

        # Continue exploring after a delay
        time.sleep(2)
        self._explore()

    def _handle_say(self, event):
        """React to speech from other entities."""
        speaker = event.get("speaker", "someone")
        message = event.get("message", "")
        logger.info(f'{speaker} says: "{message}"')

        # Simple response: greet back
        if any(word in message.lower() for word in ["hello", "hi", "greet", "hey"]):
            self._send_command("say", message=f"Hello, {speaker}! I'm exploring and looking for ideas.")
        elif "suggest" in message.lower():
            self._send_command("say", message="Good idea! Use 'suggest <idea>' to share it.")

    def _handle_arrive(self, event):
        """React to someone arriving at our location."""
        actor = event.get("actor", "someone")
        logger.info(f"{actor} arrives.")
        self._send_command("say", message=f"Welcome, {actor}! Seen anything interesting?")

    def _handle_help(self, event):
        """Log available commands."""
        commands = event.get("commands", [])
        cmd_names = [c["name"] for c in commands]
        logger.info(f"Available commands: {', '.join(cmd_names)}")

    def _handle_suggestions_list(self, event):
        """Process suggestions list for voting."""
        self.known_suggestions = event.get("suggestions", [])
        logger.info(f"Received {len(self.known_suggestions)} suggestions")

        # Vote for a random suggestion we haven't voted for yet
        unvoted = [s for s in self.known_suggestions if s["uuid"] not in self.suggestions_made]
        if unvoted:
            pick = random.choice(unvoted)
            logger.info(f"Voting for: {pick['text'][:60]}")
            self._send_command("vote", suggestion_uuid=pick["uuid"])
            self.suggestions_made.add(pick["uuid"])

    def _explore(self):
        """Pick a direction and move."""
        if not self.available_exits:
            logger.info("No exits available, waiting...")
            time.sleep(5)
            self._send_command("look")
            return

        direction = random.choice(self.available_exits)
        logger.info(f"Exploring: moving {direction}")
        self._send_command("move", direction=direction)

    def _maybe_suggest(self):
        """Submit a suggestion based on exploration experience."""
        # Pick a template we haven't used
        unused = [t for t in SUGGESTION_TEMPLATES if t not in self.suggestions_made]
        if not unused:
            logger.info("Used all suggestion templates")
            return

        suggestion_text = random.choice(unused)
        self.suggestions_made.add(suggestion_text)
        logger.info(f"Submitting suggestion: {suggestion_text[:60]}")
        self._send_command("suggest", text=suggestion_text)

    def _check_and_vote(self):
        """Fetch existing suggestions and vote on one."""
        logger.info("Checking existing suggestions...")
        self._send_command("suggestions")


def main():
    """Run the AI agent."""
    parser = argparse.ArgumentParser(description="Serverless Game AI Agent")
    parser.add_argument("--api-key", required=True, help="API key for bot authentication")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
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
        help="UUID of entity to possess (auto-creates if not set)",
    )
    parser.add_argument(
        "--suggest-interval",
        type=int,
        default=10,
        help="Number of rooms explored between suggestions (default: 10)",
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

    # Get entity UUID from auth response or args
    entity_uuid = args.entity_uuid
    if not entity_uuid and "entity" in auth_result:
        entity_uuid = auth_result["entity"].get("uuid", "")

    # Determine WebSocket URL
    ws_url = args.ws_url
    if not ws_url:
        ws_url = args.api_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = ws_url.rstrip("/") + "/ws"

    logger.info(f"Connecting to {ws_url}")
    if entity_uuid:
        logger.info(f"Will possess entity {entity_uuid}")
    else:
        logger.info("Will auto-create entity on possess")

    # Connect and run
    bot = GameBot(
        jwt=jwt,
        entity_uuid=entity_uuid or "",
        ws_url=ws_url,
        suggest_interval=args.suggest_interval,
    )
    try:
        bot.connect()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
