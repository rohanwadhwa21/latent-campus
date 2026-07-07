"""Tests for the course-catalog description parser, against a real fixture
(first few ECE courseblocks captured from coursecatalog.web.cmu.edu)."""

from pathlib import Path

import pytest

from latent_campus.ingest.catalog_parse import parse_catalog_page

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def entries():
    html = (FIXTURES / "catalog_ece_sample.html").read_text(encoding="utf-8")
    return parse_catalog_page(html)


def test_parses_blocks(entries):
    assert len(entries) >= 3


def test_course_ids_normalized(entries):
    for e in entries:
        assert e.course_id.startswith("18-")
        assert len(e.course_id) == 6  # "18-059"


def test_title_separated_from_code(entries):
    first = entries[0]
    assert first.course_id == "18-059"
    assert first.title == "Introduction to Amateur Radio"


def test_description_is_prose_not_units(entries):
    e = entries[0]
    assert "unit" not in e.description[:20].lower()
    assert len(e.description) > 100
    assert e.units_text == "3"
    assert e.offered_terms == "Spring"


def test_multi_term_units(entries):
    by_id = {e.course_id: e for e in entries}
    assert by_id["18-100"].offered_terms == "Fall and Spring"
    assert by_id["18-100"].units_text == "12"
