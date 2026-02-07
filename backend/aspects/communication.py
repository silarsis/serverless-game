"""Communication aspect for say/whisper commands.

Handles broadcasting messages to entities at the same location
and sending private messages to specific entities.
"""

import logging

from .decorators import player_command
from .handler import lambdaHandler
from .location import Location
from .thing import Thing

logger = logging.getLogger(__name__)


class Communication(Location):
    """Aspect handling speech and messaging between entities."""

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

        location_uuid = self.location
        if not location_uuid:
            return {"type": "error", "message": "You are nowhere."}

        # Get all entities at this location
        entities_at_location = self.contents
        speaker_name = self.data.get("name", self.uuid[:8])

        event = {
            "type": "say",
            "speaker": speaker_name,
            "speaker_uuid": self.uuid,
            "message": message,
        }

        # Push to all connected entities at this location (except self)
        for entity_uuid in entities_at_location:
            if entity_uuid == self.uuid:
                continue
            try:
                entity = Thing(uuid=entity_uuid)
                entity.push_event(event)
            except (KeyError, Exception) as e:
                logger.debug(f"Could not push say event to {entity_uuid}: {e}")

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

        speaker_name = self.data.get("name", self.uuid[:8])

        try:
            target = Thing(uuid=target_uuid)
            target.push_event(
                {
                    "type": "whisper",
                    "speaker": speaker_name,
                    "speaker_uuid": self.uuid,
                    "message": message,
                }
            )
        except KeyError:
            return {"type": "error", "message": "That entity doesn't exist."}

        target_name = target.data.get("name", target_uuid[:8])
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

        location_uuid = self.location
        if not location_uuid:
            return {"type": "error", "message": "You are nowhere."}

        entities_at_location = self.contents
        actor_name = self.data.get("name", self.uuid[:8])

        event = {
            "type": "emote",
            "actor": actor_name,
            "actor_uuid": self.uuid,
            "action": action,
        }

        for entity_uuid in entities_at_location:
            if entity_uuid == self.uuid:
                continue
            try:
                entity = Thing(uuid=entity_uuid)
                entity.push_event(event)
            except (KeyError, Exception) as e:
                logger.debug(f"Could not push emote event to {entity_uuid}: {e}")

        return {
            "type": "emote_confirm",
            "message": f"{actor_name} {action}",
        }


handler = lambdaHandler(Communication)
