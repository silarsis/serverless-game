"""Enhanced room description generation.

Wraps the existing LLM callers from description_generator.py with richer
context from the worldgen system (biome, terrain, landmarks, distant features).
Falls back to a biome-aware template system when no LLM key is available.
"""

from __future__ import annotations

import hashlib
import logging
from typing import List

from .base import GenerationContext, RoomBlueprint

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rich fallback templates per biome
# ---------------------------------------------------------------------------

_TEMPLATES = {
    "plains": [
        "Flat {scale} grassland stretches in every direction. {terrain_ref} The wind carries the scent of dry earth.",
        "An open expanse of {scale} plain under a wide sky. {terrain_ref} {distant_ref}",
        "Tall grass ripples like water across the {scale} plain. {terrain_ref}",
    ],
    "grassland": [
        "A gentle {scale} landscape of green grass and low wildflowers. {terrain_ref}",
        "Rolling {scale} grassland with a breeze that smells of summer. {terrain_ref} {distant_ref}",
    ],
    "forest": [
        "Dappled light falls through the canopy of this {scale} woodland. {terrain_ref}",
        "Trees press in on all sides, their trunks like pillars in a {scale} hall. {terrain_ref}",
        "A {scale} stretch of forest, alive with birdsong and rustling leaves. {terrain_ref} {distant_ref}",
    ],
    "dense_forest": [
        "The trees grow thick here, blocking most of the light. {terrain_ref} Every step crunches through old leaves.",
        "A {scale} tangle of branches and undergrowth. The air is still and humid. {terrain_ref}",
        "Ancient trees loom overhead, their roots making the ground treacherous. {terrain_ref}",
    ],
    "swamp": [
        "The ground squelches underfoot in this {scale} marsh. {terrain_ref} The air is thick with insects.",
        "Murky water seeps between tussocks of rank grass. {terrain_ref} Something bubbles nearby.",
        "A {scale} expanse of boggy ground, shrouded in mist. {terrain_ref}",
    ],
    "rocky_hills": [
        "Rough {scale} hillside dotted with loose stones and scrub. {terrain_ref} {distant_ref}",
        "The ground rises steeply here, rocky and exposed. {terrain_ref}",
    ],
    "mountain_peak": [
        "Wind howls across this {scale} exposed summit. {terrain_ref} {distant_ref}",
        "A {scale} peak of bare rock and thin air. {terrain_ref} The view is breathtaking.",
    ],
    "desert": [
        "Sand and heat shimmer across this {scale} wasteland. {terrain_ref}",
        "A {scale} expanse of baked earth and silence. {terrain_ref} {distant_ref}",
    ],
    "scrubland": [
        "Dry {scale} scrubland with sparse, hardy bushes. {terrain_ref}",
        "Dusty ground stretches through this {scale} scrub. {terrain_ref} {distant_ref}",
    ],
    "lake_shore": [
        "Water laps gently at the shore of this {scale} lake edge. {terrain_ref}",
        "A {scale} stretch of shoreline where land meets still water. {terrain_ref} {distant_ref}",
    ],
    "road": [
        "A well-worn {scale} road, packed hard by years of travel. {terrain_ref} {distant_ref}",
        "The {scale} road stretches ahead, dusty ruts marking countless journeys. {terrain_ref}",
    ],
    "settlement_outskirts": [
        "Signs of habitation mark this {scale} clearing. {terrain_ref} {distant_ref}",
        "A {scale} area at the edge of settlement. {terrain_ref} Sounds of life carry on the breeze.",
    ],
    "hilltop_ruins": [
        "Crumbling walls and broken arches mark this {scale} ruin. {terrain_ref}",
        "Old stones lie scattered across this {scale} hilltop. {terrain_ref} {distant_ref}",
    ],
    "ravine": [
        "A {scale} cleft in the earth, walls rising steeply on both sides. {terrain_ref}",
        "The {scale} ravine echoes with dripping water and your own footsteps. {terrain_ref}",
    ],
    "misty_highlands": [
        "Mist drifts across this {scale} highland moor. {terrain_ref} {distant_ref}",
        "A {scale} stretch of heather-covered high ground, visibility poor in the fog. {terrain_ref}",
    ],
    # Underground
    "shallow_cave": [
        "A {scale} cave entrance, daylight still visible behind you. {terrain_ref}",
        "Rough stone walls close in around this {scale} cavern. {terrain_ref}",
    ],
    "underground_passage": [
        "A {scale} tunnel stretches into darkness. {terrain_ref} The air is cool and still.",
        "Hewn rock walls line this {scale} underground passage. {terrain_ref}",
    ],
    "deep_cavern": [
        "A {scale} cavern swallows your light. {terrain_ref} Water drips somewhere unseen.",
        "The ceiling vanishes into blackness above this {scale} underground space. {terrain_ref}",
    ],
    "underground_river": [
        "Dark water rushes through this {scale} underground channel. {terrain_ref}",
        "The sound of flowing water echoes through the {scale} cavern. {terrain_ref}",
    ],
    "crystal_cavern": [
        "Crystalline formations catch and scatter light through this {scale} chamber. {terrain_ref}",
        "Glittering crystals stud the walls of this {scale} cavern. {terrain_ref}",
    ],
    "deep_underground": [
        "The {scale} darkness is absolute here. {terrain_ref} The silence presses in.",
        "A {scale} void of stone and shadow. {terrain_ref}",
    ],
}

