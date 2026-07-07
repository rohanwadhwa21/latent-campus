"""Directory search-page parser vs real (trimmed) HTML fixtures.

Fixtures captured 2026-07-06 from directory.andrew.cmu.edu:
  directory_detail_single.html   single-hit search -> person detail page
  directory_results_multi.html   multi-hit table (7 rows kept: Faculty/Staff/
                                 Sponsored/Student, hyphenated, multi-dept)
  directory_results_capped.html  200-result cap message present (3 rows kept)
  directory_results_empty.html   zero-hit -> bare search form
"""

from pathlib import Path

import pytest

from latent_campus.ingest.directory_parse import parse_person_detail, parse_search_results

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


class TestSingleHitDetail:
    @pytest.fixture
    def page(self):
        return parse_search_results(_load("directory_detail_single.html"))

    def test_kind_single_with_person(self, page):
        assert page.kind == "single"
        assert not page.capped
        assert page.hits == []
        assert page.person is not None

    def test_person_fields(self, page):
        p = page.person
        assert p.display_name == "David Scott Kosbie"
        assert p.affiliation == "Faculty"
        assert p.andrew_id == "koz"
        assert p.campus_room == "GHC 5001"
        assert p.job_titles == ["Teaching Professor"]
        assert p.departments == ["Computer Science Department"]

    def test_parse_person_detail_direct(self):
        p = parse_person_detail(_load("directory_detail_single.html"))
        assert p is not None and p.andrew_id == "koz"

    def test_detail_on_non_detail_page_is_none(self):
        assert parse_person_detail(_load("directory_results_empty.html")) is None


class TestMultiHitTable:
    @pytest.fixture
    def page(self):
        return parse_search_results(_load("directory_results_multi.html"))

    def test_kind_and_count(self, page):
        assert page.kind == "multi"
        assert not page.capped
        assert len(page.hits) == 7

    def test_row_fields(self, page):
        faculty = [h for h in page.hits if h.affiliation == "Faculty"]
        assert len(faculty) == 1
        h = faculty[0]
        assert h.last_name == "Smith"
        assert h.first_name == "Andrew W"
        assert h.departments == ["Drama"]
        assert h.guid  # detail link extracted

    def test_hyphenated_last_name(self, page):
        assert any(h.last_name == "Smith-Edwards" for h in page.hits)

    def test_multi_department_cell_split_and_raw_kept(self, page):
        multi = [h for h in page.hits if len(h.departments) > 1]
        assert multi, "fixture contains a multi-department row"
        h = multi[0]
        assert h.departments_raw == ", ".join(h.departments)

    def test_affiliations_present(self, page):
        assert {"Faculty", "Staff", "Sponsored", "Student"} <= {h.affiliation for h in page.hits}


class TestCappedPage:
    def test_cap_flag_set(self):
        page = parse_search_results(_load("directory_results_capped.html"))
        assert page.kind == "multi"
        assert page.capped
        assert len(page.hits) == 3


class TestEmptyPage:
    def test_zero_hits(self):
        page = parse_search_results(_load("directory_results_empty.html"))
        assert page.kind == "empty"
        assert not page.capped
        assert page.hits == [] and page.person is None
