"""Tests for embedding-corpus text hygiene (no polars/torch import)."""

import pytest

from latent_campus.embed.text import clean_description, is_placeholder


class TestCleanDescription:
    def test_none_returns_empty(self):
        assert clean_description(None) == ""

    def test_decodes_html_entities(self):
        assert clean_description("Technology &amp; Management") == "Technology & Management"
        assert clean_description("students&#39; work") == "students' work"

    def test_collapses_whitespace(self):
        assert clean_description("a\n\n  b\tc") == "a b c"

    def test_strips_nbsp(self):
        assert clean_description("a\xa0b") == "a b"

    def test_leaves_real_text_intact(self):
        text = "An introduction to machine learning, covering supervised methods."
        assert clean_description(text) == text


class TestIsPlaceholder:
    @pytest.mark.parametrize(
        "raw",
        ["TBA", "tba", "TBD", "tbd", "N/A", "n/a", "None", "TBA.", " - ", "."],
    )
    def test_known_placeholders_dropped(self, raw):
        assert is_placeholder(clean_description(raw)) is True

    def test_empty_dropped(self):
        assert is_placeholder(clean_description("")) is True
        assert is_placeholder(clean_description(None)) is True

    def test_coming_soon_dropped(self):
        assert is_placeholder(clean_description("Coming Soon.")) is True
        assert is_placeholder(
            clean_description("Coming Soon. Course Website: https://soa.cmu.edu/courses")
        ) is True

    def test_bare_url_dropped(self):
        assert is_placeholder(clean_description("https://example.com/x")) is True
        assert is_placeholder(clean_description("Course Website: http://x.cmu.edu")) is True

    def test_real_short_description_kept(self):
        # Short but genuine content must survive (kept for the atlas; the
        # 200-char DES/LIS cut is applied downstream, not here).
        assert (
            is_placeholder(
                clean_description("A one hour private lesson per week for all music majors.")
            )
            is False
        )

    def test_real_long_description_kept(self):
        assert (
            is_placeholder(
                clean_description("An introduction to the theory and practice of X.")
            )
            is False
        )