_DEFAULT_TEMPLATES = [
    "A {scale} stretch of land. {terrain_ref}",
    "An unremarkable {scale} area. {terrain_ref} {distant_ref}",
]


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------


def _terrain_ref(blueprint: RoomBlueprint) -> str:
    """Create a natural-language reference to a terrain entity."""
    if not blueprint.terrain:
        return ""
    # Mention the first terrain entity
    first = blueprint.terrain[0]
    name = first.get("name", "something")
    return f"You notice {name} nearby."


def _distant_ref(blueprint: RoomBlueprint) -> str:
    """Pick one distant feature to mention."""
    if not blueprint.distant_features:
        return ""
    return blueprint.distant_features[0]


def _scale_adjective(scale: str) -> str:
    """Convert scale to a natural adjective."""
    return {
        "cramped": "narrow",
        "room": "modest",
        "wide": "broad",
        "vast": "vast",
    }.get(scale, "")


def _generate_fallback(blueprint: RoomBlueprint) -> str:
    """Generate a template-based description from blueprint data."""
    # Strip weirdness prefix for template lookup
    biome = blueprint.biome
    for prefix in ("eldritch_", "ancient_"):
        if biome.startswith(prefix):
            biome = biome[len(prefix) :]
            break

    templates = _TEMPLATES.get(biome, _DEFAULT_TEMPLATES)

    # Deterministic selection
    hint_hash = hashlib.md5(blueprint.description_hint.encode()).hexdigest()
    seed = int(hint_hash[:8], 16)
    template = templates[seed % len(templates)]

    text = template.format(
        scale=_scale_adjective(blueprint.scale),
        terrain_ref=_terrain_ref(blueprint),
        distant_ref=_distant_ref(blueprint),
    )

    # Add landmark modifier if present
    if blueprint.landmark:
        text += f" You are {blueprint.landmark}."

    # Add weirdness flavor
    if blueprint.biome.startswith("eldritch_"):
        text += " The air shimmers with an unsettling, unnatural energy."
    elif blueprint.biome.startswith("ancient_"):
        text += " There is a palpable sense of age to this place."

    return text.strip()


# ---------------------------------------------------------------------------
# LLM-powered description
# ---------------------------------------------------------------------------


def _build_llm_prompt(
    blueprint: RoomBlueprint,
    context: GenerationContext,
) -> str:
    """Build a rich prompt for LLM description generation."""
    parts = [
        "You are describing a room in a text MUD game. Write 2-3 vivid sentences.",
        "",
        f"BIOME: {blueprint.biome.replace('_', ' ')} ({blueprint.scale} scale)",
    ]

    if blueprint.terrain:
        names = ", ".join(t["name"] for t in blueprint.terrain)
        parts.append(f"TERRAIN PRESENT: {names}")

    parts.append(f"EXITS AVAILABLE: {', '.join(blueprint.exits.keys())}")

    if context.came_from_description:
        # Keep it short
        came_short = context.came_from_description[:100]
        parts.append(f"CAME FROM: {came_short}")

    # Neighbor descriptions for coherence
    neighbor_descs = []
    for d, info in context.neighbors.items():
        desc = info.get("description", "")
        if desc:
            neighbor_descs.append(f"{d}: {desc[:80]}")
    if neighbor_descs:
        parts.append(f"NEARBY AREAS: {' | '.join(neighbor_descs[:3])}")

    if blueprint.landmark:
        parts.append(f"LANDMARK NEARBY: {blueprint.landmark}")

    if blueprint.distant_features:
        parts.append(f"DISTANT VIEWS: {'; '.join(blueprint.distant_features[:2])}")

    if blueprint.tags:
        parts.append(f"ATMOSPHERE: {', '.join(blueprint.tags[:4])}")

    parts.extend(
        [
            "",
            "Rules:",
            "- Describe what the player sees, hears, smells",
            "- Reference the terrain entities naturally (don't just list them)",
            "- If scale is 'vast', convey openness; if 'cramped', claustrophobia",
            "- Mention distant features as things seen/heard from here",
            "- Never mention coordinates or game mechanics",
            "- 2-3 sentences maximum",
        ]
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_room_description(
    blueprint: RoomBlueprint,
    context: GenerationContext,
) -> str:
    """Generate a room description using LLM or fallback templates.

    Args:
        blueprint: The generated room blueprint with biome, terrain, etc.
        context: Generation context with neighbor info.

    Returns:
        A 2-3 sentence room description.
    """
    # Try LLM first (reuse existing callers from description_generator)
    try:
        from ..description_generator import _call_claude, _call_openai

        prompt = _build_llm_prompt(blueprint, context)

        import os

        provider = os.environ.get("LLM_PROVIDER", "").lower()
        result = None

        if provider in ("claude", "anthropic"):
            result = _call_claude(prompt)
        elif provider == "openai":
            result = _call_openai(prompt)
        else:
            result = _call_claude(prompt)
            if not result:
                result = _call_openai(prompt)

        if result:
            # Add landmark modifier if LLM didn't mention it
            if blueprint.landmark and blueprint.landmark not in result:
                result = result.rstrip(".") + f", {blueprint.landmark}."
            return result

    except ImportError:
        logger.debug("description_generator not available, using fallback")
    except Exception as e:
        logger.warning(f"LLM description failed: {e}")

    return _generate_fallback(blueprint)
