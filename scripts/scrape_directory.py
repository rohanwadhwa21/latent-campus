"""Query the CMU directory for every instructor surname (Week 4 faculty ER).

Instructor strings in the SOC are last names only, and anonymous directory
search is name-only — so we run one advanced search (last_name=<surname>,
whole-word match) per distinct surname seen in F23-S25 offerings (F25/S26
have no instructor data), then fetch the guid detail page for every hit whose
affiliation is Faculty or Staff. Detail pages are the authoritative source
for departments/title (line-separated, no comma-split ambiguity).

Cap handling: results are hard-capped at 200. A capped surname's hit list is
TRUNCATED, so it can never prove uniqueness — those surnames are flagged and
excluded from automatic resolution (manual queue instead).

Acceptable use: we store only name, andrew_id, affiliation, HR job title,
departments, campus room — never email or phone.

Resilient + incremental: one JSONL record per surname appended immediately
(resume log lives with the raw cache, outside iCloud). Rerun = no-op.

  -> data/canonical/directory_candidates.parquet  (one row per candidate person-query)
  -> data/canonical/directory_capped_surnames.csv (manual-queue input)
"""

import argparse
import json

import polars as pl

from latent_campus.common.config import DATA_DIR, RAW_DIR, load_config
from latent_campus.common.fetch import PoliteFetcher
from latent_campus.ingest.directory_parse import DirectoryPerson, parse_search_results

CANONICAL_DIR = DATA_DIR / "canonical"
JSONL = RAW_DIR / "directory" / "directory_people.jsonl"
USABLE_SEMESTERS = ["F23", "S24", "F24", "S25"]  # F25/S26 have no instructors
CANDIDATE_AFFILIATIONS = ("Faculty", "Staff")


def surname_table() -> pl.DataFrame:
    """Distinct instructor surnames with offering counts and dept context."""
    offerings = pl.read_parquet(CANONICAL_DIR / "course_offerings.parquet")
    return (
        offerings.filter(pl.col("semester").is_in(USABLE_SEMESTERS))
        .select(
            pl.col("instructor_names_raw").alias("surname"),
            pl.col("course_id").str.slice(0, 2).alias("dept"),
        )
        .explode("surname")
        .drop_nulls("surname")
        .with_columns(pl.col("surname").str.strip_chars())
        .filter(pl.col("surname") != "")
        .group_by("surname")
        .agg(pl.len().alias("n_offerings"), pl.col("dept").unique().sort().alias("depts"))
        .sort("n_offerings", descending=True)
    )


def search_form(surname: str) -> dict[str, str]:
    """The full advanced-search form, as a browser would post it."""
    return {
        "first_name": "",
        "last_name": surname,
        "andrew_id": "",
        "email": "",
        "action": "Search",
        "searchtype": "advanced",
        "activetab": "advanced",
    }


def _read_html(result, fetcher, url, *, params=None, data=None) -> str:
    """Read cached HTML; on an evicted/unreadable file, re-fetch fresh."""
    try:
        return result.content_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        result = fetcher.fetch(url, params=params, data=data, force=True)
        return result.content_path.read_text(encoding="utf-8", errors="replace")


def _is_candidate(affiliation: str | None) -> bool:
    return bool(affiliation) and any(a in affiliation for a in CANDIDATE_AFFILIATIONS)


def _person_dict(person: DirectoryPerson, guid: str | None) -> dict:
    return {**person.model_dump(), "guid": guid}


def fetch_surname(fetcher: PoliteFetcher, url: str, surname: str) -> dict:
    """One surname -> search page -> candidate detail pages -> JSONL record."""
    data = search_form(surname)
    result = fetcher.fetch(url, data=data)
    page = parse_search_results(_read_html(result, fetcher, url, data=data))

    people: list[dict] = []
    if page.kind == "single" and page.person and _is_candidate(page.person.affiliation):
        people.append(_person_dict(page.person, guid=None))
    for hit in page.hits:
        if not _is_candidate(hit.affiliation):
            continue
        params = {"searchtype": "guid", "guid": hit.guid, "activetab": "advanced"}
        detail = fetcher.fetch(url, params=params)
        person = parse_search_results(
            _read_html(detail, fetcher, url, params=params)
        ).person
        if person is not None:
            people.append(_person_dict(person, guid=hit.guid))

    return {"surname": surname, "kind": page.kind, "capped": page.capped, "people": people}


