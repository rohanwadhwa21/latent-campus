"""Tests for the SOC courseDetails parser (gap-fill source for grad/Heinz)."""

from pathlib import Path

from latent_campus.ingest.details_parse import parse_course_details

FIXTURES = Path(__file__).parent / "fixtures"

CROSS_LIST_HTML = """
<div id="course-detail-description"><h4>Description:</h4>
<p class="text-left">A joint course on learning.</p></div>
<dl><dt>Prerequisites</dt><dd>15-122</dd></dl>
<dl><dt>Cross-Listed Courses</dt><dd>10-701 ; 16-831</dd></dl>
"""


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="iso-8859-1", errors="replace")


def test_real_page_parses_description():
    entry = parse_course_details(_load("details_real_95703.html"), "95-703")
    assert entry is not None
    assert entry.course_id == "95-703"
    assert "atabase" in entry.description  # "Databases systems are central..."
    assert len(entry.description) > 100


def test_error_page_returns_none():
    assert parse_course_details(_load("details_error.html"), "99-999") is None


def test_app_error_string_returns_none():
    assert parse_course_details("...error has occurred in this application...", "15-100") is None


def test_cross_list_extraction():
    entry = parse_course_details(CROSS_LIST_HTML, "15-781")
    assert entry is not None
    assert entry.cross_listed_ids == ["10-701", "16-831"]
    assert entry.prerequisites == "15-122"


def test_self_excluded_from_cross_list():
    html = CROSS_LIST_HTML.replace("10-701", "15-781")  # self-reference
    entry = parse_course_details(html, "15-781")
    assert "15-781" not in entry.cross_listed_ids
