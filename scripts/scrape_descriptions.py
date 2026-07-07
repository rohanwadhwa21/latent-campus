"""Fetch course-catalog pages and parse them into a description table.

  catalog /courses/ pages -> data/canonical/catalog_descriptions.parquet
    (course_id, title, description, offered_terms, units_text)

Deduped by course_id (college-level pages overlap department pages). The
enrich step (build_canonical.py) joins this onto courses.parquet.
"""

import polars as pl

from latent_campus.common.config import DATA_DIR
from latent_campus.ingest.catalog_fetch import fetch_all_catalog_pages
from latent_campus.ingest.catalog_parse import parse_catalog_page

CANONICAL_DIR = DATA_DIR / "canonical"


def main() -> None:
    results = fetch_all_catalog_pages()
    rows: dict[str, dict] = {}
    for result in results:
        html = result.content_path.read_text(encoding="utf-8", errors="replace")
        entries = parse_catalog_page(html)
        for e in entries:
            # first occurrence wins; prefer the longest description on conflict
            prev = rows.get(e.course_id)
            if prev is None or len(e.description) > len(prev["description"]):
                rows[e.course_id] = e.model_dump()
        cache = " (cache)" if result.from_cache else ""
        print(f"  {result.url.rsplit('/courses', 1)[0].split('/')[-1] or '?'}: "
              f"{len(entries)} entries{cache}")

    table = pl.from_dicts(list(rows.values())).sort("course_id")
    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    out = CANONICAL_DIR / "catalog_descriptions.parquet"
    table.write_parquet(out)
    print(f"{len(table)} unique course descriptions -> {out}")


if __name__ == "__main__":
    main()
