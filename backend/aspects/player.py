"""Player entity management for game users.

Handles player entity creation/retrieval based on Firebase UIDs.
Uses UUID5 for stable identifiers and assigns default locations.
"""

import uuid


def get_or_create_player_entity(firebase_uid):
    """Get or create a Player entity for this user.

    Args:
        firebase_uid: The Firebase user ID.

    Returns:
        dict with uuid, aspect, and location.
    """
    # Generate stable UUID from firebase_uid
    entity_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "player-" + firebase_uid))
    aspect = "aspects/player"
    # Demo: location always (0,0,0)
    return {
        "uuid": entity_uuid,
        "aspect": aspect,
        "location": {"x": 0, "y": 0, "z": 0},
    }
