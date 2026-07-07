"""Probe the text embedding space by hand — find the nearest courses to any course.

No model load, no downloads: works straight off the saved embeddings.npy +
text_embeddings.parquet, so it's instant. Give it a keyword (matches course
titles) or an exact course_id; it prints the top-k nearest courses by cosine
similarity (== dot, since vectors are unit-normalized).

Usage:
  PYTHONPATH=src ~/latent-campus-venv/bin/python scripts/nn_query.py "machine learning"
  PYTHONPATH=src ~/latent-campus-venv/bin/python scripts/nn_query.py 15-122 -k 8
  make nn Q="quantum"
"""
import argparse

import numpy as np
import polars as pl

from latent_campus.common.config import DATA_DIR

DEFAULT_MODEL_SLUG = "bge-large-en-v1.5"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query", help="keyword (matches title) or exact course_id")
    ap.add_argument("-k", type=int, default=10, help="how many neighbors to show")
    ap.add_argument("--model-slug", default=DEFAULT_MODEL_SLUG)
    args = ap.parse_args()

    emb_dir = DATA_DIR / "embeddings" / args.model_slug
    emb = np.load(emb_dir / "embeddings.npy")
    meta = pl.read_parquet(emb_dir / "text_embeddings.parquet")
    titles = meta["title"].to_list()
    depts = meta["dept_code"].to_list()
    cids = meta["course_id"].to_list()

    # Resolve the query to a seed row: exact course_id first, else title keyword.
    idx = None
    if args.query in cids:
        idx = cids.index(args.query)
    else:
        hits = [i for i, t in enumerate(titles) if args.query.lower() in t.lower()]
        if not hits:
            raise SystemExit(f"no course_id or title matched {args.query!r}")
        if len(hits) > 1:
            print(f"'{args.query}' matched {len(hits)} titles; using the first. Others:")
            for i in hits[1:6]:
                print(f"    [{depts[i]}-{cids[i]}] {titles[i]}")
        idx = hits[0]

    sims = emb @ emb[idx]
    order = np.argsort(-sims)[: args.k + 1]  # includes self at rank 0
    print(f"\nSEED: [{depts[idx]}-{cids[idx]}] {titles[idx]}")
    print(f"nearest {args.k} by cosine:")
    for j in order:
        if j == idx:
            continue
        print(f"  {sims[j]:.3f}  [{depts[j]}-{cids[j]}] {titles[j]}")


if __name__ == "__main__":
    main()
