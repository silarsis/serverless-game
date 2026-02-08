"""Perlin/simplex noise biome layer.

Produces deterministic biome data from (x, y, z) coordinates using layered
2D simplex noise.  No external dependencies -- the noise function is
self-contained (~80 lines, well-known public-domain algorithm).

Four noise layers at different scales produce elevation, moisture,
civilization, and weirdness values.  These are combined to classify a
biome name and select the appropriate generator.
"""

from __future__ import annotations

import math
from typing import Tuple

from .base import BiomeData

# ---------------------------------------------------------------------------
# Simplex noise (2D) -- public-domain reference implementation
# Based on Stefan Gustavson's Java implementation, ported to Python.
# ---------------------------------------------------------------------------

_GRAD3 = [
    (1, 1),
    (-1, 1),
    (1, -1),
    (-1, -1),
    (1, 0),
    (-1, 0),
    (0, 1),
    (0, -1),
]

# Permutation table (doubled to avoid wrapping)
_PERM = [
    151, 160, 137, 91, 90, 15, 131, 13, 201, 95, 96, 53, 194, 233, 7, 225,
    140, 36, 103, 30, 69, 142, 8, 99, 37, 240, 21, 10, 23, 190, 6, 148,
    247, 120, 234, 75, 0, 26, 197, 62, 94, 252, 219, 203, 117, 35, 11, 32,
    57, 177, 33, 88, 237, 149, 56, 87, 174, 20, 125, 136, 171, 168, 68, 175,
    74, 165, 71, 134, 139, 48, 27, 166, 77, 146, 158, 231, 83, 111, 229, 122,
    60, 211, 133, 230, 220, 105, 92, 41, 55, 46, 245, 40, 244, 102, 143, 54,
    65, 25, 63, 161, 1, 216, 80, 73, 209, 76, 132, 187, 208, 89, 18, 169,
    200, 196, 135, 130, 116, 188, 159, 86, 164, 100, 109, 198, 173, 186, 3, 64,
    52, 217, 226, 250, 124, 123, 5, 202, 38, 147, 118, 126, 255, 82, 85, 212,
    207, 206, 59, 227, 47, 16, 58, 17, 182, 189, 28, 42, 223, 183, 170, 213,
    119, 248, 152, 2, 44, 154, 163, 70, 221, 153, 101, 155, 167, 43, 172, 9,
    129, 22, 39, 253, 19, 98, 108, 110, 79, 113, 224, 232, 178, 185, 112, 104,
    218, 246, 97, 228, 251, 34, 242, 193, 238, 210, 144, 12, 191, 179, 162, 241,
    81, 51, 145, 235, 249, 14, 239, 107, 49, 192, 214, 31, 181, 199, 106, 157,
    184, 84, 204, 176, 115, 121, 50, 45, 127, 4, 150, 254, 138, 236, 205, 93,
    222, 114, 67, 29, 24, 72, 243, 141, 128, 195, 78, 66, 215, 61, 156, 180,
]  # fmt: skip
_PERM = _PERM * 2  # double to avoid modular indexing

_F2 = 0.5 * (math.sqrt(3.0) - 1.0)
_G2 = (3.0 - math.sqrt(3.0)) / 6.0


def _noise2d(x: float, y: float) -> float:
    """2D simplex noise, returns value in roughly -1..1."""
    s = (x + y) * _F2
    i = math.floor(x + s)
    j = math.floor(y + s)
    t = (i + j) * _G2
    x0 = x - (i - t)
    y0 = y - (j - t)

    if x0 > y0:
        i1, j1 = 1, 0
    else:
        i1, j1 = 0, 1

    x1 = x0 - i1 + _G2
    y1 = y0 - j1 + _G2
    x2 = x0 - 1.0 + 2.0 * _G2
    y2 = y0 - 1.0 + 2.0 * _G2

    ii = i & 255
    jj = j & 255

    n0 = n1 = n2 = 0.0

    t0 = 0.5 - x0 * x0 - y0 * y0
    if t0 >= 0:
        t0 *= t0
        gi = _PERM[ii + _PERM[jj]] % 8
        n0 = t0 * t0 * (_GRAD3[gi][0] * x0 + _GRAD3[gi][1] * y0)

    t1 = 0.5 - x1 * x1 - y1 * y1
    if t1 >= 0:
        t1 *= t1
        gi = _PERM[ii + i1 + _PERM[jj + j1]] % 8
        n1 = t1 * t1 * (_GRAD3[gi][0] * x1 + _GRAD3[gi][1] * y1)

    t2 = 0.5 - x2 * x2 - y2 * y2
    if t2 >= 0:
        t2 *= t2
        gi = _PERM[ii + 1 + _PERM[jj + 1]] % 8
        n2 = t2 * t2 * (_GRAD3[gi][0] * x2 + _GRAD3[gi][1] * y2)

    # Scale to roughly -1..1
    return 70.0 * (n0 + n1 + n2)


