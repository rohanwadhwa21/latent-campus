"""Fill description gaps from the SOC courseDetails endpoint.

The course catalog misses graduate/professional courses (Heinz 90-95, etc.).
This fetches courseDetails for every course that (a) still lacks a catalog
description and (b) was last offered in a live semester (S26/F25), which the
endpoint requires.

Resilient + incremental: each parsed result is appended to soc_descriptions.jsonl
immediately, so a crash (or iCloud cache eviction — this repo lives in a synced
~/Desktop) never loses progress. On resume, already-done course_ids are skipped.
If a cached HTML file is unreadable (evicted to an iCloud placeholder that times
out), we force a fresh curl re-fetch instead of crashing.

  -> data/canonical/soc_descriptions.jsonl   (incremental, source of truth)
  -> data/canonical/soc_descriptions.parquet (rebuilt at end from the jsonl)
"""

import json

import polars as pl

from latent_campus.common.config import DATA_DIR, RAW_DIR
from latent_campus.common.fetch import PoliteFetcher
from latent_campus.ingest.details_parse import parse_course_details
from latent_campus.ingest.soc_fetch import course_details_url

CANONICAL_DIR = DATA_DIR / "canonical"
# Incremental resume log is scratch/working state; keep it with the external raw
# cache (outside iCloud) so disk-pressure eviction can't time out reads of it.
# The rebuilt parquet below is the canonical output and stays in-repo.
JSONL = RAW_DIR / "details" / "soc_descriptions.jsonl"
LIVE_SEMESTERS = {"S26", "F25"}  # courseDetails only accepts live semester codes


def _read_html(result, fetcher, url, params) -> str:
    """Read cached HTML; on an iCloud-evicted/unreadable file, re-fetch fresh."""
    try:
        return result.content_path.read_text(encoding="iso-8859-1", errors="replace")
    except OSError:
        result = fetcher.fetch(url, params, force=True)
        return result.content_path.read_text(encoding="iso-8859-1", errors="replace")


def main() -> None:
    courses = pl.read_parquet(CANONICAL_DIR / "courses.parquet")
    gaps = courses.filter(
        pl.col("description").is_null() & pl.col("last_seen_semester").is_in(LIVE_SEMESTERS)
    ).select("course_id", "last_seen_semester")

    done: set[str] = set()
    if JSONL.exists():
        with JSONL.open() as f:
            done = {json.loads(line)["course_id"] for line in f if line.strip()}
    todo = gaps.filter(~pl.col("course_id").is_in(done))
    print(f"{len(gaps)} gap courses; {len(done)} already done; {len(todo)} to fetch")

    url = course_details_url()
    fetcher = PoliteFetcher("details")
    n_desc = 0
    with JSONL.open("a") as out:
        for i, row in enumerate(todo.iter_rows(named=True), 1):
            cid, sem = row["course_id"], row["last_seen_semester"]
            params = {"COURSE": cid.replace("-", ""), "SEMESTER": sem}
            result = fetcher.fetch(url, params)
            html = _read_html(result, fetcher, url, params)
            entry = parse_course_details(html, cid)
            # always record an attempt (None desc -> skip-on-resume) keyed by course_id
            rec = entry.model_dump() if entry else {"course_id": cid, "description": None}
            out.write(json.dumps(rec) + "\n")
            out.flush()
            if entry:
                n_desc += 1
            if i % 200 == 0:
                print(f"  {i}/{len(todo)} fetched, {n_desc} new descriptions", flush=True)
    fetcher.close()

    # Rebuild parquet from the jsonl (only rows that actually have a description).
    rows = [
        json.loads(line)
        for line in JSONL.read_text().splitlines()
        if line.strip() and json.loads(line).get("description")
    ]
    table = pl.from_dicts(rows) if rows else pl.DataFrame(
        schema={"course_id": pl.Utf8, "description": pl.Utf8,
                "cross_listed_ids": pl.List(pl.Utf8), "prerequisites": pl.Utf8}
    )
    table = table.unique(subset="course_id", keep="last")
    out_pq = CANONICAL_DIR / "soc_descriptions.parquet"
    table.write_parquet(out_pq)
    print(f"{len(table)} courses with SOC descriptions -> {out_pq}")


if __name__ == "__main__":
    main()
