"""Parse the SOC nightly "complete schedule" dump into CourseOffering rows.

Verified structure (Task 0, 2026-06-13). One big <table>, two variants:

  OLD (semesters <= S25, via Wayback):  10 data columns
    Course | Title | Units | Lec/Sec | Days | Begin | End | Bldg/Room | Location | Instructor
  NEW (>= F25):                          8 data columns
    Course | Title | Units | Lec/Sec | Days | Begin | End | Location

Row kinds, both variants:
  - department header: first cell is the bold dept name, rest &nbsp;
  - course row:        first cell is a 5-digit course number
  - section row:       course cells &nbsp;, Lec/Sec cell set
  - extra meeting row: course AND Lec/Sec cells &nbsp;

Instructors are comma-joined LAST NAMES: "Taylor, Kosbie" is two people.
NEW-variant tags are uppercase (<TR>, <TD>); parse case-insensitively.
"""

import re

from bs4 import BeautifulSoup

from latent_campus.common.schemas import CourseOffering, Meeting, normalize_course_id

ROOM_RE = re.compile(r"^([A-Z]{2,4})\s+([\w-]+)$")  # "GHC 4401" -> ("GHC", "4401")
MINI_TITLE_RE = re.compile(r"\bmini[\s-]*([12])\b", re.IGNORECASE)
COURSE_NUM_RE = re.compile(r"^\d{5}$")
SEMESTER_BANNER_RE = re.compile(r"\b(Spring|Summer|Fall)\s*(20\d\d)\b")

_BANNER_TO_CODE = {"Spring": "S", "Fall": "F", "Summer": "M"}


def parse_room(raw: str | None) -> tuple[str | None, str | None]:
    """'GHC 4401' -> ('GHC', 'GHC 4401'). TBA/DNM/blank -> (None, raw)."""
    if not raw:
        return None, None
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw or raw.upper() in {"TBA", "DNM", "DNM DNM", "REMOTE"}:
        return None, raw or None
    m = ROOM_RE.match(raw)
    return (m.group(1) if m else None), raw


def split_instructors(raw: str | None) -> list[str]:
    """Comma-joined last names: 'Taylor, Kosbie' -> ['Taylor', 'Kosbie'].

    'Instructor TBA' / blank -> []. Names are LAST NAMES ONLY (the dump
    carries no first names/initials) — full identity comes in Phase 2 ER.
    """
    if not raw:
        return []
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw or "TBA" in raw.upper():
        return []
    return [name.strip() for name in raw.split(",") if name.strip()]


def detect_mini(title: str) -> int | None:
    """Mini flag from title suffix ('... Mini 1'); the dump has no Mini column."""
    if m := MINI_TITLE_RE.search(title):
        return int(m.group(1))
    return None


def parse_units(raw: str | None) -> tuple[float | None, str | None]:
    """'12.0' -> (12.0, '12.0'); 'VAR' -> (None, 'VAR'); blank -> (None, None)."""
    if not raw or not raw.strip():
        return None, None
    raw = raw.strip()
    try:
        return float(raw), raw
    except ValueError:
        return None, raw


def detect_semester_banner(html: str) -> str | None:
    """'Spring 2025' anywhere in the page -> 'S25'. Sanity check for Wayback fetches."""
    if m := SEMESTER_BANNER_RE.search(html):
        return _BANNER_TO_CODE[m.group(1)] + m.group(2)[2:]
    return None


def _clean(cell) -> str:
    text = cell.get_text(" ", strip=True)
    return "" if text == "\xa0" else re.sub(r"\s+", " ", text).replace("\xa0", " ").strip()


def parse_complete_schedule(html: str, semester: str) -> tuple[list[CourseOffering], dict]:
    """Parse one nightly dump. Returns (offerings, dept_names) where dept_names
    maps dept_code -> department display name (free alias-dictionary seed).
    """
    banner = detect_semester_banner(html)
    if banner and banner != semester:
        raise ValueError(f"page banner says {banner}, expected {semester}")

    soup = BeautifulSoup(html, "lxml")
    has_instructors = "Bldg/Room" in html  # OLD 10-col variant

    offerings: list[CourseOffering] = []
    dept_names: dict[str, str] = {}
    current_dept_name: str | None = None
    current: CourseOffering | None = None
    course_id: str | None = None
    title: str | None = None
    units_raw: str | None = None

    for row in soup.find_all("tr"):
        cells = [_clean(td) for td in row.find_all("td")]
        if not cells or all(not c for c in cells):
            continue
        first = cells[0]

        # department header: bold name in first cell, all other cells blank
        if first and not COURSE_NUM_RE.match(first) and all(not c for c in cells[1:]):
            current_dept_name = first
            continue
        if len(cells) < 8:
            continue  # column headers and decoration

        if COURSE_NUM_RE.match(first):  # new course block
            course_id = normalize_course_id(first)
            title = cells[1]
            units_raw = cells[2] or None
            if current_dept_name:
                dept_names.setdefault(course_id[:2], current_dept_name)
        if course_id is None:
            continue

        section = cells[3]
        days, begin, end = cells[4] or None, cells[5] or None, cells[6] or None
        if has_instructors:
            building_code, room = parse_room(cells[7])
            campus = cells[8] or None
            instructors = split_instructors(cells[9]) if len(cells) > 9 else []
        else:
            building_code, room = None, None
            campus = cells[7] or None
            instructors = []

        if section:  # new section -> new offering
            current = CourseOffering(
                offering_id=f"{course_id}_{semester}_{section.replace(' ', '')}",
                course_id=course_id,
                semester=semester,
                section=section,
                title=title or "",
                units_raw=units_raw,
                mini=detect_mini(title or ""),
                instructor_names_raw=instructors,
            )
            offerings.append(current)
        elif current is not None and instructors:
            # extra meeting row may carry an additional instructor
            for name in instructors:
                if name not in current.instructor_names_raw:
                    current.instructor_names_raw.append(name)
        if current is None:
            continue
        current.meetings.append(
            Meeting(
                days=days, begin=begin, end=end,
                room=room, building_code=building_code, campus=campus,
            )
        )
    return offerings, dept_names
