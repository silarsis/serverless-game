"""Overworld generator for surface biomes.

Handles exit selection (variable, not always 4), terrain entity placement,
scale classification, and distant feature detection.  All decisions are
seeded from coordinates for determinism.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple

from .base import BiomeData, GenerationContext, RoomBlueprint
from .biome import get_biome

# ---------------------------------------------------------------------------
# Exit probability profiles per biome
# ---------------------------------------------------------------------------

# base_exits: how many cardinal exits this biome typically has (2-4)
# up_down_chance: probability of adding an up or down exit
EXIT_PROFILES: Dict[str, Dict[str, Any]] = {
    # Open terrain -- many paths
    "plains": {"base_exits": 4, "up_down_chance": 0.0},
    "grassland": {"base_exits": 4, "up_down_chance": 0.0},
    "road": {"base_exits": 2, "up_down_chance": 0.0},
    "settlement_outskirts": {"base_exits": 3, "up_down_chance": 0.0},
    # Forests -- paths wind
    "forest": {"base_exits": 3, "up_down_chance": 0.0},
    "dense_forest": {"base_exits": 2, "up_down_chance": 0.0},
    # Elevated -- restricted, vertical possible
    "rocky_hills": {"base_exits": 3, "up_down_chance": 0.3},
    "misty_highlands": {"base_exits": 3, "up_down_chance": 0.2},
    "mountain_peak": {"base_exits": 2, "up_down_chance": 0.5},
    "hilltop_ruins": {"base_exits": 3, "up_down_chance": 0.3},
    # Wet terrain
    "swamp": {"base_exits": 3, "up_down_chance": 0.1},
    "lake_shore": {"base_exits": 3, "up_down_chance": 0.0},
    # Dry terrain
    "desert": {"base_exits": 3, "up_down_chance": 0.0},
    "scrubland": {"base_exits": 3, "up_down_chance": 0.0},
    # Low terrain
    "ravine": {"base_exits": 2, "up_down_chance": 0.4},
}

# Default profile for biomes not listed (including weirdness-prefixed ones)
_DEFAULT_PROFILE = {"base_exits": 3, "up_down_chance": 0.1}

# ---------------------------------------------------------------------------
# Terrain catalogs per biome
# ---------------------------------------------------------------------------

TERRAIN_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "plains": [
        {
            "name": "a patch of tall grass",
            "type": "vegetation",
            "description": "Waist-high grass sways in the breeze.",
            "weight": 1,
            "tags": ["grass", "vegetation"],
        },
        {
            "name": "a weathered boulder",
            "type": "rock",
            "description": "A lone boulder, half-buried in the earth.",
            "weight": 500,
            "tags": ["rock", "climbable"],
        },
        {
            "name": "a wildflower meadow",
            "type": "vegetation",
            "description": "Tiny flowers dot the ground in patches of colour.",
            "weight": 1,
            "tags": ["flowers", "vegetation"],
        },
    ],
    "grassland": [
        {
            "name": "a low stone wall",
            "type": "structure",
            "description": "An old stone wall, crumbling at the edges.",
            "weight": 999,
            "tags": ["stone", "wall", "shelter"],
        },
        {
            "name": "a gentle hill",
            "type": "terrain",
            "description": "A slight rise gives a broader view of the surroundings.",
            "weight": 999,
            "tags": ["hill", "climbable", "vantage"],
        },
    ],
    "forest": [
        {
            "name": "a tall oak tree",
            "type": "tree",
            "description": "A gnarled oak, its branches spreading wide overhead.",
            "weight": 999,
            "tags": ["tree", "climbable", "wood", "shelter"],
        },
        {
            "name": "a mossy log",
            "type": "wood",
            "description": "A fallen tree, soft with moss and home to small creatures.",
            "weight": 200,
            "tags": ["wood", "shelter", "climbable"],
        },
        {
            "name": "a cluster of ferns",
            "type": "vegetation",
            "description": "Lush ferns crowd the forest floor.",
            "weight": 1,
            "tags": ["vegetation", "hiding"],
        },
        {
            "name": "a birch stand",
            "type": "tree",
            "description": "Several slender birch trees, their white bark peeling.",
            "weight": 999,
            "tags": ["tree", "wood"],
        },
    ],
    "dense_forest": [
        {
            "name": "a massive ancient tree",
            "type": "tree",
            "description": "An enormous tree, its trunk wider than three people.",
            "weight": 999,
            "tags": ["tree", "ancient", "wood", "climbable"],
        },
        {
            "name": "a tangle of roots",
            "type": "terrain",
            "description": "Thick roots weave across the ground like frozen serpents.",
            "weight": 999,
            "tags": ["roots", "dangerous"],
        },
        {
            "name": "a dark thicket",
            "type": "vegetation",
            "description": "Dense thorny bushes block easy passage.",
            "weight": 999,
            "tags": ["bush", "blocking", "thorns"],
        },
    ],
    "swamp": [
        {
            "name": "a murky pool",
            "type": "water",
            "description": "Dark water, still and reflective. Something ripples beneath.",
            "weight": 999,
            "tags": ["water", "deep", "dangerous"],
        },
        {
            "name": "a dead tree",
            "type": "tree",
            "description": "A bleached, leafless tree stands like a skeleton.",
            "weight": 999,
            "tags": ["tree", "dead", "wood"],
        },
        {
            "name": "a patch of reeds",
            "type": "vegetation",
            "description": "Tall reeds whisper as the air stirs.",
            "weight": 1,
            "tags": ["reeds", "vegetation", "hiding"],
        },
    ],
    "rocky_hills": [
        {
            "name": "a rocky outcrop",
            "type": "rock",
            "description": "Jagged rock thrusts upward from the hillside.",
            "weight": 999,
            "tags": ["rock", "climbable", "vantage"],
        },
        {
            "name": "a scree slope",
            "type": "terrain",
            "description": "Loose stones clatter underfoot on this unstable slope.",
            "weight": 999,
            "tags": ["rock", "dangerous", "unstable"],
        },
    ],
    "mountain_peak": [
        {
            "name": "a wind-carved pinnacle",
            "type": "rock",
            "description": "A needle of stone shaped by centuries of wind.",
            "weight": 999,
            "tags": ["rock", "landmark"],
        },
        {
            "name": "a snow patch",
            "type": "terrain",
            "description": "A stubborn patch of snow clings to the shaded rock.",
            "weight": 999,
            "tags": ["snow", "cold", "water"],
        },
    ],
    "desert": [
        {
            "name": "a sand dune",
            "type": "terrain",
            "description": "A rippled dune of fine golden sand.",
            "weight": 999,
            "tags": ["sand", "shifting"],
        },
        {
            "name": "a sun-bleached skull",
            "type": "bone",
            "description": "The skull of some large creature, half-buried in sand.",
            "weight": 5,
            "tags": ["bone", "mysterious"],
        },
        {
            "name": "a thorny cactus",
            "type": "vegetation",
            "description": "A squat, spiny cactus. It might hold water.",
            "weight": 30,
            "tags": ["vegetation", "thorns", "water"],
        },
    ],
    "scrubland": [
        {
            "name": "a dry bush",
            "type": "vegetation",
            "description": "A hardy bush with dusty grey-green leaves.",
            "weight": 10,
            "tags": ["bush", "vegetation", "wood"],
        },
        {
            "name": "a cracked stone slab",
            "type": "rock",
            "description": "A flat stone, split by heat and time.",
            "weight": 300,
            "tags": ["rock", "flat"],
        },
    ],
    "lake_shore": [
        {
            "name": "a stretch of pebbled beach",
            "type": "terrain",
            "description": "Smooth pebbles line the water's edge.",
            "weight": 999,
            "tags": ["pebbles", "beach", "water"],
        },
        {
            "name": "a small wooden jetty",
            "type": "structure",
            "description": "A rickety jetty extends a few metres over the water.",
            "weight": 999,
            "tags": ["wood", "structure", "water"],
        },
    ],
    "road": [
        {
            "name": "a worn milestone",
            "type": "structure",
            "description": "A stone marker, its carved numbers barely legible.",
            "weight": 200,
            "tags": ["stone", "landmark", "structure"],
        },
        {
            "name": "a cart rut",
            "type": "terrain",
            "description": "Deep ruts from countless passing wheels.",
            "weight": 999,
            "tags": ["road", "civilization"],
        },
    ],
    "settlement_outskirts": [
        {
            "name": "a wooden fence post",
            "type": "structure",
            "description": "A leaning fence post, its wire long rusted away.",
            "weight": 50,
            "tags": ["wood", "structure", "civilization"],
        },
        {
            "name": "a small vegetable patch",
            "type": "vegetation",
            "description": "Someone has been tending rows of scraggly vegetables.",
            "weight": 999,
            "tags": ["vegetation", "food", "civilization"],
        },
    ],
    "hilltop_ruins": [
        {
            "name": "a crumbling wall segment",
            "type": "structure",
            "description": "Part of an old wall, overgrown with ivy.",
            "weight": 999,
            "tags": ["stone", "structure", "ruins", "ancient"],
        },
        {
            "name": "a broken column",
            "type": "structure",
            "description": "A column base, its upper half long fallen.",
            "weight": 999,
            "tags": ["stone", "structure", "ruins"],
        },
    ],
    "ravine": [
        {
            "name": "a narrow ledge",
            "type": "terrain",
            "description": "A precarious ledge along the ravine wall.",
            "weight": 999,
            "tags": ["rock", "dangerous", "narrow"],
        },
        {
            "name": "a trickle of water",
            "type": "water",
            "description": "A thin stream runs along the ravine floor.",
            "weight": 999,
            "tags": ["water", "stream"],
        },
    ],
    "misty_highlands": [
        {
            "name": "a heather-covered slope",
            "type": "vegetation",
            "description": "Purple heather carpets the ground in low mounds.",
            "weight": 999,
            "tags": ["vegetation", "flowers"],
        },
        {
            "name": "a cairn of stacked stones",
            "type": "structure",
            "description": "Carefully balanced stones mark this spot.",
            "weight": 300,
            "tags": ["stone", "landmark", "structure"],
        },
    ],
}

# ---------------------------------------------------------------------------
# Scale mapping
# ---------------------------------------------------------------------------

BIOME_SCALES: Dict[str, str] = {
    "plains": "vast",
    "grassland": "wide",
    "desert": "vast",
    "forest": "room",
    "dense_forest": "cramped",
    "swamp": "room",
    "rocky_hills": "wide",
    "mountain_peak": "room",
    "road": "wide",
    "settlement_outskirts": "wide",
    "lake_shore": "wide",
    "ravine": "cramped",
    "hilltop_ruins": "room",
    "misty_highlands": "wide",
    "scrubland": "wide",
}

# ---------------------------------------------------------------------------
# Ambient tags per biome (stored on Land, not as entities)
# ---------------------------------------------------------------------------

BIOME_TAGS: Dict[str, List[str]] = {
    "plains": ["open", "windy", "grass"],
    "grassland": ["open", "gentle", "grass"],
    "forest": ["wooded", "shaded", "birdsong"],
    "dense_forest": ["dark", "overgrown", "damp", "quiet"],
    "swamp": ["wet", "murky", "insects", "stench"],
    "rocky_hills": ["exposed", "rocky", "windy"],
    "mountain_peak": ["cold", "windy", "exposed", "high"],
    "desert": ["hot", "dry", "sand", "glare"],
    "scrubland": ["dry", "dusty", "sparse"],
    "lake_shore": ["water", "breeze", "pebbles"],
    "road": ["dusty", "flat", "worn"],
    "settlement_outskirts": ["civilization", "fences", "smoke"],
    "hilltop_ruins": ["ancient", "crumbling", "overgrown"],
    "ravine": ["narrow", "echoing", "damp", "shadowed"],
    "misty_highlands": ["misty", "heather", "windy", "damp"],
}

# ---------------------------------------------------------------------------
# Distant feature templates
# ---------------------------------------------------------------------------

_DISTANT_TEMPLATES: Dict[str, List[str]] = {
    "mountain_peak": [
        "Mountains rise to the {dir}, their peaks lost in cloud.",
        "Jagged peaks loom on the {dir}ern horizon.",
    ],
    "rocky_hills": [
        "Rolling hills stretch away to the {dir}.",
    ],
    "forest": [
        "A dark tree line marks the {dir}ern horizon.",
        "Forest canopy spreads to the {dir}.",
    ],
    "dense_forest": [
        "Dense woodland crowds the view to the {dir}.",
    ],
    "lake_shore": [
        "Sunlight glints off water to the {dir}.",
    ],
    "swamp": [
        "Mist hangs low over marshland to the {dir}.",
    ],
    "desert": [
        "Sand stretches endlessly to the {dir}.",
    ],
    "settlement_outskirts": [
        "Smoke curls from somewhere to the {dir}.",
        "A few rooftops are visible to the {dir}.",
    ],
    "road": [
        "A road stretches into the distance to the {dir}.",
    ],
    "hilltop_ruins": [
        "Ruined walls stand on a hill to the {dir}.",
    ],
}


# ---------------------------------------------------------------------------
# Deterministic seeded RNG from coordinates
# ---------------------------------------------------------------------------


def _coord_seed(x: int, y: int, z: int) -> int:
    """Deterministic seed from coordinates."""
    h = hashlib.md5(f"{x},{y},{z}".encode()).hexdigest()
    return int(h[:8], 16)


def _seeded_choice(seed: int, items: list, index: int = 0):
    """Pick an item deterministically from a list."""
    if not items:
        return None
    return items[(seed + index * 7919) % len(items)]


def _seeded_sample(seed: int, items: list, k: int) -> list:
    """Pick k unique items deterministically from a list."""
    if k >= len(items):
        return list(items)
    result = []
    remaining = list(items)
    for i in range(k):
        idx = (seed + i * 6311) % len(remaining)
        result.append(remaining.pop(idx))
    return result


# ---------------------------------------------------------------------------
# The generator
# ---------------------------------------------------------------------------

_CARDINALS = ["north", "south", "east", "west"]
_COORD_DELTAS = {
    "north": (0, 1, 0),
    "south": (0, -1, 0),
    "east": (1, 0, 0),
    "west": (-1, 0, 0),
    "up": (0, 0, 1),
    "down": (0, 0, -1),
}
_OPPOSITE = {
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
    "up": "down",
    "down": "up",
}


def _dest_coords(origin: Tuple[int, int, int], direction: str) -> Tuple[int, int, int]:
    """Compute destination coordinates from origin + direction."""
    dx, dy, dz = _COORD_DELTAS[direction]
    return (origin[0] + dx, origin[1] + dy, origin[2] + dz)


class OverworldGenerator:
    """Generator for all surface biomes."""

    def generate(
        self,
        coords: Tuple[int, int, int],
        context: GenerationContext,
    ) -> RoomBlueprint:
        """Generate a room blueprint for surface coordinates."""
        biome = context.biome_data
        base_biome = biome.biome_name
        # Strip weirdness prefix for catalog lookups
        lookup_biome = base_biome
        for prefix in ("eldritch_", "ancient_"):
            if lookup_biome.startswith(prefix):
                lookup_biome = lookup_biome[len(prefix) :]
                break

        seed = _coord_seed(*coords)

        # --- Exits ---
        exits = self._generate_exits(coords, lookup_biome, seed, context)

        # --- Terrain entities ---
        terrain = self._generate_terrain(lookup_biome, seed)

        # --- Scale ---
        scale = BIOME_SCALES.get(lookup_biome, "room")

        # --- Tags ---
        tags = list(BIOME_TAGS.get(lookup_biome, ["unknown"]))
        # Add weirdness tags
        if biome.weirdness > 0.35:
            tags.append("ancient")
        if biome.weirdness > 0.6:
            tags.append("eldritch")

        # --- Distant features ---
        distant = self._generate_distant_features(coords, exits, lookup_biome)

        # --- Description hint ---
        hint_parts = [lookup_biome.replace("_", " ")]
        if context.came_from_biome:
            hint_parts.append(f"arrived from {context.came_from_biome}")
        if tags:
            hint_parts.append(f"feels {', '.join(tags[:3])}")
        description_hint = "; ".join(hint_parts)

        return RoomBlueprint(
            exits=exits,
            biome=base_biome,
            terrain=terrain,
            description_hint=description_hint,
            scale=scale,
            tags=tags,
            distant_features=distant,
        )

    def _generate_exits(
        self,
        coords: Tuple[int, int, int],
        biome: str,
        seed: int,
        context: GenerationContext,
    ) -> Dict[str, Tuple[int, int, int]]:
        """Decide which exits this room has."""
        profile = EXIT_PROFILES.get(biome, _DEFAULT_PROFILE)
        base_count = profile["base_exits"]

        # Start with all cardinals, we'll prune
        candidates = list(_CARDINALS)

        # Forced exits: if a neighbor already has an exit pointing here,
        # we MUST include the reciprocal direction.
        forced: set = set()
        for direction, info in context.neighbors.items():
            # info has "has_exit_to_us" key if the neighbor points back at us
            if info.get("has_exit_to_us"):
                forced.add(direction)

        # Also force the direction we came from (so player can go back)
        if context.came_from:
            for d in _CARDINALS:
                dest = _dest_coords(coords, d)
                if dest == context.came_from:
                    forced.add(d)
                    break

        # Select exits: forced ones always included, then fill up to base_count
        selected = set(forced)
        remaining = [d for d in candidates if d not in selected]

        # Deterministically pick from remaining to fill quota
        if len(selected) < base_count and remaining:
            # Shuffle remaining deterministically
            remaining.sort(key=lambda d: (seed + hash(d)) % 1000)
            for d in remaining:
                if len(selected) >= base_count:
                    break
                selected.add(d)

        # Check for up/down
        up_down_chance = profile["up_down_chance"]
        if up_down_chance > 0:
            # Use seed to decide deterministically
            if ((seed >> 16) % 100) / 100.0 < up_down_chance:
                if context.biome_data and context.biome_data.elevation > 0.3:
                    selected.add("up")
                else:
                    selected.add("down")

        # Convert to coordinate map
        exits = {}
        for d in selected:
            exits[d] = _dest_coords(coords, d)

        return exits

    def _generate_terrain(
        self,
        biome: str,
        seed: int,
    ) -> List[Dict[str, Any]]:
        """Select terrain entities for this room."""
        catalog = TERRAIN_CATALOG.get(biome, [])
        if not catalog:
            return []

        # 1-3 terrain entities per room
        count = 1 + (seed % 3)
        count = min(count, len(catalog))

        return _seeded_sample(seed, catalog, count)

    def _generate_distant_features(
        self,
        coords: Tuple[int, int, int],
        exits: Dict[str, Tuple[int, int, int]],
        current_biome: str,
    ) -> List[str]:
        """Check what's visible in the distance via noise lookups."""
        features = []

        for direction in exits:
            if direction in ("up", "down"):
                continue

            # Look 3-5 tiles ahead in this direction
            dx, dy, dz = _COORD_DELTAS[direction]
            for distance in (3, 5):
                far_x = coords[0] + dx * distance
                far_y = coords[1] + dy * distance
                far_z = coords[2]
                far_biome = get_biome(far_x, far_y, far_z)

                # Strip weirdness prefix for template lookup
                far_name = far_biome.biome_name
                for prefix in ("eldritch_", "ancient_"):
                    if far_name.startswith(prefix):
                        far_name = far_name[len(prefix) :]
                        break

                # Only report if different from current biome
                if far_name != current_biome and far_name in _DISTANT_TEMPLATES:
                    templates = _DISTANT_TEMPLATES[far_name]
                    seed = _coord_seed(far_x, far_y, far_z)
                    template = _seeded_choice(seed, templates)
                    if template:
                        feature = template.format(dir=direction)
                        if feature not in features:
                            features.append(feature)
                    break  # one feature per direction

            if len(features) >= 3:
                break

        return features
