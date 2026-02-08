"""Tests for the pluggable world generation system.

Covers noise determinism, biome classification, exit generation,
terrain placement, landmark discovery, description generation,
and full pipeline integration.
"""

import os
import unittest

os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")


class TestSimplexNoise(unittest.TestCase):
    """Test the simplex noise implementation for correctness and determinism."""

    def test_determinism(self):
        """Same inputs always produce same outputs."""
        from aspects.worldgen.biome import _noise2d

        val1 = _noise2d(1.5, 2.7)
        val2 = _noise2d(1.5, 2.7)
        self.assertEqual(val1, val2)

    def test_range(self):
        """Noise values should be roughly in -1..1 range."""
        from aspects.worldgen.biome import _noise2d

        for x in range(-20, 20):
            for y in range(-20, 20):
                val = _noise2d(x * 0.1, y * 0.1)
                self.assertGreaterEqual(val, -1.5, f"Too low at ({x}, {y})")
                self.assertLessEqual(val, 1.5, f"Too high at ({x}, {y})")

    def test_different_inputs_vary(self):
        """Different coordinates should (generally) produce different values."""
        from aspects.worldgen.biome import _noise2d

        values = set()
        for x in range(10):
            for y in range(10):
                values.add(round(_noise2d(x * 0.5, y * 0.5), 6))
        # Should have many distinct values
        self.assertGreater(len(values), 20)

    def test_zero_at_origin(self):
        """Noise at (0, 0) should return 0 (lattice point)."""
        from aspects.worldgen.biome import _noise2d

        val = _noise2d(0.0, 0.0)
        self.assertAlmostEqual(val, 0.0, places=10)


class TestBiomeClassification(unittest.TestCase):
    """Test biome determination from coordinates."""

    def test_get_biome_determinism(self):
        """Same coordinates always produce same biome."""
        from aspects.worldgen.biome import get_biome

        b1 = get_biome(10, 20, 0)
        b2 = get_biome(10, 20, 0)
        self.assertEqual(b1.biome_name, b2.biome_name)
        self.assertEqual(b1.elevation, b2.elevation)
        self.assertEqual(b1.moisture, b2.moisture)

    def test_biome_data_fields(self):
        """Verify biome data has all expected fields."""
        from aspects.worldgen.biome import get_biome

        b = get_biome(0, 0, 0)
        self.assertIsInstance(b.elevation, float)
        self.assertIsInstance(b.moisture, float)
        self.assertIsInstance(b.civilization, float)
        self.assertIsInstance(b.weirdness, float)
        self.assertIsInstance(b.biome_name, str)
        self.assertIsInstance(b.generator_name, str)
        self.assertIn(b.generator_name, ("overworld", "dungeon"))

    def test_underground_uses_dungeon_generator(self):
        """Negative z should route to dungeon generator."""
        from aspects.worldgen.biome import get_biome

        b = get_biome(5, 5, -1)
        self.assertEqual(b.generator_name, "dungeon")

    def test_surface_uses_overworld_generator(self):
        """z=0 should route to overworld generator."""
        from aspects.worldgen.biome import get_biome

        b = get_biome(5, 5, 0)
        self.assertEqual(b.generator_name, "overworld")

    def test_biome_variety(self):
        """Scanning a large area should produce multiple biome types."""
        from aspects.worldgen.biome import get_biome

        biomes = set()
        for x in range(-50, 50, 5):
            for y in range(-50, 50, 5):
                b = get_biome(x, y, 0)
                biomes.add(b.biome_name)
        # Should have at least a few different biomes
        self.assertGreater(len(biomes), 3, f"Only found biomes: {biomes}")

    def test_z_affects_elevation(self):
        """Higher z should increase effective elevation."""
        from aspects.worldgen.biome import get_biome

        low = get_biome(10, 10, 0)
        high = get_biome(10, 10, 2)
        self.assertGreater(high.elevation, low.elevation)

    def test_classify_surface(self):
        """Test direct biome classification with known values."""
        from aspects.worldgen.biome import _classify_surface

        # High elevation → mountain
        self.assertEqual(_classify_surface(0.7, 0.0, 0.0, 0.0), "mountain_peak")

        # High civilization → road
        self.assertEqual(_classify_surface(0.0, 0.0, 0.8, 0.0), "road")

        # High moisture, low elevation → swamp
        self.assertEqual(_classify_surface(-0.1, 0.6, 0.0, 0.0), "swamp")

        # Very low elevation, low moisture → ravine
        self.assertEqual(_classify_surface(-0.6, 0.0, 0.0, 0.0), "ravine")

    def test_weirdness_prefix(self):
        """High weirdness should add prefix to biome name."""
        from aspects.worldgen.biome import _apply_weirdness

        self.assertEqual(_apply_weirdness("forest", 0.7), "eldritch_forest")
        self.assertEqual(_apply_weirdness("forest", 0.4), "ancient_forest")
        self.assertEqual(_apply_weirdness("forest", 0.1), "forest")


