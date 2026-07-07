"""Parser tests.

Two tiers:
  1. Pure-helper tests.
  2. Fixture tests against real SOC complete-schedule HTML (trimmed to the
     first two department sections), one fixture per format variant:
       complete_schedule_old_S25.html — 10-col, with Bldg/Room + Instructor
       complete_schedule_new_S26.html — 8-col, columns removed by CMU (F25+)
"""

from pathlib import Path

import pytest

from latent_campus.common.schemas import GENERIC_NUMBER_RE, normalize_course_id
from latent_campus.ingest.soc_parse import (
    detect_mini,
    detect_semester_banner,
    parse_complete_schedule,
    parse_room,
    parse_units,
    split_instructors,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestNormalizeCourseId:
    def test_plain_digits(self):
        assert normalize_course_id("15440") == "15-440"

    def test_already_hyphenated(self):
        assert normalize_course_id("15-440") == "15-440"

    def test_whitespace_and_separators(self):
        assert normalize_course_id(" 15 440 ") == "15-440"

    def test_rejects_wrong_length(self):
        with pytest.raises(ValueError):
            normalize_course_id("1544")


class TestParseRoom:
    def test_building_and_room(self):
        assert parse_room("GHC 4401") == ("GHC", "GHC 4401")

    def test_tba(self):
        assert parse_room("TBA") == (None, "TBA")

    def test_dnm(self):
        assert parse_room("DNM DNM") == (None, "DNM DNM")

    def test_none(self):
        assert parse_room(None) == (None, None)


class TestSplitInstructors:
    """Instructor strings are comma-joined LAST NAMES (verified Task 0)."""

    def test_single(self):
        assert split_instructors("Yang") == ["Yang"]

    def test_co_taught(self):
        assert split_instructors("Taylor, Kosbie") == ["Taylor", "Kosbie"]

    def test_tba(self):
        assert split_instructors("Instructor TBA") == []

    def test_empty(self):
        assert split_instructors(None) == []
        assert split_instructors("  ") == []


class TestDetectMini:
    def test_mini_in_title(self):
        assert detect_mini("Intro to Something Mini 1") == 1
        assert detect_mini("Intro to Something Mini-2") == 2

    def test_no_mini(self):
        assert detect_mini("Distributed Systems") is None


class TestParseUnits:
    def test_numeric(self):
        assert parse_units("12.0") == (12.0, "12.0")

    def test_var(self):
        assert parse_units("VAR") == (None, "VAR")

    def test_blank(self):
        assert parse_units("  ") == (None, None)


class TestGenericNumbers:
    def test_thesis_flagged(self):
        assert GENERIC_NUMBER_RE.match("15-997")
        assert GENERIC_NUMBER_RE.match("18-599")

    def test_regular_not_flagged(self):
        assert not GENERIC_NUMBER_RE.match("15-440")


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="iso-8859-1", errors="replace")


class TestParseOldFormat:
    @pytest.fixture(scope="class")
    def parsed(self):
        return parse_complete_schedule(_load("complete_schedule_old_S25.html"), "S25")

    def test_offerings_parsed(self, parsed):
        offerings, _ = parsed
        assert len(offerings) > 50

    def test_semester_banner(self):
        assert detect_semester_banner(_load("complete_schedule_old_S25.html")) == "S25"

    def test_wrong_semester_rejected(self):
        with pytest.raises(ValueError, match="banner"):
            parse_complete_schedule(_load("complete_schedule_old_S25.html"), "F25")

    def test_has_instructors_and_rooms(self, parsed):
        offerings, _ = parsed
        with_instr = [o for o in offerings if o.instructor_names_raw]
        assert len(with_instr) > len(offerings) * 0.5
        rooms = [m.building_code for o in offerings for m in o.meetings if m.building_code]
        assert rooms, "old format should yield building codes"

    def test_dept_names_seeded(self, parsed):
        _, dept_names = parsed
        assert "48" in dept_names  # Architecture is the first section
        assert dept_names["48"] == "Architecture"

    def test_offering_shape(self, parsed):
        offerings, _ = parsed
        for o in offerings:
            assert o.course_id and o.section and o.semester == "S25"
            assert o.meetings


class TestParseNewFormat:
    @pytest.fixture(scope="class")
    def parsed(self):
        return parse_complete_schedule(_load("complete_schedule_new_S26.html"), "S26")

    def test_offerings_parsed(self, parsed):
        offerings, _ = parsed
        assert len(offerings) > 50

    def test_no_instructors_in_new_format(self, parsed):
        offerings, _ = parsed
        assert all(not o.instructor_names_raw for o in offerings)

    def test_campus_still_parsed(self, parsed):
        offerings, _ = parsed
        campuses = {m.campus for o in offerings for m in o.meetings if m.campus}
        assert "Pittsburgh, Pennsylvania" in campuses
