"""Resolve instructor surnames to directory people -> faculty + edge tables.

Consumes the bulk-fetch output (directory_candidates.parquet) plus the F23-S25
offerings, resolves every (surname, offering-dept) pair via
latent_campus.resolve.faculty, and writes:

  data/canonical/faculty.parquet          resolved people (node exists ONLY on
                                          a confident directory match)
  data/canonical/course_faculty.parquet   offering -> faculty TEACHES edges,
                                          each carrying its evidence
  data/canonical/faculty_ambiguous.csv    manual-review queue (ambiguous+capped)

Modes:
  --report-unmapped   list HR dept names absent from dept_directory_map.yaml,
                      by frequency (the seeding step for hand-mapping)
  --sample-labels N   sample N resolved pairs to a labeling CSV for the
                      precision check (~99% target before accepting the run)

Leakage rule (locked): faculty attributes come from the directory only;
course text is never read here.
"""

import argparse
from collections import Counter

import polars as pl

from latent_campus.common.config import DATA_DIR, load_config
from latent_campus.common.schemas import CourseFacultyEdge, Faculty
from latent_campus.ingest.soc_parse import parse_room
from latent_campus.resolve.faculty import Candidate, attach_dept_codes, resolve_pair

CANONICAL_DIR = DATA_DIR / "canonical"
USABLE_SEMESTERS = ["F23", "S24", "F24", "S25"]


def load_candidate_pools() -> tuple[dict[str, list[Candidate]], set[str], set[str]]:
    """directory_candidates.parquet -> ({surname: [Candidate...]}, capped, queried).

    Keys are CASEFOLDED: SOC tokens have case variants ("AAZAM"/"Aazam") that
    are the same person; directory search is case-insensitive anyway. People
    reached via two case variants are deduped by andrew_id per pool.
    """
    df = pl.read_parquet(CANONICAL_DIR / "directory_candidates.parquet")
    dept_map = load_config("dept_directory_map") or {}
    pools: dict[str, list[Candidate]] = {}
    seen: set[tuple[str, str]] = set()
    for row in df.iter_rows(named=True):
        key = row["query_surname"].casefold()
        if (key, row["andrew_id"]) in seen:
            continue
        seen.add((key, row["andrew_id"]))
        pools.setdefault(key, []).append(
            Candidate(
                andrew_id=row["andrew_id"],
                display_name=row["display_name"],
                affiliation=row["affiliation"],
                job_titles=row["job_titles"] or [],
                departments=row["departments"] or [],
                campus_room=row["campus_room"],
            )
        )
    pools = {s: attach_dept_codes(cands, dept_map) for s, cands in pools.items()}
    queries = pl.read_parquet(CANONICAL_DIR / "directory_queries.parquet")
    capped = {s.casefold() for s in queries.filter(pl.col("capped")).get_column("surname")}
    queried = {s.casefold() for s in queries.get_column("surname")}
    return pools, capped, queried


def instructor_tokens() -> pl.DataFrame:
    """F23-S25 offerings exploded to one row per (offering, surname token)."""
    offerings = pl.read_parquet(CANONICAL_DIR / "course_offerings.parquet")
    return (
        offerings.filter(pl.col("semester").is_in(USABLE_SEMESTERS))
        .select(
            "offering_id", "course_id", "semester",
            pl.col("course_id").str.slice(0, 2).alias("dept_code"),
            pl.col("instructor_names_raw").alias("surname"),
        )
        .explode("surname")
        .drop_nulls("surname")
        .with_columns(pl.col("surname").str.strip_chars())
        .filter(pl.col("surname") != "")
    )


def report_unmapped(pools: dict[str, list[Candidate]]) -> None:
    dept_map = load_config("dept_directory_map") or {}
    counts: Counter[str] = Counter()
    for cands in pools.values():
        for c in cands:
            counts.update(n for n in c.departments if n not in dept_map)
    print(f"{len(counts)} unmapped HR department names (add to dept_directory_map.yaml):")
    for name, n in counts.most_common():
        print(f'  "{name}": null   # seen {n}x')


