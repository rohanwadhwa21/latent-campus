"""Cross-validate resolved TEACHES edges against cmucourses (Week 4 gate).

Our resolution turned a bare SOC surname into a specific directory person.
cmucourses (ScottyLabs; FCE-derived) independently records instructor FULL
names per (course, semester). For every edge we look up that course-semester's
"Last, First" instructors and compare:

  confirmed  surname matches AND the first name agrees with our person
  refuted    surname matches but the FIRST NAME DISAGREES -> possibly the
             wrong person; goes to human adjudication (NOT auto-dropped:
             preferred-vs-legal first names cause false refutes)
  no_data    cmucourses lacks that course/semester or that surname

Precision (pessimistic) = confirmed / (confirmed + refuted), reported per
match_method (dept-unique vs global-unique are accepted/dropped separately).

Locked decision: cmucourses is a cross-validation source ONLY — nothing from
it enters the atlas.

  -> data/canonical/crossval_refuted.csv  (adjudication queue)
"""

import json
import urllib.parse
from collections import defaultdict

import polars as pl

from latent_campus.common.config import DATA_DIR, load_config
from latent_campus.common.fetch import PoliteFetcher

CANONICAL_DIR = DATA_DIR / "canonical"
BATCH = 25
# our semester codes -> cmucourses (semester, year)
SEM = {"F23": ("fall", 2023), "S24": ("spring", 2024),
       "F24": ("fall", 2024), "S25": ("spring", 2025)}


def fetch_schedules(course_ids: list[str]) -> dict[str, list[dict]]:
    """courseID -> schedules list, via batched cached GETs."""
    base = load_config("sources")["cmucourses"]["base_url"] + "/courses"
    fetcher = PoliteFetcher("cmucourses")
    out: dict[str, list[dict]] = {}
    batches = [course_ids[i:i + BATCH] for i in range(0, len(course_ids), BATCH)]
    for i, batch in enumerate(batches, 1):
        qs = urllib.parse.urlencode([("courseID", c) for c in batch] + [("schedules", "true")])
        result = fetcher.fetch(f"{base}?{qs}")
        try:
            payload = json.loads(result.content_path.read_text())
        except (OSError, json.JSONDecodeError):
            payload = json.loads(
                fetcher.fetch(f"{base}?{qs}", force=True).content_path.read_text()
            )
        for course in payload:
            out[course["courseID"]] = course.get("schedules") or []
        if i % 20 == 0:
            print(f"  {i}/{len(batches)} batches", flush=True)
    fetcher.close()
    return out


def instructor_index(schedules: dict[str, list[dict]]) -> dict[tuple[str, str], set[str]]:
    """(course_id, our-semester-code) -> {"Last, First", ...}"""
    want = {v: k for k, v in SEM.items()}
    idx: dict[tuple[str, str], set[str]] = defaultdict(set)
    for cid, scheds in schedules.items():
        for s in scheds:
            sem_code = want.get((s.get("semester"), s.get("year")))
            if sem_code is None:
                continue
            for lec in s.get("lectures") or []:
                idx[(cid, sem_code)].update(lec.get("instructors") or [])
    return idx


def split_cc_name(name: str) -> tuple[str, str]:
    """'Kosbie, David' -> ('kosbie', 'david'). Missing comma -> whole as last."""
    last, _, first = name.partition(",")
    return last.strip().casefold(), first.strip().casefold()


def verdict(surname: str, display_name: str, cc_names: set[str]) -> str:
    """Compare our resolved person against cmucourses' names for the slot."""
    ours_first = display_name.split()[0].casefold() if display_name else ""
    same_surname = [split_cc_name(n)[1] for n in cc_names
                    if split_cc_name(n)[0] == surname.casefold()]
    if not same_surname:
        return "no_data"
    for cc_first in same_surname:
        a, b = cc_first.split()[0] if cc_first else "", ours_first
        if a and b and (a == b or a.startswith(b) or b.startswith(a)):
            return "confirmed"
    return "refuted"


def main() -> None:
    edges = pl.read_parquet(CANONICAL_DIR / "course_faculty.parquet")
    fac = pl.read_parquet(CANONICAL_DIR / "faculty.parquet")
    edges = edges.join(
        fac.select(pl.col("faculty_id"), pl.col("display_name")), on="faculty_id"
    )
    course_ids = sorted(set(edges.get_column("course_id")))
    print(f"{len(edges)} edges over {len(course_ids)} courses; fetching cmucourses...")

    idx = instructor_index(fetch_schedules(course_ids))
    print(f"{len(idx)} (course, semester) slots with instructor data")

    rows = []
    for e in edges.iter_rows(named=True):
        cc = idx.get((e["course_id"], e["semester"]), set())
        rows.append({**e, "verdict": verdict(e["surname_token"], e["display_name"], cc),
                     "cc_names": "; ".join(sorted(cc))})
    out = pl.from_dicts(rows)

    print("\n=== verdicts by match method ===")
    pivot = out.group_by("match_method", "verdict").len().sort("match_method", "verdict")
    print(pivot)
    for method in ("dept-unique", "global-unique"):
        sub = out.filter(pl.col("match_method") == method)
        c = sub.filter(pl.col("verdict") == "confirmed").height
        r = sub.filter(pl.col("verdict") == "refuted").height
        cov = (c + r) / max(len(sub), 1)
        prec = c / max(c + r, 1)
        print(f"{method}: precision {prec:.3%} (confirmed {c} / refuted {r}; "
              f"{cov:.0%} of edges verifiable)")

    refuted = out.filter(pl.col("verdict") == "refuted").select(
        "surname_token", "dept_code", "course_id", "semester",
        "faculty_id", "display_name", "match_method", "cc_names",
    ).unique(subset=["surname_token", "faculty_id", "course_id"])
    path = CANONICAL_DIR / "crossval_refuted.csv"
    refuted.write_csv(path)
    print(f"\n{len(refuted)} distinct refuted (surname, person, course) rows -> {path}")


if __name__ == "__main__":
    main()