class TestOverworldGenerator(unittest.TestCase):
    """Test the overworld generator."""

    def test_generate_returns_blueprint(self):
        """Generator should return a RoomBlueprint."""
        from aspects.worldgen.base import GenerationContext, RoomBlueprint
        from aspects.worldgen.biome import get_biome
        from aspects.worldgen.overworld import OverworldGenerator

        gen = OverworldGenerator()
        biome = get_biome(10, 10, 0)
        context = GenerationContext(biome_data=biome)
        blueprint = gen.generate((10, 10, 0), context)

        self.assertIsInstance(blueprint, RoomBlueprint)
        self.assertIsInstance(blueprint.exits, dict)
        self.assertGreater(len(blueprint.exits), 0)
        self.assertIsInstance(blueprint.biome, str)
        self.assertIsInstance(blueprint.terrain, list)
        self.assertIn(blueprint.scale, ("cramped", "room", "wide", "vast"))

    def test_exits_are_coordinate_tuples(self):
        """Exit values should be (x, y, z) coordinate tuples."""
        from aspects.worldgen.base import GenerationContext
        from aspects.worldgen.biome import get_biome
        from aspects.worldgen.overworld import OverworldGenerator

        gen = OverworldGenerator()
        biome = get_biome(0, 0, 0)
        context = GenerationContext(biome_data=biome)
        blueprint = gen.generate((0, 0, 0), context)

        for direction, coords in blueprint.exits.items():
            self.assertIsInstance(coords, tuple, f"Exit {direction} is not a tuple")
            self.assertEqual(len(coords), 3, f"Exit {direction} is not 3-tuple")

    def test_came_from_always_included(self):
        """The direction back to came_from should always be in exits."""
        from aspects.worldgen.base import GenerationContext
        from aspects.worldgen.biome import get_biome
        from aspects.worldgen.overworld import OverworldGenerator

        gen = OverworldGenerator()
        biome = get_biome(5, 6, 0)
        # Player came from (5, 5, 0), which is south of (5, 6, 0)
        context = GenerationContext(
            came_from=(5, 5, 0),
            biome_data=biome,
        )
        blueprint = gen.generate((5, 6, 0), context)

        self.assertIn("south", blueprint.exits, "Exit back to came_from must be included")

    def test_forced_reciprocal_exits(self):
        """If a neighbor has an exit pointing to us, we must include reciprocal."""
        from aspects.worldgen.base import GenerationContext
        from aspects.worldgen.biome import get_biome
        from aspects.worldgen.overworld import OverworldGenerator

        gen = OverworldGenerator()
        biome = get_biome(5, 5, 0)
        context = GenerationContext(
            biome_data=biome,
            neighbors={
                "east": {
                    "coords": (6, 5, 0),
                    "has_exit_to_us": True,
                    "description": "",
                    "biome": "forest",
                }
            },
        )
        blueprint = gen.generate((5, 5, 0), context)
        self.assertIn("east", blueprint.exits, "Reciprocal exit for neighbor must be included")

    def test_exit_count_varies_by_biome(self):
        """Different biomes should produce different typical exit counts."""
        from aspects.worldgen.base import GenerationContext
        from aspects.worldgen.biome import BiomeData
        from aspects.worldgen.overworld import OverworldGenerator

        gen = OverworldGenerator()

        # Plains: 4 exits
        plains_biome = BiomeData(0.0, -0.1, 0.0, 0.0, "plains", "overworld")
        plains_ctx = GenerationContext(biome_data=plains_biome)
        plains_bp = gen.generate((100, 100, 0), plains_ctx)

        # Dense forest: 2 exits
        forest_biome = BiomeData(0.1, 0.6, 0.0, 0.0, "dense_forest", "overworld")
        forest_ctx = GenerationContext(biome_data=forest_biome)
        forest_bp = gen.generate((100, 100, 0), forest_ctx)

        # Plains should have more exits than dense forest on average
        self.assertEqual(len(plains_bp.exits), 4)
        self.assertLessEqual(len(forest_bp.exits), 3)

    def test_terrain_entities_have_required_fields(self):
        """Terrain entities should have name, type, and other fields."""
        from aspects.worldgen.base import GenerationContext
        from aspects.worldgen.biome import get_biome
        from aspects.worldgen.overworld import OverworldGenerator

        gen = OverworldGenerator()
        biome = get_biome(10, 10, 0)
        context = GenerationContext(biome_data=biome)
        blueprint = gen.generate((10, 10, 0), context)

        for terrain in blueprint.terrain:
            self.assertIn("name", terrain)
            self.assertIn("type", terrain)
            self.assertIn("weight", terrain)
            self.assertIn("tags", terrain)

    def test_determinism(self):
        """Same coordinates + context should always produce same blueprint."""
        from aspects.worldgen.base import GenerationContext
        from aspects.worldgen.biome import get_biome
        from aspects.worldgen.overworld import OverworldGenerator

        gen = OverworldGenerator()
        biome = get_biome(42, 42, 0)
        context = GenerationContext(biome_data=biome)

        bp1 = gen.generate((42, 42, 0), context)
        bp2 = gen.generate((42, 42, 0), context)

        self.assertEqual(bp1.exits, bp2.exits)
        self.assertEqual(bp1.biome, bp2.biome)
        self.assertEqual(bp1.scale, bp2.scale)
        self.assertEqual(len(bp1.terrain), len(bp2.terrain))
        self.assertEqual(bp1.tags, bp2.tags)


