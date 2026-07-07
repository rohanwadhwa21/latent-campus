"""Build canonical parquet files from parsed offerings JSON.

  data/raw/courses/json/offerings_*.json
    -> data/canonical/course_offerings.parquet
    -> data/canonical/courses.parquet   (one row per unique course;
       most-recent title/units win; descriptions joined from
       catalog_descriptions.parquet when present — rly un scrape_descriptions.py)
"""

import json

import polars as pl

from latent_campus.common.config import DATA_DIR
from latent_campus.common.config import RAW_DIR as RAW_BASE
from latent_campus.common.schemas import GENERIC_NUMBER_RE

CANONICAL_DIR = DATA_DIR / "canonical"
RAW_DIR = RAW_BASE / "courses"


def semester_sort_key(code: str) -> tuple[int, int]:
    """Chronological key: F23 < S24 < F24 < S25 ... (Spring precedes Fall in a year)."""
    season, year = code[0], int(code[1:])
    return year, {"S": 0, "F": 1}[season]


def main() -> None:
    json_dir = RAW_DIR / "json"
    files = sorted(json_dir.glob("offerings_*.json"))
    if not files:
        raise SystemExit(f"no offerings JSON in {json_dir}; run scrape_courses.py first")

    rows = []
    for f in files:
        rows.extend(json.loads(f.read_text()))
    offerings = pl.from_dicts(rows)

    # SOC sometimes lists one (course, semester, section) twice — different
    # campuses sharing a section letter, or a second row carrying another
    # instructor. Merge: union instructors, concat meetings (each meeting
    # keeps its own campus).
    before = len(offerings)
    offerings = (
        offerings.group_by("offering_id", maintain_order=True)
        .agg(
            pl.col("course_id").first(),
            pl.col("semester").first(),
            pl.col("section").first(),
            pl.col("title").first(),
            pl.col("instructor_names_raw")
            .list.explode(keep_nulls=False, empty_as_null=False)
            .drop_nulls()
            .unique(maintain_order=True),
            pl.col("instructor_ids").first(),
            pl.col("mini").first(),
            pl.col("units_raw").first(),
            pl.col("meetings").list.explode(keep_nulls=False, empty_as_null=False).drop_nulls(),
        )
    )
    if before != len(offerings):
        print(f"merged {before - len(offerings)} duplicate offering rows")

    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    offerings.write_parquet(CANONICAL_DIR / "course_offerings.parquet")

    # Unique courses: most recent semester's title/units win.
    sem_order = {
        s: i
        for i, s in enumerate(
            sorted(offerings["semester"].unique().to_list(), key=semester_sort_key)
        )
    }
    courses = (
        offerings.with_columns(
            pl.col("semester").replace_strict(sem_order).alias("_sem_rank")
        )
        .sort("_sem_rank")
        .group_by("course_id")
        .agg(
            pl.col("title").last(),
            pl.col("units_raw").last(),
            pl.col("semester").first().alias("first_seen_semester"),
            pl.col("semester").last().alias("last_seen_semester"),
        )
        .with_columns(
            pl.col("course_id").str.slice(0, 2).alias("dept_code"),
            pl.col("course_id").str.slice(3).alias("course_number"),
            pl.col("units_raw").cast(pl.Float64, strict=False).alias("units"),
            pl.col("course_id").str.contains(GENERIC_NUMBER_RE.pattern).alias("is_generic"),
            pl.lit(None, dtype=pl.Utf8).alias("description"),
            pl.lit("none").alias("description_source"),
            pl.lit([], dtype=pl.List(pl.Utf8)).alias("cross_listed_ids"),
        )
        .drop("units_raw")
        .sort("course_id")
    )

    courses = enrich_descriptions(courses)
    courses.write_parquet(CANONICAL_DIR / "courses.parquet")
    print(f"{len(offerings)} offerings, {len(courses)} unique courses -> {CANONICAL_DIR}")


def enrich_descriptions(courses: pl.DataFrame) -> pl.DataFrame:
    """Fill descriptions from two sources, catalog first then SOC courseDetails.

    catalog_descriptions.parquet covers undergrad-oriented departments;
    soc_descriptions.parquet fills graduate/professional gaps (Heinz, etc.)
    and contributes cross-listing info. description_source records the winner.
    """
    courses = courses.drop("description", "description_source")

    cat_path = CANONICAL_DIR / "catalog_descriptions.parquet"
    cat = (
        pl.read_parquet(cat_path).select("course_id", pl.col("description").alias("_cat"))
        if cat_path.exists()
        else pl.DataFrame(schema={"course_id": pl.Utf8, "_cat": pl.Utf8})
    )

    soc_path = CANONICAL_DIR / "soc_descriptions.parquet"
    soc = (
        pl.read_parquet(soc_path).select(
            "course_id",
            pl.col("description").alias("_soc"),
            pl.col("cross_listed_ids").alias("_soc_xlist"),
        )
        if soc_path.exists()
        else pl.DataFrame(
            schema={"course_id": pl.Utf8, "_soc": pl.Utf8, "_soc_xlist": pl.List(pl.Utf8)}
        )
    )

    courses = (
        courses.join(cat, on="course_id", how="left")
        .join(soc, on="course_id", how="left")
        .with_columns(
            pl.coalesce("_cat", "_soc").alias("description"),
            pl.when(pl.col("_cat").is_not_null())
            .then(pl.lit("catalog"))
            .when(pl.col("_soc").is_not_null())
            .then(pl.lit("soc"))
            .otherwise(pl.lit("none"))
            .alias("description_source"),
            # adopt SOC cross-listings where we found them
            pl.coalesce(pl.col("_soc_xlist"), pl.col("cross_listed_ids")).alias(
                "cross_listed_ids"
            ),
        )
        .drop("_cat", "_soc", "_soc_xlist")
    )

    n = len(courses)
    by_src = dict(
        courses.group_by("description_source").len().iter_rows()
    )
    have = n - by_src.get("none", 0)
    print(f"  descriptions: {have}/{n} ({have / max(n, 1):.0%}) "
          f"[catalog={by_src.get('catalog', 0)}, soc={by_src.get('soc', 0)}, "
          f"none={by_src.get('none', 0)}]")
    return courses


if __name__ == "__main__":
    main()