# ---------------------------------------------------------------------------
# Noise layer helpers
# ---------------------------------------------------------------------------

# Each layer uses a different frequency and offset so they're independent.
_LAYERS = {
    "elevation": {"scale": 0.03, "offset": 0.0},
    "moisture": {"scale": 0.05, "offset": 100.0},
    "civilization": {"scale": 0.02, "offset": 200.0},
    "weirdness": {"scale": 0.08, "offset": 300.0},
}


def _sample(layer: str, x: int, y: int) -> float:
    """Sample a noise layer at integer grid coordinates."""
    cfg = _LAYERS[layer]
    return _noise2d(
        x * cfg["scale"] + cfg["offset"],
        y * cfg["scale"] + cfg["offset"],
    )


# ---------------------------------------------------------------------------
# Biome classification
# ---------------------------------------------------------------------------

# Underground biomes (z < 0)
_UNDERGROUND_BIOMES = {
    -1: "shallow_cave",
    -2: "underground_passage",
    -3: "deep_cavern",
}


def _classify_surface(elev: float, moist: float, civ: float, weird: float) -> str:
    """Classify surface biome from noise values."""
    # High civilization overrides natural terrain
    if civ > 0.4:
        if civ > 0.7:
            return "road"
        if elev > 0.3:
            return "hilltop_ruins"
        return "settlement_outskirts"

    # Elevation dominates
    if elev > 0.6:
        return "mountain_peak"
    if elev > 0.35:
        if moist > 0.2:
            return "misty_highlands"
        return "rocky_hills"

    # Low elevation
    if elev < -0.5:
        if moist > 0.3:
            return "lake_shore"
        return "ravine"

    # Mid-elevation: moisture matters
    if moist > 0.5:
        if elev < 0.0:
            return "swamp"
        return "dense_forest"
    if moist > 0.15:
        return "forest"
    if moist > -0.2:
        if elev > 0.1:
            return "grassland"
        return "plains"

    # Dry
    if moist < -0.4:
        return "desert"
    return "scrubland"


def _apply_weirdness(biome: str, weird: float) -> str:
    """Optionally modify biome name with weirdness prefix."""
    if weird > 0.6:
        return "eldritch_" + biome
    if weird > 0.35:
        return "ancient_" + biome
    return biome


def _classify_underground(z: int, moist: float, weird: float) -> str:
    """Classify underground biomes."""
    if z in _UNDERGROUND_BIOMES:
        base = _UNDERGROUND_BIOMES[z]
    elif z < -3:
        base = "deep_underground"
    else:
        base = "shallow_cave"

    if moist > 0.4:
        base = "underground_river"
    if weird > 0.5:
        base = "crystal_cavern"

    return base


def _generator_for_biome(biome: str, z: int) -> str:
    """Decide which generator handles this biome."""
    if z < 0:
        return "dungeon"
    # Future: settlement generator for high-civ biomes
    return "overworld"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_biome(x: int, y: int, z: int) -> BiomeData:
    """Deterministic biome data from coordinates.

    Same input always produces same output.  The noise functions are
    pure math with no randomness.

    Args:
        x, y, z: Integer grid coordinates.

    Returns:
        BiomeData with noise values, biome name, and generator name.
    """
    elev = _sample("elevation", x, y)
    moist = _sample("moisture", x, y)
    civ = _sample("civilization", x, y)
    weird = _sample("weirdness", x, y)

    # Z-coordinate modifies elevation (higher z = higher elevation)
    elev = min(1.0, max(-1.0, elev + z * 0.3))

    if z < 0:
        biome = _classify_underground(z, moist, weird)
    else:
        biome = _classify_surface(elev, moist, civ, weird)
        biome = _apply_weirdness(biome, weird)

    generator = _generator_for_biome(biome, z)

    return BiomeData(
        elevation=elev,
        moisture=moist,
        civilization=civ,
        weirdness=weird,
        biome_name=biome,
        generator_name=generator,
    )


def get_biome_at(coords: Tuple[int, int, int]) -> BiomeData:
    """Return biome data for coordinate tuple."""
    return get_biome(*coords)
