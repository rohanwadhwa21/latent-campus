"""Interdisciplinarity metrics on the course-text space (Phase 1 closer).

  data/embeddings/<model>/embeddings.npy + text_embeddings.parquet
    -> data/metrics/interdisciplinarity_courses.parquet   (per-course DES, LIS)
    -> data/metrics/interdisciplinarity_departments.parquet (per-dept, ranked)
    -> data/metrics/interdisciplinarity_report.md         (human-readable ranking)

DES (Department Escape) = fraction of a course's k-NN in a different department.
LIS (Latent Interdisciplinarity Score) = normalized entropy of neighbor COLLEGE labels.

SIZE CONTROL — why rank-based residuals, not z-scores: both metrics are confounded by
department size (bigger depts have more same-dept courses to cluster with; observed
corr(log size, DES) ~ -0.64). A shuffled-label z-score does NOT fix this — the std of a
group mean shrinks as 1/sqrt(n), so |z| scales with sqrt(size), re-introducing the
confound (empirically corr stayed ~-0.57). Instead we regress each dept's mean score on
log(size) and rank by the RESIDUAL ("interdisciplinary beyond what size predicts"),
exactly the rank-based-residual approach the plan already prescribes for PLG.

Hygiene: drop <200-char descriptions (generics already excluded at embedding time).

Usage:
  PYTHONPATH=src ~/latent-campus-venv/bin/python scripts/interdisciplinarity.py
  PYTHONPATH=src ~/latent-campus-venv/bin/python scripts/interdisciplinarity.py --k 15
"""
import argparse

import numpy as np
import polars as pl
from scipy.stats import spearmanr

from latent_campus.common.config import DATA_DIR
from latent_campus.metrics.colleges import to_college
from latent_campus.metrics.diversity import des, lis
from latent_campus.metrics.knn import knn_indices

DEFAULT_MODEL_SLUG = "bge-large-en-v1.5"
MIN_CHARS = 200  # locked DES/LIS hygiene: short descriptions are too thin to embed well
MIN_DEPT_N = 10  # depts smaller than this are too noisy to rank / detrend on


