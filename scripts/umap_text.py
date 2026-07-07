"""Unsupervised UMAP of the text embedding space — first visual look (Week 3.5).

  data/embeddings/<model-slug>/embeddings.npy        (5179 x 1024, unit-normalized)
  data/embeddings/<model-slug>/text_embeddings.parquet  (course_id, dept_code, title, ...)
    -> data/embeddings/<model-slug>/umap_2d.parquet   (course_id, dept_code, title, x, y)
    -> data/embeddings/<model-slug>/umap_2d.png       (scatter, top-N depts colored)

UNSUPERVISED on purpose: department labels are NEVER fed to UMAP.fit — they only
color the result. So any clustering we see is discovered by the text alone, which
is what makes "departments separate in the latent space" a real finding and not a
circular one (locked decision). Metric is cosine because the vectors are
unit-normalized (cosine == dot here).

NOTE: first import of umap/numba JIT-compiles and is slow (~1 min). With a fixed
random_state UMAP runs single-threaded for reproducibility, so the fit on ~5k
points takes ~30-60s — acceptable for a one-off.

Usage:
  PYTHONPATH=src ~/latent-campus-venv/bin/python -u scripts/umap_text.py
  PYTHONPATH=src ~/latent-campus-venv/bin/python -u scripts/umap_text.py \
      --n-neighbors 30 --min-dist 0.05 --top-depts 12
"""

import argparse

import matplotlib

matplotlib.use("Agg")  # headless: render straight to file, no display needed
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

from latent_campus.common.config import DATA_DIR  # noqa: E402

DEFAULT_MODEL_SLUG = "bge-large-en-v1.5"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-slug", default=DEFAULT_MODEL_SLUG)
    ap.add_argument("--n-neighbors", type=int, default=15, help="UMAP local/global balance")
    ap.add_argument("--min-dist", type=float, default=0.1, help="UMAP cluster tightness")
    ap.add_argument("--top-depts", type=int, default=12, help="how many depts to color")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    emb_dir = DATA_DIR / "embeddings" / args.model_slug
    emb = np.load(emb_dir / "embeddings.npy")
    meta = pl.read_parquet(emb_dir / "text_embeddings.parquet")
    assert emb.shape[0] == meta.height, "embeddings/parquet row mismatch"
    print(f"loaded {emb.shape[0]} x {emb.shape[1]} embeddings + metadata")

    # Cosine metric: correct geometry for unit-normalized vectors. random_state
    # makes the layout reproducible (and forces single-threaded for determinism).
    import umap

    reducer = umap.UMAP(
        n_neighbors=args.n_neighbors,
        min_dist=args.min_dist,
        metric="cosine",
        random_state=args.seed,
    )
    print(f"fitting UMAP (n_neighbors={args.n_neighbors}, min_dist={args.min_dist}, cosine) ...")
    xy = reducer.fit_transform(emb)
    print("  done")

    coords = meta.select("course_id", "dept_code", "title").with_columns(
        x=pl.Series(xy[:, 0]), y=pl.Series(xy[:, 1])
    )
    coords.write_parquet(emb_dir / "umap_2d.parquet")

    # Color only the top-N departments by course count; gray out the long tail so
    # the eye can track the big disciplines and where they bleed together.
    top = (
        meta.group_by("dept_code").len().sort("len", descending=True).head(args.top_depts)
    )["dept_code"].to_list()
    print(f"coloring top {len(top)} depts: {top}")

    fig, axis = plt.subplots(figsize=(13, 11))
    is_top = np.array([d in top for d in meta["dept_code"].to_list()])
    axis.scatter(xy[~is_top, 0], xy[~is_top, 1], s=4, c="lightgray", alpha=0.4, linewidths=0)
    cmap = plt.get_cmap("tab20")
    for i, dept in enumerate(top):
        m = np.array([d == dept for d in meta["dept_code"].to_list()])
        axis.scatter(xy[m, 0], xy[m, 1], s=7, color=cmap(i % 20), alpha=0.8,
                     linewidths=0, label=f"{dept} (n={int(m.sum())})")
    # A few degenerate embeddings land far out and would squish the bulk; clip the
    # VIEW (not the data — all points stay in umap_2d.parquet) to the 1-99 pct box
    # plus a small margin so the real structure fills the canvas.
    xlo, xhi = np.percentile(xy[:, 0], [1, 99])
    ylo, yhi = np.percentile(xy[:, 1], [1, 99])
    mx, my = 0.05 * (xhi - xlo), 0.05 * (yhi - ylo)
    n_off = int(((xy[:, 0] < xlo - mx) | (xy[:, 0] > xhi + mx)
                 | (xy[:, 1] < ylo - my) | (xy[:, 1] > yhi + my)).sum())
    axis.set_xlim(xlo - mx, xhi + mx)
    axis.set_ylim(ylo - my, yhi + my)
    axis.set_title(
        f"UMAP of bge-large course-text embeddings (unsupervised)\n"
        f"n_neighbors={args.n_neighbors}, min_dist={args.min_dist}, cosine — "
        f"{emb.shape[0]} courses, top {len(top)} depts colored "
        f"({n_off} outliers off-frame)"
    )
    axis.set_xticks([])
    axis.set_yticks([])
    axis.legend(markerscale=2, fontsize=8, loc="best", framealpha=0.9, title="dept_code")
    fig.tight_layout()
    fig.savefig(emb_dir / "umap_2d.png", dpi=150)
    print(f"wrote umap_2d.parquet + umap_2d.png -> {emb_dir}")


if __name__ == "__main__":
    main()
