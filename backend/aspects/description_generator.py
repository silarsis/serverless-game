"""LLM-powered room description generator.

Generates evocative room descriptions using an LLM API (Claude or OpenAI),
with template fallback for local dev or cost control.
"""

import hashlib
import json
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

# Biome hints based on z-level
Z_BIOMES = {
    -3: "deep cavern",
    -2: "underground passage",
    -1: "shallow cave",
    0: "surface terrain",
    1: "hilltop",
    2: "mountain path",
    3: "mountain peak",
}

# Simple templates for fallback when no LLM is available
FALLBACK_TEMPLATES = [
    "A {biome} stretches before you. The ground is {ground} and the air {air}.",
    "You find yourself in a {biome}. {feature} catches your eye.",
    "This {biome} is quiet and still. {atmosphere}.",
]

GROUND_TYPES = ["rocky", "soft", "muddy", "sandy", "grassy", "dusty", "mossy"]
AIR_TYPES = [
    "is cool and damp",
    "smells of earth",
    "carries a faint breeze",
    "is thick and warm",
    "is crisp and clean",
]
FEATURES = [
    "A strange rock formation",
    "An old tree stump",
    "A patch of wildflowers",
    "A shallow pool of water",
    "Faint scratch marks on a wall",
    "A pile of weathered stones",
]
ATMOSPHERES = [
    "Light filters in from above",
    "Shadows dance along the edges",
    "A faint hum fills the space",
    "The silence is almost tangible",
    "Distant echoes suggest open space beyond",
]


def _get_biome(z: int) -> str:
    """Get biome description from z-level."""
    if z in Z_BIOMES:
        return Z_BIOMES[z]
    if z > 3:
        return "high altitude"
    return "deep underground"


def _generate_fallback(coordinates: tuple, neighbors: List[str]) -> str:
    """Generate a deterministic template-based description."""
    x, y, z = coordinates
    seed = hashlib.md5(f"{x},{y},{z}".encode()).hexdigest()
    seed_int = int(seed[:8], 16)

    biome = _get_biome(z)
    template = FALLBACK_TEMPLATES[seed_int % len(FALLBACK_TEMPLATES)]
    ground = GROUND_TYPES[seed_int % len(GROUND_TYPES)]
    air = AIR_TYPES[(seed_int >> 4) % len(AIR_TYPES)]
    feature = FEATURES[(seed_int >> 8) % len(FEATURES)]
    atmosphere = ATMOSPHERES[(seed_int >> 12) % len(ATMOSPHERES)]

    return template.format(
        biome=biome,
        ground=ground,
        air=air,
        feature=feature,
        atmosphere=atmosphere,
    )


def _call_claude(prompt: str) -> Optional[str]:
    """Call Claude API for description generation."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import urllib.request

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        body = json.dumps(
            {
                "model": os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929"),
                "max_tokens": 150,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["content"][0]["text"].strip()
    except Exception as e:
        logger.warning(f"Claude API call failed: {e}")
        return None


def _call_openai(prompt: str) -> Optional[str]:
    """Call OpenAI API for description generation."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        import urllib.request

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        body = json.dumps(
            {
                "model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
                "max_tokens": 150,
                "messages": [
                    {
                        "role": "system",
                        "content": "You write brief, evocative MUD room descriptions. 2-3 sentences max.",
                    },
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"OpenAI API call failed: {e}")
        return None


def generate_description(
    coordinates: tuple,
    neighbor_descriptions: Optional[List[str]] = None,
) -> str:
    """Generate a room description for a land tile.

    Tries LLM first (Claude or OpenAI), falls back to templates.

    Args:
        coordinates: (x, y, z) tuple for the location.
        neighbor_descriptions: Descriptions of adjacent rooms for coherence.

    Returns:
        A 2-3 sentence room description string.
    """
    neighbors = neighbor_descriptions or []
    biome = _get_biome(coordinates[2])

    prompt = (
        f"Write a 2-3 sentence room description for a MUD game. "
        f"This location is at coordinates {coordinates} in a {biome} area."
    )
    if neighbors:
        neighbor_text = " | ".join(n for n in neighbors[:4] if n)
        prompt += f" Nearby rooms: {neighbor_text}. Keep thematic coherence."
    prompt += " Be evocative but brief. No coordinates in the description."

    # Try configured LLM provider
    provider = os.environ.get("LLM_PROVIDER", "").lower()
    result = None

    if provider == "claude" or provider == "anthropic":
        result = _call_claude(prompt)
    elif provider == "openai":
        result = _call_openai(prompt)
    else:
        # Try Claude first, then OpenAI
        result = _call_claude(prompt)
        if not result:
            result = _call_openai(prompt)

    if result:
        return result

    logger.info(f"Using fallback description for {coordinates}")
    return _generate_fallback(coordinates, neighbors)