def rebuild_outputs() -> None:
    """JSONL -> candidates parquet + query-log parquet + capped-surname csv."""
    records = [json.loads(line) for line in JSONL.read_text().splitlines() if line.strip()]

    # Query log: lets the resolver distinguish "queried, no candidates"
    # (a real no-match) from "never queried" (a pipeline error).
    queries = pl.from_dicts(
        [
            {"surname": r["surname"], "kind": r["kind"], "capped": r["capped"],
             "n_people": len(r["people"])}
            for r in records
        ],
        schema={"surname": pl.Utf8, "kind": pl.Utf8, "capped": pl.Boolean, "n_people": pl.Int64},
    ).unique(subset="surname", keep="last")
    queries_path = CANONICAL_DIR / "directory_queries.parquet"
    queries.write_parquet(queries_path)

    capped = pl.DataFrame({"surname": [r["surname"] for r in records if r["capped"]]})
    capped_csv = CANONICAL_DIR / "directory_capped_surnames.csv"
    capped.write_csv(capped_csv)

    rows = [
        {
            "query_surname": r["surname"],
            "query_capped": r["capped"],
            "andrew_id": p["andrew_id"],
            "display_name": p["display_name"],
            "affiliation": p["affiliation"],
            "job_titles": p["job_titles"],
            "departments": p["departments"],
            "campus_room": p["campus_room"],
            "guid": p["guid"],
        }
        for r in records
        for p in r["people"]
    ]
    schema = {
        "query_surname": pl.Utf8, "query_capped": pl.Boolean, "andrew_id": pl.Utf8,
        "display_name": pl.Utf8, "affiliation": pl.Utf8, "job_titles": pl.List(pl.Utf8),
        "departments": pl.List(pl.Utf8), "campus_room": pl.Utf8, "guid": pl.Utf8,
    }
    table = pl.from_dicts(rows, schema=schema) if rows else pl.DataFrame(schema=schema)
    table = table.unique(subset=["query_surname", "andrew_id"], keep="last")
    out = CANONICAL_DIR / "directory_candidates.parquet"
    table.write_parquet(out)

    n_people = table.get_column("andrew_id").n_unique() if len(table) else 0
    kinds = pl.DataFrame({"kind": [r["kind"] for r in records]}).group_by("kind").len()
    print(f"\n{len(records)} surnames queried: {dict(kinds.iter_rows())}")
    print(f"{len(capped)} capped surnames -> {capped_csv}")
    print(f"{len(table)} candidate rows ({n_people} distinct people) -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="only the N most frequent surnames")
    ap.add_argument("--rebuild-only", action="store_true",
                    help="no fetching; rebuild the parquet/csv outputs from the JSONL log")
    args = ap.parse_args()

    if args.rebuild_only:
        rebuild_outputs()
        return

    surnames = surname_table()
    per_dept = surnames.explode("depts").group_by("depts").len().sort("len", descending=True)
    print(f"{len(surnames)} distinct surnames across {USABLE_SEMESTERS}")
    print("distinct surnames per dept (top 10):", dict(per_dept.head(10).iter_rows()))
    if args.limit:
        surnames = surnames.head(args.limit)

    done: set[str] = set()
    if JSONL.exists():
        with JSONL.open() as f:
            done = {json.loads(line)["surname"] for line in f if line.strip()}
    todo = surnames.filter(~pl.col("surname").is_in(done))
    print(f"{len(done)} surnames already done; {len(todo)} to fetch")

    src = load_config("sources")["directory"]
    url = src["base_url"] + src["search_endpoint"]
    fetcher = PoliteFetcher("directory")
    JSONL.parent.mkdir(parents=True, exist_ok=True)
    n_people = 0
    with JSONL.open("a") as out:
        for i, surname in enumerate(todo.get_column("surname"), 1):
            rec = fetch_surname(fetcher, url, surname)
            out.write(json.dumps(rec) + "\n")
            out.flush()
            n_people += len(rec["people"])
            if i % 100 == 0:
                print(f"  {i}/{len(todo)} surnames, {n_people} candidate records", flush=True)
    fetcher.close()

    rebuild_outputs()


if __name__ == "__main__":
    main()
