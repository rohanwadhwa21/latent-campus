"""Scrape SOC nightly dumps for configured semesters; parse to offerings JSON.

Usage:
    uv run python scripts/scrape_courses.py            # first semester in config (Week 1)
    uv run python scripts/scrape_courses.py --all      # all configured semesters (Week 2)
    uv run python scripts/scrape_courses.py --semester F25
"""

import argparse
import json

from latent_campus.common import config
from latent_campus.common.config import RAW_DIR
from latent_campus.ingest.soc_fetch import fetch_semester
from latent_campus.ingest.soc_parse import parse_complete_schedule

JSON_DIR = RAW_DIR / "courses" / "json"


def scrape_one(semester: str) -> dict[str, str]:
    result = fetch_semester(semester)
    html = result.content_path.read_text(encoding="iso-8859-1", errors="replace")
    offerings, dept_names = parse_complete_schedule(html, semester)
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    out = JSON_DIR / f"offerings_{semester}.json"
    out.write_text(json.dumps([o.model_dump() for o in offerings], indent=1))
    cache_note = " (cache)" if result.from_cache else ""
    print(f"{semester}: {len(offerings)} offerings, {len(dept_names)} depts{cache_note} -> {out}")
    return dept_names


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--semester", help="single semester code, e.g. S26")
    ap.add_argument("--all", action="store_true", help="all semesters in configs/semesters.yaml")
    args = ap.parse_args()

    if args.semester:
        semesters = [args.semester]
    elif args.all:
        semesters = config.semesters()
    else:
        semesters = config.semesters()[:1]  # Week 1: most recent only

    dept_names: dict[str, str] = {}
    for s in semesters:
        dept_names.update(scrape_one(s))

    # free seed for the department alias dictionary
    seed = JSON_DIR / "dept_names_seed.json"
    if seed.exists():
        dept_names = {**json.loads(seed.read_text()), **dept_names}
    seed.write_text(json.dumps(dict(sorted(dept_names.items())), indent=1))
    print(f"dept name seed: {len(dept_names)} codes -> {seed}")


if __name__ == "__main__":
    main()
