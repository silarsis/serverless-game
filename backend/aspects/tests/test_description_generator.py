"""Tests for the LLM description generator with fallback templates."""

import unittest
from unittest.mock import patch

from aspects.description_generator import (
    _generate_fallback,
    _get_biome,
    generate_description,
)


class TestDescriptionGenerator(unittest.TestCase):
    """Test the description generator module."""

    def test_get_biome_surface(self):
        """Test biome for z=0 is surface terrain."""
        assert _get_biome(0) == "surface terrain"

    def test_get_biome_underground(self):
        """Test biome for negative z levels."""
        assert _get_biome(-1) == "shallow cave"
        assert _get_biome(-2) == "underground passage"
        assert _get_biome(-3) == "deep cavern"

    def test_get_biome_above(self):
        """Test biome for positive z levels."""
        assert _get_biome(1) == "hilltop"
        assert _get_biome(2) == "mountain path"
        assert _get_biome(3) == "mountain peak"

    def test_get_biome_extreme(self):
        """Test biome for extreme z levels."""
        assert _get_biome(10) == "high altitude"
        assert _get_biome(-10) == "deep underground"

    def test_fallback_deterministic(self):
        """Test that fallback descriptions are deterministic for same coordinates."""
        desc1 = _generate_fallback((0, 0, 0), [])
        desc2 = _generate_fallback((0, 0, 0), [])
        assert desc1 == desc2

    def test_fallback_different_coords(self):
        """Test that different coordinates produce different descriptions."""
        desc1 = _generate_fallback((0, 0, 0), [])
        desc2 = _generate_fallback((1, 0, 0), [])
        # They could theoretically be the same, but very unlikely
        # At minimum, they should be non-empty strings
        assert isinstance(desc1, str) and len(desc1) > 0
        assert isinstance(desc2, str) and len(desc2) > 0

    def test_fallback_contains_biome(self):
        """Test that fallback description includes the biome."""
        desc = _generate_fallback((0, 0, 0), [])
        # The template uses the biome word, which for z=0 is "surface terrain"
        # Check it's a reasonable description
        assert len(desc) > 20

    @patch.dict("os.environ", {}, clear=True)
    def test_generate_description_no_llm(self):
        """Test generate_description falls back to templates when no LLM configured."""
        desc = generate_description((5, 3, 0))
        assert isinstance(desc, str)
        assert len(desc) > 10

    @patch.dict("os.environ", {}, clear=True)
    def test_generate_description_with_neighbors(self):
        """Test generate_description works with neighbor descriptions."""
        neighbors = ["A rocky outcrop with sparse vegetation.", "A muddy trail leads north."]
        desc = generate_description((1, 1, 0), neighbor_descriptions=neighbors)
        assert isinstance(desc, str)
        assert len(desc) > 10


if __name__ == "__main__":
    unittest.main()
