"""Core data types and protocol for the pluggable world generation system.

Generators produce RoomBlueprints that describe everything about a room
(exits, terrain, description hints) without knowing about UUIDs or DynamoDB.
The caller (Land._generate_room) materializes the blueprint into real entities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple


@dataclass
class BiomeData:
    """Noise-derived biome information for a coordinate."""

    elevation: float  # -1..1: ocean → lowland → hills → mountains
    moisture: float  # -1..1: desert → dry → wet → swamp
    civilization: float  # -1..1: wilderness → ruins → settled → roads
    weirdness: float  # -1..1: mundane → unusual → magical → eldritch
    biome_name: str  # resolved name: "dense_forest", "rocky_hills", etc.
    generator_name: str  # which generator handles this: "overworld", "dungeon"


@dataclass
class GenerationContext:
    """What we know when generating a room."""

    came_from: Optional[Tuple[int, int, int]] = None
    came_from_description: Optional[str] = None
    came_from_biome: Optional[str] = None
    neighbors: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # direction → {coords, description, biome, uuid} for existing neighbors
    biome_data: Optional[BiomeData] = None


@dataclass
class RoomBlueprint:
    """Everything needed to materialize a room.

    Exits map direction → destination coordinates (NOT UUIDs).
    The caller resolves coordinates to UUIDs via Land.by_coordinates().
    """

    exits: Dict[str, Tuple[int, int, int]]
    # direction → destination coords
    biome: str
    terrain: List[Dict[str, Any]]
    # entities to create: [{"name": "an old oak", "type": "tree", ...}]
    description_hint: str
    # short context for LLM prompt
    description: str = ""
    # filled in by describe.py after generation
    scale: str = "room"
    # "cramped" | "room" | "wide" | "vast"
    tags: List[str] = field(default_factory=list)
    # ambient terrain tags: ["wooded", "dark", "damp"]
    distant_features: List[str] = field(default_factory=list)
    # ["Mountains rise to the north"]
    landmark: Optional[str] = None
    # landmark name if within influence zone


class WorldGenerator(Protocol):
    """Protocol for pluggable world generators.

    Implement this to create a new generator (dungeon, settlement, etc.).
    Register it in worldgen/__init__.py.
    """

    def generate(
        self,
        coords: Tuple[int, int, int],
        context: GenerationContext,
    ) -> RoomBlueprint:
        """Generate a room blueprint for the given coordinates."""
        ...
