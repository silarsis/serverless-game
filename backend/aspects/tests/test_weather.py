"""Tests for the Weather aspect (time periods, weather conditions).

Tests the noise-based weather computation system:
- Time period calculation from wall clock
- Weather computation from coordinates and time
- Biome-specific descriptions
- Determinism (same input = same output)
"""


from backend.aspects.weather import (
    get_time_period,
    get_weather_at,
    get_time_description,
    add_weather_to_description,
    _noise,
    _get_location_seed,
    WEATHER_OPTIONS,
    TIME_PERIODS,
)


class TestTimePeriod:
    """Tests for day/night time period calculation."""

    def test_returns_valid_period(self):
        """get_time_period should return a valid time period."""
        period = get_time_period()
        assert period in TIME_PERIODS

    def test_consistency(self):
        """Time period should be consistent across multiple calls."""
        period1 = get_time_period()
        period2 = get_time_period()
        assert period1 == period2


class TestWeatherAt:
    """Tests for weather computation at location."""

    def test_returns_valid_weather(self):
        """get_weather_at should return a valid weather type."""
        weather, desc = get_weather_at(100, 50, "plains")
        assert weather in WEATHER_OPTIONS

    def test_returns_description(self):
        """get_weather_at should return a non-empty description."""
        weather, desc = get_weather_at(100, 50, "plains")
        assert desc is not None
        assert len(desc) > 0

    def test_different_locations_different_weather(self):
        """Different locations should potentially have different weather."""
        weather1, _ = get_weather_at(0, 0, "plains")
        weather2, _ = get_weather_at(1000, 1000, "plains")
        # Not guaranteed to be different, but should not error
        assert weather1 in WEATHER_OPTIONS
        assert weather2 in WEATHER_OPTIONS

    def test_biome_affects_description(self):
        """Different biomes should produce different descriptions."""
        _, desc_plains = get_weather_at(100, 50, "plains")
        _, desc_forest = get_weather_at(100, 50, "forest")
        # Different biomes should have different flavor text
        assert desc_plains != desc_forest

    def test_unknown_biome_falls_back_to_default(self):
        """Unknown biomes should use default description."""
        weather, desc = get_weather_at(100, 50, "unknown_biome")
        assert weather in WEATHER_OPTIONS
        # Should still return something (default)
        assert len(desc) > 0


class TestNoiseFunction:
    """Tests for the noise function determinism."""

    def test_deterministic(self):
        """Same inputs should produce same output."""
        result1 = _noise(1.0, 2.0, 12345)
        result2 = _noise(1.0, 2.0, 12345)
        assert result1 == result2

    def test_different_coords_different_output(self):
        """Different coordinates should produce different output."""
        result1 = _noise(1.0, 2.0, 12345)
        result2 = _noise(3.0, 4.0, 12345)
        assert result1 != result2

    def test_different_seeds_different_output(self):
        """Different seeds should produce different output."""
        result1 = _noise(1.0, 2.0, 12345)
        result2 = _noise(1.0, 2.0, 67890)
        assert result1 != result2

    def test_output_in_range(self):
        """Noise output should be between 0 and 1."""
        result = _noise(100.0, 200.0, 12345)
        assert 0.0 <= result <= 1.0


class TestLocationSeed:
    """Tests for location seed generation."""

    def test_deterministic(self):
        """Same coordinates should produce same seed."""
        seed1 = _get_location_seed(100, 50)
        seed2 = _get_location_seed(100, 50)
        assert seed1 == seed2

    def test_different_coords_different_seed(self):
        """Different coordinates should produce different seeds."""
        seed1 = _get_location_seed(100, 50)
        seed2 = _get_location_seed(200, 100)
        assert seed1 != seed2


class TestTimeDescription:
    """Tests for time description generation."""

    def test_returns_string(self):
        """get_time_description should return a string."""
        desc = get_time_description()
        assert isinstance(desc, str)

    def test_non_empty(self):
        """get_time_description should return non-empty string."""
        desc = get_time_description()
        assert len(desc) > 0


class TestAddWeatherToDescription:
    """Tests for the weather overlay function."""

    def test_appends_time_description(self):
        """Should append time period description."""
        result = add_weather_to_description("A room.", 100, 50, "plains")
        assert "A room." in result
        # Should have additional atmospheric text
        assert len(result) > len("A room.")

    def test_appends_weather_description(self):
        """Should append weather description."""
        result = add_weather_to_description("A room.", 100, 50, "plains")
        # Should contain weather-related words
        # (the exact word depends on the noise function output)
        words = result.lower().split()
        atmospheric_words = {
            "rain", "clear", "fog", "storm", "snow", "sky",
            "sunlight", "darkness", "dawn", "dusk", "light"
        }
        has_atmosphere = any(w in atmospheric_words for w in words)
        assert has_atmosphere

    def test_handles_empty_description(self):
        """Should handle empty input description."""
        result = add_weather_to_description("", 100, 50, "plains")
        # Should still add atmospheric text
        assert len(result) > 0

    def test_handles_all_biomes(self):
        """Should handle all supported biomes."""
        biomes = ["plains", "forest", "desert", "swamp", "mountain"]
        for biome in biomes:
            result = add_weather_to_description("Test.", 100, 50, biome)
            assert len(result) > len("Test.")


class TestWeatherTypes:
    """Tests for weather type distribution."""

    def test_all_weather_types_valid(self):
        """All weather options should be valid strings."""
        for weather in WEATHER_OPTIONS:
            assert isinstance(weather, str)
            assert len(weather) > 0

    def test_weather_options_covered(self):
        """Should have expected weather types."""
        expected = {"clear", "rain", "fog", "storm", "snow"}
        actual = set(WEATHER_OPTIONS)
        assert expected.issubset(actual)


class TestTimePeriods:
    """Tests for time period configuration."""

    def test_all_periods_valid(self):
        """All time periods should be valid strings."""
        for period in TIME_PERIODS:
            assert isinstance(period, str)
            assert len(period) > 0

    def test_expected_periods_present(self):
        """Should have all expected periods."""
        expected = {"dawn", "day", "dusk", "night"}
        actual = set(TIME_PERIODS)
        assert expected == actual
