"""NPC behavior system.

NPCs are entities with autonomous behavior that runs on tick().
They use the same @callable event system as everything else - they're
just entities that act on their own schedule.
"""

import logging
import random
from typing import Optional

from .handler import lambdaHandler
from .land import Land
from .location import Location
from .thing import Thing, callable

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


class NPC(Location):
    """An entity with autonomous behavior.

    NPCs have a behavior field that determines how they act on each tick:
    - wander: move randomly through existing exits
    - patrol: follow a set route of locations
    - guard: stay put, greet visitors
    - merchant: stay put, offer trades

    NPCs react to player presence (arrival events) by speaking.
    """

    @callable
    def create(self, behavior: str = "wander", name: str = "a stranger", **kwargs):
        """Create a new NPC with behavior and personality.

        Args:
            behavior: One of 'wander', 'patrol', 'guard', 'merchant', 'hermit'.
            name: Display name for the NPC.
            **kwargs: Additional NPC properties (e.g., patrol_route, inventory).
        """
        super().create()
        self.data["behavior"] = behavior
        self.data["name"] = name
        self.data["is_npc"] = True
        self.data.update(kwargs)
        self._save()
        self.schedule_next_tick()

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

        self.schedule_next_tick()

    def _wander(self):
        """Move randomly through available exits."""
        loc_uuid = self.location
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

        self._move_to(self.location, dest_uuid)
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
        npc_name = self.data.get("name", "someone")

        # Notify departure
        self._broadcast_to_location(
            from_uuid,
            {
                "type": "depart",
                "actor": npc_name,
                "actor_uuid": self.uuid,
                "direction": direction or "away",
            },
        )

        # Update location
        self.location = to_uuid

        # Notify arrival
        self._broadcast_to_location(
            to_uuid,
            {
                "type": "arrive",
                "actor": npc_name,
                "actor_uuid": self.uuid,
            },
        )

    def _check_for_players(self):
        """Check if any connected players are at this location and greet them."""
        loc_uuid = self.location
        if not loc_uuid:
            return

        try:
            loc = Location(uuid=loc_uuid)
        except KeyError:
            return

        for entity_uuid in loc.contents:
            if entity_uuid == self.uuid:
                continue
            try:
                entity = Thing(uuid=entity_uuid)
                # Only greet connected entities (players)
                if entity.connection_id:
                    self._greet_player(entity)
            except (KeyError, Exception):
                continue

    def _greet_player(self, player: Thing):
        """Say hello to a player."""
        # Don't spam - track who we've greeted recently
        greeted = self.data.get("greeted", [])
        if player.uuid in greeted:
            return

        behavior = self.data.get("behavior", "wanderer")
        greetings = GREETINGS.get(behavior, GREETINGS["wanderer"])
        greeting = random.choice(greetings)
        npc_name = self.data.get("name", "someone")

        player.push_event(
            {
                "type": "say",
                "speaker": npc_name,
                "speaker_uuid": self.uuid,
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
            player = Thing(uuid=player_uuid)
            if player.connection_id:
                self._greet_player(player)
        except KeyError:
            pass
        return {"type": "npc_reaction", "npc_uuid": self.uuid}

    def _broadcast_to_location(self, location_uuid: str, event: dict) -> None:
        """Push event to all connected entities at a location, except self."""
        if not location_uuid:
            return
        try:
            loc = Location(uuid=location_uuid)
            for entity_uuid in loc.contents:
                if entity_uuid == self.uuid:
                    continue
                try:
                    entity = Thing(uuid=entity_uuid)
                    entity.push_event(event)
                except (KeyError, Exception):
                    pass
        except (KeyError, Exception):
            pass


handler = lambdaHandler(NPC)