def size_residual(values: np.ndarray, sizes: np.ndarray) -> np.ndarray:
    """Residual of `values` after regressing on log(size) — the size-controlled score."""
    logn = np.log(sizes)
    coef = np.polyfit(logn, values, 1)  # [slope, intercept]
    return values - np.polyval(coef, logn)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-slug", default=DEFAULT_MODEL_SLUG)
    ap.add_argument("--k", type=int, default=10, help="neighbors per course")
    args = ap.parse_args()

    emb_dir = DATA_DIR / "embeddings" / args.model_slug
    emb = np.load(emb_dir / "embeddings.npy")
    meta = pl.read_parquet(emb_dir / "text_embeddings.parquet")

    # Hygiene: keep only substantive descriptions; neighbors should be real content too.
    keep = (meta["n_chars"] >= MIN_CHARS).to_numpy()
    emb, meta = emb[keep], meta.filter(pl.col("n_chars") >= MIN_CHARS)
    print(f"corpus: {int(keep.sum())} courses (>={MIN_CHARS} chars), "
          f"dropped {int((~keep).sum())} short")

    depts = meta["dept_code"].to_list()
    colleges = to_college(depts)
    dept_uniq, dept_ints = np.unique(np.array(depts), return_inverse=True)
    coll_uniq, coll_ints = np.unique(np.array(colleges), return_inverse=True)
    print(f"{len(dept_uniq)} departments, {len(coll_uniq)} colleges, k={args.k}")

    nn = knn_indices(emb, k=args.k)
    des_course = des(nn, dept_ints)             # per-course escape fraction
    lis_course = lis(nn, coll_ints, len(coll_uniq))  # per-course college entropy

    # ---- per-department means, then size-detrend (the size-controlled ranking) ----
    n_dept = np.bincount(dept_ints, minlength=len(dept_uniq)).astype(float)
    des_mean = np.bincount(dept_ints, weights=des_course, minlength=len(dept_uniq)) / n_dept
    lis_mean = np.bincount(dept_ints, weights=lis_course, minlength=len(dept_uniq)) / n_dept

    big = n_dept >= MIN_DEPT_N  # fit + rank only on depts large enough to be stable
    des_resid = np.full(len(dept_uniq), np.nan)
    lis_resid = np.full(len(dept_uniq), np.nan)
    des_resid[big] = size_residual(des_mean[big], n_dept[big])
    lis_resid[big] = size_residual(lis_mean[big], n_dept[big])

    depts_df = pl.DataFrame({
        "dept_code": dept_uniq,
        "college": to_college(list(dept_uniq)),
        "n_courses": n_dept.astype(int),
        "des_mean": des_mean,
        "des_resid": des_resid,
        "lis_mean": lis_mean,
        "lis_resid": lis_resid,
    }).filter(pl.col("n_courses") >= MIN_DEPT_N).sort("des_resid", descending=True)

    # ---- verification: did detrending kill the size confound? ----
    logn = np.log(depts_df["n_courses"].to_numpy())
    r_raw = np.corrcoef(logn, depts_df["des_mean"].to_numpy())[0, 1]
    r_res = np.corrcoef(logn, depts_df["des_resid"].to_numpy())[0, 1]
    rho = spearmanr(depts_df["des_resid"], depts_df["lis_resid"]).correlation
    print(f"\ncorr(log size, RAW des_mean)  = {r_raw:+.2f}  (the size confound)")
    print(f"corr(log size, des_RESIDUAL)  = {r_res:+.2f}  (size-controlled)")
    print(f"Spearman(des_resid, lis_resid)= {rho:+.2f}  (DES vs LIS agreement)")

    print(f"\nMost interdisciplinary (des_resid, n>={MIN_DEPT_N}):")
    for r in depts_df.head(10).iter_rows(named=True):
        print(f"  des_resid={r['des_resid']:+.3f} lis_resid={r['lis_resid']:+.3f} "
              f"[{r['dept_code']}/{r['college']}] n={r['n_courses']}")
    print("Most insular:")
    for r in depts_df.tail(8).iter_rows(named=True):
        print(f"  des_resid={r['des_resid']:+.3f} lis_resid={r['lis_resid']:+.3f} "
              f"[{r['dept_code']}/{r['college']}] n={r['n_courses']}")

    # ---- persist ----
    courses = meta.select("course_id", "dept_code", "title", "n_chars").with_columns(
        college=pl.Series(colleges),
        des=pl.Series(des_course),
        lis=pl.Series(lis_course),
    )
    # Namespace outputs per model slug so all embedding spaces' rankings survive
    # side by side for the cross-space replication comparison (Phase 1 closer).
    out = DATA_DIR / "metrics" / args.model_slug
    out.mkdir(parents=True, exist_ok=True)
    courses.write_parquet(out / "interdisciplinarity_courses.parquet")
    depts_df.write_parquet(out / "interdisciplinarity_departments.parquet")
    report = [
        f"# Interdisciplinarity ({args.model_slug}, k={args.k})\n",
        "Rank-based residuals (dept-mean metric detrended on log size).\n",
        f"- corpus: {int(keep.sum())} courses (>={MIN_CHARS} chars), {len(dept_uniq)} depts",
        f"- size control: corr(size, raw)={r_raw:+.2f} -> corr(size, residual)={r_res:+.2f}",
        f"- Spearman(DES-resid, LIS-resid) = {rho:+.2f}\n",
        f"## Most interdisciplinary, by DES residual (n>={MIN_DEPT_N})\n",
        "| dept | college | n | des_resid | lis_resid |",
        "|---|---|---|---|---|",
    ]
    for r in depts_df.head(20).iter_rows(named=True):
        report.append(f"| {r['dept_code']} | {r['college']} | {r['n_courses']} "
                      f"| {r['des_resid']:+.3f} | {r['lis_resid']:+.3f} |")
    (out / "interdisciplinarity_report.md").write_text("\n".join(report) + "\n")
    print(f"\nwrote -> {out}")


if __name__ == "__main__":
    main()
