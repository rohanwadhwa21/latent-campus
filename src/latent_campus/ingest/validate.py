"""Week 1 validation report over canonical parquet files.

Emits a markdown report answering: did the parse produce sane data?
Run via `make validate` after `make build-canonical`.
"""

from pathlib import Path

import polars as pl

MIN_DESCRIPTION_CHARS = 200  # below this, text embeds near-randomly (DES/LIS hygiene)


def validation_report(courses_path: Path, offerings_path: Path) -> str:
    courses = pl.read_parquet(courses_path)
    offerings = pl.read_parquet(offerings_path)

    lines = ["# Validation report", ""]

    def section(title: str) -> None:
        lines.extend(["", f"## {title}", ""])

    section("Row counts")
    lines.append(f"- unique courses: {len(courses)}")
    lines.append(f"- offerings: {len(offerings)}")
    lines.append(f"- semesters: {sorted(offerings['semester'].unique().to_list())}")

    section("Courses per department (top 20)")
    per_dept = (
        courses.group_by("dept_code").len().sort("len", descending=True).head(20)
    )
    for row in per_dept.iter_rows(named=True):
        lines.append(f"- {row['dept_code']}: {row['len']}")

    section("Description coverage")
    n = len(courses)
    missing = courses.filter(pl.col("description").is_null()).height
    short = courses.filter(
        pl.col("description").is_not_null()
        & (pl.col("description").str.len_chars() < MIN_DESCRIPTION_CHARS)
    ).height
    lines.append(f"- missing description: {missing}/{n} ({missing / max(n, 1):.1%})")
    lines.append(f"- short (<{MIN_DESCRIPTION_CHARS} chars): {short}/{n}")
    lines.append(f"- generic numbers (x97/x98/x99): {courses.filter(pl.col('is_generic')).height}")

    section("Duplicate IDs")
    dup_courses = courses.group_by("course_id").len().filter(pl.col("len") > 1)
    dup_offerings = offerings.group_by("offering_id").len().filter(pl.col("len") > 1)
    lines.append(f"- duplicate course_ids: {dup_courses.height}")
    lines.append(f"- duplicate offering_ids: {dup_offerings.height}")
    for row in dup_offerings.head(10).iter_rows(named=True):
        lines.append(f"  - {row['offering_id']} x{row['len']}")

    section("Units")
    var_units = offerings.filter(
        pl.col("units_raw").is_not_null()
        & ~pl.col("units_raw").str.contains(r"^\d+(\.\d+)?$")
    ).height
    lines.append(f"- offerings with non-numeric units (VAR etc.): {var_units}/{len(offerings)}")

    section("Instructor coverage by semester")
    lines.append("(F25/S26 have none by design — CMU removed the column from the public SOC)")
    cov = (
        offerings.group_by("semester")
        .agg(
            pl.len().alias("n"),
            (pl.col("instructor_names_raw").list.len() > 0).sum().alias("with_instr"),
        )
        .sort("semester")
    )
    for row in cov.iter_rows(named=True):
        pct = row["with_instr"] / max(row["n"], 1)
        lines.append(f"- {row['semester']}: {row['with_instr']}/{row['n']} ({pct:.0%})")

    section("Campus split")
    campus = (
        offerings.explode("meetings")
        .select(pl.col("meetings").struct.field("campus"))
        .group_by("campus")
        .len()
        .sort("len", descending=True)
    )
    for row in campus.iter_rows(named=True):
        lines.append(f"- {row['campus']}: {row['len']} meetings")

    section("Mini-semester offerings")
    lines.append(f"- mini offerings: {offerings.filter(pl.col('mini').is_not_null()).height}")

    return "\n".join(lines) + "\n"
