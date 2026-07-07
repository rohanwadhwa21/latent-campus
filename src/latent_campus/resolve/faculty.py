"""Resolve SOC instructor surname tokens to directory people (Week 4 ER).

The resolution unit is the (surname, offering-dept) PAIR — the SOC gives us
last names only, so the offering's department is the disambiguator. For each
pair, the candidate pool is every Faculty/Staff directory person returned by
that surname's search:

  capped surname       -> "capped": the pool is truncated at 200 results, so it
                          can never prove uniqueness — manual queue, never auto.
  exactly 1 candidate whose mapped SOC dept codes contain the offering dept
                       -> resolved, method "dept-unique" (the strong case)
  0 dept matches but exactly 1 candidate for the surname overall
                       -> resolved, method "global-unique" (weaker: relies on
                          the surname being rare; validated by the labeled-pair
                          precision check and droppable independently)
  >=2 dept matches      -> "ambiguous": manual queue
  otherwise             -> "no-match": no node (locked: non-directory
                          instructors get no Faculty node)

Leakage rule (locked): nothing here reads course text — inputs are surname
tokens, dept codes, and directory records only.
"""

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["resolved", "ambiguous", "no-match", "capped"]


class Candidate(BaseModel):
    """One directory person in a surname's candidate pool."""

    andrew_id: str
    display_name: str
    affiliation: str
    job_titles: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)  # HR names, verbatim
    campus_room: str | None = None
    dept_codes: set[str] = Field(default_factory=set)  # filled via map_departments


class Resolution(BaseModel):
    """Outcome for one (surname, dept) pair."""

    surname: str
    dept_code: str
    status: Status
    method: Literal["dept-unique", "global-unique"] | None = None
    andrew_id: str | None = None
    n_candidates: int = 0
    n_dept_matches: int = 0


def map_departments(hr_names: list[str], dept_map: dict[str, list[str] | None]) -> set[str]:
    """HR department names -> the union of their mapped SOC codes.

    Unmapped names and explicit nulls (non-teaching units) contribute nothing.
    """
    codes: set[str] = set()
    for name in hr_names:
        codes.update(dept_map.get(name) or [])
    return codes


def attach_dept_codes(
    candidates: list[Candidate], dept_map: dict[str, list[str] | None]
) -> list[Candidate]:
    return [
        c.model_copy(update={"dept_codes": map_departments(c.departments, dept_map)})
        for c in candidates
    ]


def resolve_pair(
    surname: str, dept_code: str, candidates: list[Candidate], capped: bool
) -> Resolution:
    """Resolve one (surname, offering-dept) pair against its candidate pool.

    `candidates` must already carry dept_codes (attach_dept_codes)."""
    base = {"surname": surname, "dept_code": dept_code, "n_candidates": len(candidates)}
    if capped:
        return Resolution(status="capped", **base)

    dept_matches = [c for c in candidates if dept_code in c.dept_codes]
    base["n_dept_matches"] = len(dept_matches)
    if len(dept_matches) == 1:
        return Resolution(status="resolved", method="dept-unique",
                          andrew_id=dept_matches[0].andrew_id, **base)
    if len(dept_matches) >= 2:
        return Resolution(status="ambiguous", **base)
    if len(candidates) == 1:
        return Resolution(status="resolved", method="global-unique",
                          andrew_id=candidates[0].andrew_id, **base)
    if len(candidates) >= 2:
        return Resolution(status="ambiguous", **base)
    return Resolution(status="no-match", **base)
