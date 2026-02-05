"""Decorators for aspect security and command routing.

This module provides decorators for controlling access to aspect methods
via WebSocket commands and internal calls.
"""

import logging
from functools import wraps
from typing import Callable

logger = logging.getLogger(__name__)


def player_command(func: Callable) -> Callable:
    """Mark a method as callable via WebSocket from a player.

    Only methods decorated with @player_command can be invoked through the
    WebSocket interface. This is distinct from @callable which allows
    internal aspect-to-aspect calls via SNS.

    The decorator:
    1. Marks the method with _is_player_command = True
    2. Validates the caller has permission to possess this entity
    3. Ensures the entity is a player-owned entity (not system entity)

    Example:
        class Land(Thing):
            @player_command
            def move(self, direction: str) -> dict:
                '''Move in a direction - callable by connected player.'''
                return {"status": "moved", "direction": direction}

            @callable
            def internal_update(self, data: dict) -> dict:
                '''Internal update - NOT callable via WebSocket.'''
                return {"status": "updated"}

    Security:
        - JWT from WebSocket connect headers is used to identify the player
        - Player can only invoke commands on their own player entity
        - System entities (is_system=True) cannot be possessed or commanded
    """

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # Check if this is a system entity (admin-only, no player access)
        if getattr(self, "is_system", False):
            logger.warning(f"Player attempted to command system entity {self.uuid}")
            return {"error": "System entities cannot be player-controlled"}

        # Validate the connection ownership (set by receive_command)
        caller_connection = kwargs.pop("_caller_connection_id", None)
        expected_connection = getattr(self, "connection_id", None)

        if caller_connection and expected_connection:
            if caller_connection != expected_connection:
                logger.warning(
                    f"Connection mismatch: caller={caller_connection}, "
                    f"expected={expected_connection}"
                )
                return {"error": "Not authorized to command this entity"}

        # Call the actual method
        return func(self, *args, **kwargs)

    # Mark the method as a player-accessible command
    wrapper._is_player_command = True  # type: ignore[attr-defined]
    wrapper._is_callable = True  # type: ignore[attr-defined]  # Also callable internally

    return wrapper


def admin_only(func: Callable) -> Callable:
    """Mark a method as admin-only.

    These methods can only be called by system entities or admin-authenticated
    connections. Used for administrative commands.

    Example:
        class WorldManager(Thing):
            @admin_only
            def shutdown(self, reason: str) -> dict:
                # Shutdown the world - admin only.
                return {"status": "shutting_down"}
    """

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # Check for admin flag in kwargs or entity
        is_admin = kwargs.pop("_is_admin", False) or getattr(self, "is_admin", False)

        if not is_admin:
            logger.warning(f"Non-admin attempted admin command on {self.uuid}")
            return {"error": "Admin access required"}

        return func(self, *args, **kwargs)

    wrapper._is_admin_only = True  # type: ignore[attr-defined]
    wrapper._is_callable = True  # type: ignore[attr-defined]

    return wrapper


def system_entity(func: Callable) -> Callable:
    """Mark a class as a system entity.

    System entities:
    - Cannot be possessed by players
    - Can only be commanded by other system entities or admin connections
    - Are typically infrastructure (world managers, tick schedulers, etc.)

    Example:
        @system_entity
        class WorldTicker(Thing):
            def tick(self) -> dict:
                return {"status": "ticked"}
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        instance = func(*args, **kwargs)
        instance.is_system = True
        return instance

    wrapper._is_system_entity = True  # type: ignore[attr-defined]
    return wrapper


# Internal callable decorator (for reference/completeness)
def callable(func: Callable) -> Callable:
    """Mark a method as callable via SNS.

    This is the existing @callable decorator pattern. Methods decorated
    with @callable can be invoked via SNS Call() but NOT directly via
    WebSocket unless also decorated with @player_command.

    For WebSocket-exposed commands, use @player_command instead which
    includes both capabilities with proper authorization.

    Example:
        @callable
        def internal_sync(self, data: dict) -> dict:
            # Can be called via SNS from other aspects
            # Cannot be called directly from WebSocket
            pass
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    wrapper._is_callable = True  # type: ignore[attr-defined]
    return wrapper
