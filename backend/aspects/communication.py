"""Communication aspect for say/whisper commands.

Handles broadcasting messages to entities at the same location
and sending private messages to specific entities.

Shared fields (name, location, contents) live on Entity, not on this aspect.
Access them via self.entity.*.
"""

import logging

from .decorators import player_command
from .handler import lambdaHandler
from .thing import Aspect, Entity

logger = logging.getLogger(__name__)


class Communication(Aspect):
    """Aspect handling speech and messaging between entities.

    Behavioral aspect — no persistent data needed. The aspect table
    record may be empty apart from the uuid key.
    """

    _tableName = "LOCATION_TABLE"  # Share table with Location for now

    @player_command
    def say(self, message: str) -> dict:
        """Broadcast a message to all entities at the same location.

        Args:
            message: The message to say.

        Returns:
            dict with say confirmation.
        """
        if not message:
            return {"type": "error", "message": "Say what?"}

        location_uuid = self.entity.location
        if not location_uuid:
            return {"type": "error", "message": "You are nowhere."}

        speaker_name = self.entity.name

        event = {
            "type": "say",
            "speaker": speaker_name,
            "speaker_uuid": self.entity.uuid,
            "message": message,
        }

        # Broadcast to all entities at this location (except self)
        self.entity.broadcast_to_location(location_uuid, event)

        return {
            "type": "say_confirm",
            "message": f'You say: "{message}"',
        }

    @player_command
    def whisper(self, target_uuid: str, message: str) -> dict:
        """Send a private message to a specific entity.

        Args:
            target_uuid: UUID of the entity to whisper to.
            message: The message to whisper.

        Returns:
            dict with whisper confirmation.
        """
        if not message:
            return {"type": "error", "message": "Whisper what?"}
        if not target_uuid:
            return {"type": "error", "message": "Whisper to whom?"}

        speaker_name = self.entity.name

        try:
            target = Entity(uuid=target_uuid)
            target.push_event(
                {
                    "type": "whisper",
                    "speaker": speaker_name,
                    "speaker_uuid": self.entity.uuid,
                    "message": message,
                }
            )
        except KeyError:
            return {"type": "error", "message": "That entity doesn't exist."}

        target_name = target.name
        return {
            "type": "whisper_confirm",
            "message": f'You whisper to {target_name}: "{message}"',
        }

    @player_command
    def emote(self, action: str) -> dict:
        """Perform an emote visible to all entities at the same location.

        Args:
            action: The emote action (e.g., "waves", "laughs").

        Returns:
            dict with emote confirmation.
        """
        if not action:
            return {"type": "error", "message": "Do what?"}

        location_uuid = self.entity.location
        if not location_uuid:
            return {"type": "error", "message": "You are nowhere."}

        actor_name = self.entity.name

        event = {
            "type": "emote",
            "actor": actor_name,
            "actor_uuid": self.entity.uuid,
            "action": action,
        }

        # Broadcast to all entities at this location (except self)
        self.entity.broadcast_to_location(location_uuid, event)

        return {
            "type": "emote_confirm",
            "message": f"{actor_name} {action}",
        }


handler = lambdaHandler(Entity)