def _room_building(campus_room: str | None) -> str | None:
    """Directory rooms are mixed-case ('Cic 3225'); SOC codes are upper."""
    if not campus_room:
        return None
    head, _, rest = campus_room.strip().partition(" ")
    code, _ = parse_room(f"{head.upper()} {rest}".strip())
    return code


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report-unmapped", action="store_true")
    ap.add_argument("--sample-labels", type=int, default=None, metavar="N")
    args = ap.parse_args()

    pools, capped, queried = load_candidate_pools()
    if args.report_unmapped:
        report_unmapped(pools)
        return

    tokens = instructor_tokens()
    pairs = tokens.select("surname", "dept_code").unique()
    print(f"{len(tokens)} instructor tokens -> {len(pairs)} (surname, dept) pairs")

    unqueried = {s.casefold() for s in pairs.get_column("surname")} - queried
    if unqueried:
        raise SystemExit(
            f"{len(unqueried)} surnames never queried against the directory "
            f"(run `make scrape-directory` to completion first); e.g. {sorted(unqueried)[:5]}"
        )

    resolutions = [
        resolve_pair(s, d, pools.get(s.casefold(), []), capped=s.casefold() in capped)
        for s, d in pairs.iter_rows()
    ]
    res_df = pl.from_dicts([r.model_dump() for r in resolutions])
    by_status = dict(res_df.group_by("status").len().iter_rows())
    by_method = dict(
        res_df.filter(pl.col("status") == "resolved").group_by("method").len().iter_rows()
    )
    print(f"pair status: {by_status}")
    print(f"resolved methods: {by_method}")

    # --- edges: every token whose (surname, dept) pair resolved ---
    resolved = res_df.filter(pl.col("status") == "resolved").select(
        "surname", "dept_code", "andrew_id", "method"
    )
    edges = tokens.join(resolved, on=["surname", "dept_code"], how="inner")
    edge_models = [
        CourseFacultyEdge(
            offering_id=r["offering_id"], course_id=r["course_id"], semester=r["semester"],
            faculty_id=r["andrew_id"], surname_token=r["surname"],
            dept_code=r["dept_code"], match_method=r["method"],
        )
        for r in edges.iter_rows(named=True)
    ]
    edges_out = pl.from_dicts([e.model_dump() for e in edge_models])
    edges_path = CANONICAL_DIR / "course_faculty.parquet"
    edges_out.write_parquet(edges_path)
    print(f"{len(edges_out)} TEACHES edges ({edges_out['faculty_id'].n_unique()} people, "
          f"{len(tokens)} tokens, {len(edges_out)/len(tokens):.1%} token coverage) -> {edges_path}")

    # --- faculty nodes: distinct resolved people ---
    resolved_ids = set(edges_out.get_column("faculty_id").to_list())
    people: dict[str, Faculty] = {}
    for cands in pools.values():
        for c in cands:
            if c.andrew_id in resolved_ids and c.andrew_id not in people:
                people[c.andrew_id] = Faculty(
                    faculty_id=c.andrew_id, display_name=c.display_name,
                    affiliation=c.affiliation, job_titles=c.job_titles,
                    hr_departments=c.departments, dept_codes=sorted(c.dept_codes),
                    campus_room=c.campus_room,
                    building_code=_room_building(c.campus_room),
                )
    fac_out = pl.from_dicts([p.model_dump() for p in people.values()])
    fac_path = CANONICAL_DIR / "faculty.parquet"
    fac_out.write_parquet(fac_path)
    print(f"{len(fac_out)} faculty nodes -> {fac_path}")

    # --- manual queue: ambiguous + capped pairs, with their candidate pools ---
    queue_rows = [
        {
            "surname": r.surname, "dept_code": r.dept_code, "status": r.status,
            "n_candidates": r.n_candidates,
            "candidates": "; ".join(
                f"{c.andrew_id} ({c.display_name}: {', '.join(c.departments)})"
                for c in pools.get(r.surname.casefold(), [])
            ),
        }
        for r in resolutions if r.status in ("ambiguous", "capped")
    ]
    queue_path = CANONICAL_DIR / "faculty_ambiguous.csv"
    pl.from_dicts(queue_rows).write_csv(queue_path) if queue_rows else None
    print(f"{len(queue_rows)} pairs to manual queue -> {queue_path}")

    # --- per-dept resolution-rate report ---
    rate = (
        tokens.join(resolved, on=["surname", "dept_code"], how="left")
        .group_by("dept_code")
        .agg(pl.len().alias("tokens"), pl.col("andrew_id").is_not_null().mean().alias("rate"))
        .sort("rate")
    )
    print("\nlowest per-dept token resolution rates:")
    print(rate.head(10))

    if args.sample_labels:
        sample = (
            edges_out.select("surname_token", "dept_code", "faculty_id", "match_method")
            .unique()
            .sample(min(args.sample_labels, len(edges_out)), seed=42)
            .with_columns(pl.lit("").alias("verdict_correct_yn"))
        )
        labels_path = CANONICAL_DIR / "faculty_label_sample.csv"
        sample.write_csv(labels_path)
        print(f"\n{len(sample)} pairs to hand-label -> {labels_path}")


if __name__ == "__main__":
    main()
