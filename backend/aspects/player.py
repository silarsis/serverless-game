"""Player entity management for game users."""

import uuid


def get_or_create_player_entity(firebase_uid):
    """Get or create a Player entity for this user.

    Args:
        firebase_uid: The Firebase user ID.

    Returns:
        dict with uuid, aspect, and location.
    """
    # For simplicity: generate UUID based on firebase_uid (stable)
    entity_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "player-" + firebase_uid))
    aspect = "aspects/player"
    # Optionally: create in entities table or whatever other infra needed.
    # For demo: location always (0,0,0)
    return {
        "uuid": entity_uuid,
        "aspect": aspect,
        "location": {"x": 0, "y": 0, "z": 0},
    }
