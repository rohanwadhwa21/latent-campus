"""Pydantic schemas for canonical course data.

Two-level model (see SCHEMAS.md):
  Course         — semester-independent catalog entry, key = dept_code + course_number
  CourseOffering — a specific semester/section instance of a Course

Descriptions come from the course catalog (Week 2); the SOC has none,
so Course.description is nullable with description_source tracking.

Week 4 adds people:
  Faculty           — a directory-resolved person (node exists ONLY on a
                      confident directory match; leakage rule: attributes come
                      from the directory, never from taught-course text)
  CourseFacultyEdge — offering -> faculty TEACHES edge with its evidence
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SEMESTER_RE = re.compile(r"^[FS]\d{2}$")  # F25, S26 — summers excluded by design
COURSE_ID_RE = re.compile(r"^\d{2}-\d{3}$")  # "15-440"

# Course numbers that are independent study / thesis / reading shells:
# last two digits 97/98/99 (e.g. 15-997, 18-599). Flagged via Course.is_generic
# and excluded from DES/LIS findings (thin text embeds near-randomly).
# Heuristic — refine against the Week 1 validation report.
GENERIC_NUMBER_RE = re.compile(r"^\d{2}-\d(97|98|99)$")


def normalize_course_id(raw: str) -> str:
    """'15440' / '15-440' / ' 15 440 ' -> '15-440'."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 5:
        raise ValueError(f"course id {raw!r} does not contain 5 digits")
    return f"{digits[:2]}-{digits[2:]}"


class Meeting(BaseModel):
    """One scheduled meeting block of an offering section."""

    days: str | None = None  # as printed, e.g. "MW"
    begin: str | None = None  # "09:30AM"
    end: str | None = None  # "10:50AM"
    room: str | None = None  # as printed, e.g. "GHC 4401"
    building_code: str | None = None  # parsed from room, e.g. "GHC"
    campus: str | None = None  # "Pittsburgh, Pennsylvania" | "Doha, Qatar" | ...


class CourseOffering(BaseModel):
    """A specific semester/section instance. Key = course_id + semester + section."""

    offering_id: str  # "15-440_F25_A"
    course_id: str
    semester: str
    section: str
    title: str  # title as printed that semester (may drift across years)
    instructor_names_raw: list[str] = Field(default_factory=list)  # as printed: "Last, F"
    instructor_ids: list[str] = Field(default_factory=list)  # resolved in Phase 2, empty for now
    mini: int | None = None  # 1 or 2 if a mini, None if full-semester
    units_raw: str | None = None  # "12.0", "VAR", ...
    meetings: list[Meeting] = Field(default_factory=list)

    @field_validator("course_id")
    @classmethod
    def _valid_course_id(cls, v: str) -> str:
        if not COURSE_ID_RE.match(v):
            raise ValueError(f"bad course_id: {v!r}")
        return v

    @field_validator("semester")
    @classmethod
    def _valid_semester(cls, v: str) -> str:
        if not SEMESTER_RE.match(v):
            raise ValueError(f"bad semester code: {v!r}")
        return v


class Faculty(BaseModel):
    """A directory-resolved person. Key = faculty_id (Andrew ID).

    Acceptable-use compliance: no email/phone fields, by design.
    """

    faculty_id: str  # andrew_id — stable and unique
    display_name: str
    affiliation: str  # "Faculty" | "Staff" (teaching staff, e.g. adjunct instructors)
    job_titles: list[str] = Field(default_factory=list)  # HR titles, verbatim
    hr_departments: list[str] = Field(default_factory=list)  # directory lines, verbatim
    dept_codes: list[str] = Field(default_factory=list)  # mapped SOC codes (evidence for match)
    campus_room: str | None = None  # "GHC 5001" — Week 5 faculty->building signal
    building_code: str | None = None  # parsed from campus_room when well-formed


class CourseFacultyEdge(BaseModel):
    """One offering -> faculty TEACHES edge, with the evidence that made it."""

    offering_id: str
    course_id: str
    semester: str
    faculty_id: str
    surname_token: str  # the raw instructor token this edge came from
    dept_code: str  # offering dept used for disambiguation
    match_method: Literal["dept-unique", "global-unique"]


class Course(BaseModel):
    """Semester-independent catalog entry. Key = course_id."""

    course_id: str  # "15-440"
    dept_code: str  # "15"
    course_number: str  # "440"
    title: str  # most recent title
    description: str | None = None  # most recent non-empty (catalog, Week 2)
    description_source: Literal["catalog", "soc", "none"] = "none"
    units: float | None = None  # None when variable
    cross_listed_ids: list[str] = Field(default_factory=list)  # other course_ids, same canonical
    is_generic: bool = False  # independent study / thesis / reading shells
    first_seen_semester: str | None = None
    last_seen_semester: str | None = None

    @field_validator("course_id")
    @classmethod
    def _valid_course_id(cls, v: str) -> str:
        if not COURSE_ID_RE.match(v):
            raise ValueError(f"bad course_id: {v!r}")
        return v
