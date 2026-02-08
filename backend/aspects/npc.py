"""NPC behavior system.

NPCs are entities with autonomous behavior that runs on tick().
They use the same @callable event system as everything else - they're
just entities that act on their own schedule.

Shared fields (name, location, contents, connection_id) live on Entity,
not on this aspect. Access them via self.entity.*.
"""

import logging
import random
from typing import Optional

from .handler import lambdaHandler
from .land import Land
from .thing import Aspect, Entity, callable

logger = logging.getLogger(__name__)

# Simple dialogue pools for NPC archetypes
GREETINGS = {
    "wanderer": [
        "A fellow traveler! Well met.",
        "These roads are long, but the company is welcome.",
        "Greetings, stranger. Have you seen anything unusual?",
    ],
    "guard": [
        "Halt! State your business.",
        "Move along, citizen.",
        "All is quiet on my watch.",
    ],
    "merchant": [
        "Wares for sale! Come, have a look.",
        "I have just what you need, friend.",
        "Finest goods this side of the mountains.",
    ],
    "hermit": [
        "You found me. Not many do.",
        "The silence here is precious. Don't ruin it.",
        "What brings you to this forgotten place?",
    ],
}


class NPC(Aspect):
    """An entity with autonomous behavior.

    NPCs have a behavior field that determines how they act on each tick:
    - wander: move randomly through existing exits
    - patrol: follow a set route of locations
    - guard: stay put, greet visitors
    - merchant: stay put, offer trades

    NPCs react to player presence (arrival events) by speaking.

    Stores: behavior, patrol_route, patrol_index, greeted, is_npc.
    """

    _tableName = "LOCATION_TABLE"  # Shared aspect table — keyed by entity UUID, no conflicts

    @callable
    def create(self, behavior: str = "wander", name: str = "a stranger", **kwargs):
        """Create a new NPC with behavior and personality.

        Args:
            behavior: One of 'wander', 'patrol', 'guard', 'merchant', 'hermit'.
            name: Display name for the NPC.
            **kwargs: Additional NPC properties (e.g., patrol_route, inventory).
        """
        self.data["behavior"] = behavior
        self.data["is_npc"] = True
        self.data.update(kwargs)
        self._save()
        # Set entity name
        if self.entity:
            self.entity.name = name
            self.entity._save()
            self.entity.schedule_next_tick()

    @callable
    def tick(self):
        """Execute behavior-specific action."""
        behavior = self.data.get("behavior", "wander")

        if behavior == "wander":
            self._wander()
        elif behavior == "patrol":
            self._patrol()
        elif behavior == "guard":
            self._guard()
        elif behavior == "merchant":
            self._merchant()
        elif behavior == "hermit":
            self._hermit()

        if self.entity:
            self.entity.schedule_next_tick()

    def _wander(self):
        """Move randomly through available exits."""
        loc_uuid = self.entity.location if self.entity else None
        if not loc_uuid:
            return

        try:
            loc = Land(uuid=loc_uuid)
        except KeyError:
            return

        exits = loc.exits
        if not exits:
            return

        # 50% chance to move, 50% chance to stay
        if random.random() < 0.5:
            direction = random.choice(list(exits.keys()))
            dest_uuid = exits[direction]
            self._move_to(loc_uuid, dest_uuid, direction)

    def _patrol(self):
        """Follow a preset patrol route."""
        route = self.data.get("patrol_route", [])
        if not route:
            self._wander()
            return

        current_idx = self.data.get("patrol_index", 0)
        next_idx = (current_idx + 1) % len(route)
        dest_uuid = route[next_idx]

        loc_uuid = self.entity.location if self.entity else None
        self._move_to(loc_uuid, dest_uuid)
        self.data["patrol_index"] = next_idx
        self._save()

    def _guard(self):
        """Stay in place, observe surroundings."""
        self._check_for_players()

    def _merchant(self):
        """Stay in place, available for trade."""
        self._check_for_players()

    def _hermit(self):
        """Stay in place, occasionally mutter."""
        self._check_for_players()

    def _move_to(self, from_uuid: str, to_uuid: str, direction: Optional[str] = None):
        """Move NPC from one location to another, notifying both locations."""
        npc_name = self.entity.name if self.entity else "someone"

        # Notify departure
        if self.entity:
            self.entity.broadcast_to_location(
                from_uuid,
                {
                    "type": "depart",
                    "actor": npc_name,
                    "actor_uuid": self.entity.uuid,
                    "direction": direction or "away",
                },
            )

        # Update location (writes to entity table, sends arrival notification)
        if self.entity:
            self.entity.location = to_uuid

    def _check_for_players(self):
        """Check if any connected players are at this location and greet them."""
        loc_uuid = self.entity.location if self.entity else None
        if not loc_uuid:
            return

        try:
            loc_entity = Entity(uuid=loc_uuid)
        except KeyError:
            return

        for entity_uuid in loc_entity.contents:
            if self.entity and entity_uuid == self.entity.uuid:
                continue
            try:
                other_entity = Entity(uuid=entity_uuid)
                # Only greet connected entities (players)
                if other_entity.connection_id:
                    self._greet_player(other_entity)
            except (KeyError, Exception):
                continue

    def _greet_player(self, player: Entity):
        """Say hello to a player."""
        # Don't spam - track who we've greeted recently
        greeted = self.data.get("greeted", [])
        if player.uuid in greeted:
            return

        behavior = self.data.get("behavior", "wanderer")
        greetings = GREETINGS.get(behavior, GREETINGS["wanderer"])
        greeting = random.choice(greetings)
        npc_name = self.entity.name if self.entity else "someone"

        player.push_event(
            {
                "type": "say",
                "speaker": npc_name,
                "speaker_uuid": self.entity.uuid if self.entity else "",
                "message": greeting,
            }
        )

        # Remember we greeted this player (keep list bounded)
        greeted.append(player.uuid)
        self.data["greeted"] = greeted[-10:]
        self._save()

    @callable
    def on_player_arrive(self, player_uuid: str, player_name: str = "") -> dict:
        """React when a player arrives at the NPC's location.

        Args:
            player_uuid: UUID of the arriving player.
            player_name: Name of the arriving player.

        Returns:
            dict confirming reaction.
        """
        try:
            player = Entity(uuid=player_uuid)
            if player.connection_id:
                self._greet_player(player)
        except KeyError:
            pass
        npc_uuid = self.entity.uuid if self.entity else self.uuid
        return {"type": "npc_reaction", "npc_uuid": npc_uuid}


handler = lambdaHandler(Entity)
