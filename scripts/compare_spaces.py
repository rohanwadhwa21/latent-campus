"""Cross-space replication check — the Phase-1 closer.

The interdisciplinarity finding was first measured in ONE embedding space (bge). A single
model can have idiosyncrasies, so a ranking there might be a fact about the MODEL, not
about CMU. This script re-reads the size-controlled department rankings produced by
`interdisciplinarity.py` for every embedding space and asks the pre-committed question:

  Does the finding REPLICATE across independent encoders?

Two lenses:
  1. Pairwise Spearman between spaces' des_resid vectors (aligned by dept) — do the models
     AGREE on the overall ordering? High rho = the ranking is model-robust.
  2. Per-department replication: a dept "replicates" if it lands in the top-20 by des_resid
     in >= REPLICATE_MIN of the spaces (the locked >=3-of-4 protocol).

  data/metrics/<slug>/interdisciplinarity_departments.parquet  (one per space)
    -> data/metrics/replication_report.md

Usage:
  PYTHONPATH=src ~/latent-campus-venv/bin/python scripts/compare_spaces.py
"""
import argparse
from itertools import combinations

import numpy as np
import polars as pl
from scipy.stats import spearmanr

from latent_campus.common.config import DATA_DIR

DEFAULT_SLUGS = [
    "bge-large-en-v1.5",
    "all-mpnet-base-v2",
    "all-MiniLM-L6-v2",
    "e5-large-v2",
]
TOP_N = 20            # "interdisciplinary" = top-20 by des_resid in a space
REPLICATE_MIN = 3    # dept replicates if top-20 in >= this many spaces (locked >=3 of 4)


def load_space(slug: str) -> pl.DataFrame:
    """Load one space's ranked department table (dept_code, des_resid, lis_resid, ...)."""
    path = DATA_DIR / "metrics" / slug / "interdisciplinarity_departments.parquet"
    if not path.exists():
        raise SystemExit(f"missing {path}; run interdisciplinarity.py --model-slug {slug}")
    return pl.read_parquet(path).select("dept_code", "n_courses", "des_resid", "lis_resid")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slugs", nargs="+", default=DEFAULT_SLUGS)
    args = ap.parse_args()

    spaces = {slug: load_space(slug) for slug in args.slugs}

    # Align on the departments present in EVERY space (same corpus+hygiene -> should be all,
    # but intersect defensively so the Spearman vectors line up row-for-row).
    common = set.intersection(*(set(df["dept_code"].to_list()) for df in spaces.values()))
    common = sorted(common)
    print(f"{len(spaces)} spaces, {len(common)} departments common to all\n")

    # des_resid vector per space, indexed identically by `common`.
    resid = {}
    for slug, df in spaces.items():
        m = dict(zip(df["dept_code"].to_list(), df["des_resid"].to_list(), strict=True))
        resid[slug] = np.array([m[d] for d in common])

    # ---- lens 1: pairwise Spearman on des_resid (do the models agree on ordering?) ----
    print("Pairwise Spearman(des_resid) between spaces:")
    rhos = []
    for a, b in combinations(args.slugs, 2):
        rho = spearmanr(resid[a], resid[b]).correlation
        rhos.append(rho)
        print(f"  {rho:+.2f}  {a}  vs  {b}")
    print(f"  mean pairwise rho = {np.mean(rhos):+.2f}\n")

    # ---- lens 2: per-department top-20 replication count ----
    top_sets = {
        slug: set(
            df.sort("des_resid", descending=True).head(TOP_N)["dept_code"].to_list()
        )
        for slug, df in spaces.items()
    }
    rows = []
    for d in common:
        in_spaces = [slug for slug in args.slugs if d in top_sets[slug]]
        rows.append((d, len(in_spaces), in_spaces))
    rows.sort(key=lambda r: (-r[1], r[0]))

    replicated = [r for r in rows if r[1] >= REPLICATE_MIN]
    print(f"Departments top-{TOP_N} in >= {REPLICATE_MIN} of {len(spaces)} spaces "
          f"(REPLICATED): {len(replicated)}")
    # mean rank across spaces, for a stable headline ordering among the replicators
    mean_resid = {d: float(np.mean([resid[s][common.index(d)] for s in args.slugs]))
                  for d, _, _ in replicated}
    for d, cnt, in_spaces in sorted(replicated, key=lambda r: -mean_resid[r[0]]):
        tags = ",".join(s.split("-")[0] for s in in_spaces)
        print(f"  {d}: {cnt}/{len(spaces)}  (mean des_resid {mean_resid[d]:+.3f})  [{tags}]")

    # ---- persist a report ----
    lines = [
        "# Cross-space replication of the interdisciplinarity finding\n",
        f"Spaces: {', '.join(args.slugs)}",
        f"Protocol: dept replicates if top-{TOP_N} by des_resid in >= {REPLICATE_MIN} "
        f"of {len(spaces)} spaces.\n",
        "## Pairwise Spearman(des_resid)\n",
        "| space A | space B | rho |", "|---|---|---|",
    ]
    for (a, b), rho in zip(combinations(args.slugs, 2), rhos, strict=True):
        lines.append(f"| {a} | {b} | {rho:+.2f} |")
    lines += [f"\nmean pairwise rho = **{np.mean(rhos):+.2f}**\n",
              f"## Replicated departments ({len(replicated)})\n",
              "| dept | spaces (of 4) | mean des_resid |", "|---|---|---|"]
    for d, cnt, _ in sorted(replicated, key=lambda r: -mean_resid[r[0]]):
        lines.append(f"| {d} | {cnt} | {mean_resid[d]:+.3f} |")
    out = DATA_DIR / "metrics" / "replication_report.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"\nwrote -> {out}")


if __name__ == "__main__":
    main()