class TestDungeonGenerator(unittest.TestCase):
    """Test the dungeon/cave generator."""

    def test_generate_underground(self):
        """Dungeon generator should produce valid blueprints."""
        from aspects.worldgen.base import GenerationContext
        from aspects.worldgen.biome import get_biome
        from aspects.worldgen.dungeon import DungeonGenerator

        gen = DungeonGenerator()
        biome = get_biome(5, 5, -1)
        context = GenerationContext(biome_data=biome)
        blueprint = gen.generate((5, 5, -1), context)

        self.assertIsInstance(blueprint.exits, dict)
        self.assertGreater(len(blueprint.exits), 0)
        self.assertIn("underground", blueprint.tags)
        self.assertIn(blueprint.scale, ("cramped", "room"))

    def test_cave_exit_count(self):
        """Caves should typically have 2-3 exits (plus forced ones)."""
        from aspects.worldgen.base import GenerationContext
        from aspects.worldgen.biome import get_biome
        from aspects.worldgen.dungeon import DungeonGenerator

        gen = DungeonGenerator()
        biome = get_biome(5, 5, -1)
        context = GenerationContext(biome_data=biome)
        blueprint = gen.generate((5, 5, -1), context)

        # Should be 2-5 exits (2-3 base + possible up/down)
        self.assertGreaterEqual(len(blueprint.exits), 2)
        self.assertLessEqual(len(blueprint.exits), 6)

    def test_came_from_forced(self):
        """Cave should include exit back to where player came from."""
        from aspects.worldgen.base import GenerationContext
        from aspects.worldgen.biome import get_biome
        from aspects.worldgen.dungeon import DungeonGenerator

        gen = DungeonGenerator()
        biome = get_biome(5, 6, -1)
        context = GenerationContext(
            came_from=(5, 5, -1),
            biome_data=biome,
        )
        blueprint = gen.generate((5, 6, -1), context)

        self.assertIn("south", blueprint.exits)


class TestLandmarks(unittest.TestCase):
    """Test the landmark discovery system."""

    def test_landmark_determinism(self):
        """Same coordinates should always produce same landmark result."""
        from aspects.worldgen.landmarks import check_landmark

        result1 = check_landmark(0, 0, 0)
        result2 = check_landmark(0, 0, 0)
        if result1 is None:
            self.assertIsNone(result2)
        else:
            self.assertEqual(result1.name, result2.name)
            self.assertEqual(result1.center, result2.center)

    def test_landmark_fields(self):
        """Landmarks should have all required fields."""
        from aspects.worldgen.landmarks import _landmark_at

        # Find a landmark by brute force (check many coords)
        landmark = None
        for x in range(500):
            lm = _landmark_at(x, 0, 0)
            if lm is not None:
                landmark = lm
                break

        self.assertIsNotNone(landmark, "Should find at least one landmark in 500 tiles")
        self.assertIsInstance(landmark.name, str)
        self.assertIsInstance(landmark.landmark_type, str)
        self.assertIsInstance(landmark.center, tuple)
        self.assertIsInstance(landmark.radius, int)
        self.assertGreater(landmark.radius, 0)
        self.assertIsInstance(landmark.description_modifier, str)
        self.assertIsInstance(landmark.terrain_additions, list)

    def test_landmark_rarity(self):
        """Landmarks should be rare — roughly 1 in LANDMARK_RARITY."""
        from aspects.worldgen.landmarks import LANDMARK_RARITY, _is_landmark_center

        count = 0
        total = 1000
        for x in range(total):
            if _is_landmark_center(x, 0, 0):
                count += 1

        # Should be roughly total / LANDMARK_RARITY
        expected = total / LANDMARK_RARITY
        # Allow wide margin for randomness
        self.assertGreater(count, 0, "Should find at least one landmark")
        self.assertLess(count, expected * 5, f"Too many landmarks: {count}, expected ~{expected}")

    def test_nearby_landmark_discovery(self):
        """check_landmark should find nearby landmark centers."""
        from aspects.worldgen.landmarks import _landmark_at, check_landmark

        # Find a landmark center
        center = None
        for x in range(500):
            lm = _landmark_at(x, 0, 0)
            if lm is not None:
                center = (x, 0, 0)
                break

        self.assertIsNotNone(center, "Need a landmark center for this test")
        lm = _landmark_at(*center)

        # Check a tile within the landmark's radius
        if lm.radius >= 1:
            nearby = check_landmark(center[0] + 1, center[1], center[2])
            self.assertIsNotNone(nearby, "Should find landmark from nearby tile")
            self.assertEqual(nearby.name, lm.name)


class TestDescriptionGeneration(unittest.TestCase):
    """Test the description generation system."""

    def test_fallback_generates_description(self):
        """Fallback template system should produce non-empty descriptions."""
        from aspects.worldgen.base import RoomBlueprint
        from aspects.worldgen.describe import _generate_fallback

        blueprint = RoomBlueprint(
            exits={"north": (0, 1, 0)},
            biome="forest",
            terrain=[{"name": "a tall oak tree", "type": "tree"}],
            description_hint="forest; feels wooded",
            scale="room",
            tags=["wooded"],
        )
        desc = _generate_fallback(blueprint)
        self.assertIsInstance(desc, str)
        self.assertGreater(len(desc), 10)

    def test_fallback_includes_terrain_reference(self):
        """Fallback description should mention terrain."""
        from aspects.worldgen.base import RoomBlueprint
        from aspects.worldgen.describe import _generate_fallback

        blueprint = RoomBlueprint(
            exits={"north": (0, 1, 0)},
            biome="plains",
            terrain=[{"name": "a weathered boulder", "type": "rock"}],
            description_hint="plains",
            scale="vast",
            tags=["open"],
        )
        desc = _generate_fallback(blueprint)
        self.assertIn("weathered boulder", desc)

    def test_fallback_with_landmark(self):
        """Fallback should include landmark modifier."""
        from aspects.worldgen.base import RoomBlueprint
        from aspects.worldgen.describe import _generate_fallback

        blueprint = RoomBlueprint(
            exits={"north": (0, 1, 0)},
            biome="forest",
            terrain=[],
            description_hint="forest near ruins",
            scale="room",
            tags=["wooded"],
            landmark="near the ruins of an old watchtower",
        )
        desc = _generate_fallback(blueprint)
        self.assertIn("watchtower", desc)

    def test_fallback_with_weirdness(self):
        """Eldritch/ancient biome prefix should add flavor text."""
        from aspects.worldgen.base import RoomBlueprint
        from aspects.worldgen.describe import _generate_fallback

        blueprint = RoomBlueprint(
            exits={"north": (0, 1, 0)},
            biome="eldritch_forest",
            terrain=[],
            description_hint="eldritch forest",
            scale="room",
            tags=["wooded", "eldritch"],
        )
        desc = _generate_fallback(blueprint)
        self.assertIn("unsettling", desc.lower())

    def test_llm_prompt_construction(self):
        """LLM prompt should include all relevant context."""
        from aspects.worldgen.base import GenerationContext, RoomBlueprint
        from aspects.worldgen.describe import _build_llm_prompt

        blueprint = RoomBlueprint(
            exits={"north": (0, 1, 0), "east": (1, 0, 0)},
            biome="dense_forest",
            terrain=[{"name": "an ancient tree", "type": "tree"}],
            description_hint="dense forest",
            scale="cramped",
            tags=["dark", "overgrown"],
            distant_features=["Mountains rise to the north"],
            landmark="near a crystal spring",
        )
        context = GenerationContext(
            came_from_description="A sunny clearing.",
        )
        prompt = _build_llm_prompt(blueprint, context)

        self.assertIn("dense forest", prompt)
        self.assertIn("ancient tree", prompt)
        self.assertIn("north", prompt)
        self.assertIn("cramped", prompt)
        self.assertIn("crystal spring", prompt)
        self.assertIn("Mountains", prompt)
        self.assertIn("sunny clearing", prompt)


class TestFullPipeline(unittest.TestCase):
    """Test the full worldgen pipeline (generate_room)."""

    def test_generate_room(self):
        """Full pipeline should produce a complete RoomBlueprint."""
        from aspects.worldgen import generate_room
        from aspects.worldgen.base import GenerationContext, RoomBlueprint

        context = GenerationContext()
        blueprint = generate_room((10, 10, 0), context)

        self.assertIsInstance(blueprint, RoomBlueprint)
        self.assertIsInstance(blueprint.exits, dict)
        self.assertGreater(len(blueprint.exits), 0)
        self.assertIsInstance(blueprint.biome, str)
        self.assertIsInstance(blueprint.description, str)
        self.assertGreater(len(blueprint.description), 0)
        self.assertIn(blueprint.scale, ("cramped", "room", "wide", "vast"))

    def test_generate_room_underground(self):
        """Full pipeline should work for underground coordinates."""
        from aspects.worldgen import generate_room
        from aspects.worldgen.base import GenerationContext

        context = GenerationContext()
        blueprint = generate_room((5, 5, -1), context)

        self.assertIsInstance(blueprint.exits, dict)
        self.assertGreater(len(blueprint.exits), 0)
        # Underground rooms should have dark/underground tags
        self.assertTrue(
            any(t in blueprint.tags for t in ("underground", "dark")),
            f"Underground room missing expected tags, got: {blueprint.tags}",
        )

    def test_generate_room_determinism(self):
        """Same inputs should produce same outputs."""
        from aspects.worldgen import generate_room
        from aspects.worldgen.base import GenerationContext

        context = GenerationContext()
        bp1 = generate_room((42, 42, 0), context)
        bp2 = generate_room((42, 42, 0), context)

        self.assertEqual(bp1.exits, bp2.exits)
        self.assertEqual(bp1.biome, bp2.biome)
        self.assertEqual(bp1.scale, bp2.scale)
        self.assertEqual(bp1.description, bp2.description)

    def test_generate_room_with_context(self):
        """Pipeline should respect generation context."""
        from aspects.worldgen import generate_room
        from aspects.worldgen.base import GenerationContext

        context = GenerationContext(
            came_from=(5, 5, 0),
            came_from_description="A dense forest clearing.",
            came_from_biome="forest",
        )
        blueprint = generate_room((5, 6, 0), context)

        # Should always include exit back to came_from
        self.assertIn("south", blueprint.exits)

    def test_landmark_influence_in_pipeline(self):
        """Landmarks near a tile should influence the blueprint."""
        from aspects.worldgen.base import GenerationContext
        from aspects.worldgen.landmarks import _landmark_at

        # Find a landmark center
        center = None
        for x in range(500):
            lm = _landmark_at(x, 0, 0)
            if lm is not None:
                center = (x, 0, 0)
                break

        if center is None:
            self.skipTest("No landmark found in search range")

        from aspects.worldgen import generate_room

        context = GenerationContext()
        blueprint = generate_room(center, context)

        # Blueprint at landmark center should have landmark data
        self.assertIsNotNone(
            blueprint.landmark, "Blueprint at landmark center should have landmark"
        )


class TestGeneratorRegistry(unittest.TestCase):
    """Test the generator registry system."""

    def test_default_generators(self):
        """Registry should have overworld and dungeon generators."""
        from aspects.worldgen import _GENERATORS

        self.assertIn("overworld", _GENERATORS)
        self.assertIn("dungeon", _GENERATORS)

    def test_register_custom_generator(self):
        """Should be able to register a custom generator."""
        from aspects.worldgen import _GENERATORS, register_generator
        from aspects.worldgen.base import RoomBlueprint

        class MockGenerator:
            def generate(self, coords, context):
                return RoomBlueprint(
                    exits={"north": (0, 1, 0)},
                    biome="test_biome",
                    terrain=[],
                    description_hint="test",
                    scale="room",
                )

        register_generator("test", MockGenerator())
        self.assertIn("test", _GENERATORS)

        # Clean up
        del _GENERATORS["test"]

    def test_fallback_to_overworld(self):
        """Unknown generator name should fall back to overworld."""
        from aspects.worldgen import _GENERATORS, _get_generator

        gen = _get_generator("nonexistent_generator")
        self.assertIs(gen, _GENERATORS["overworld"])


if __name__ == "__main__":
    unittest.main()
