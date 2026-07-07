"""Embed course descriptions into the primary text latent space (Week 3).

  data/canonical/courses.parquet
    -> data/embeddings/<model-slug>/text_embeddings.parquet  (course_id + vector)
    -> data/embeddings/<model-slug>/embeddings.npy           (float32 [N, dim])
    -> data/embeddings/<model-slug>/manifest.json            (model/dim/date/N)
    -> data/embeddings/<model-slug>/dropped_placeholders.csv (audit trail)

Corpus = described, non-generic courses, minus pure placeholders (TBA/N/A/bare
URL — see latent_campus.embed.text). Model: BAAI/bge-large-en-v1.5 (1024-dim),
"space #1" of several; the interdisciplinarity finding must later replicate
across >=3 of 4 spaces. bge plain-document embedding takes NO instruction
prefix (prefixes are only for retrieval queries).

NOTE: first run downloads the model (~1.3 GB) from HuggingFace — network + disk
I/O heavy. Run `xattr -dr com.apple.quarantine .venv` first and avoid running
other heavy native imports concurrently (see CLAUDE.md env gotchas).

Usage:
  PYTHONPATH=src .venv/bin/python -u scripts/embed_text.py            # full run
  PYTHONPATH=src .venv/bin/python -u scripts/embed_text.py --limit 50 # smoke test
"""

import argparse
import datetime as dt
import json

import numpy as np
import polars as pl

from latent_campus.common.config import DATA_DIR
from latent_campus.embed.text import clean_description, is_placeholder

DEFAULT_MODEL = "BAAI/bge-large-en-v1.5"
COURSES_PARQUET = DATA_DIR / "canonical" / "courses.parquet"


def model_slug(name: str) -> str:
    """'BAAI/bge-large-en-v1.5' -> 'bge-large-en-v1.5' for a tidy output dir."""
    return name.split("/")[-1]


def pick_device(requested: str | None) -> str:
    """Resolve compute device: explicit flag wins, else MPS (Apple Silicon), else CPU."""
    if requested:
        return requested
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def build_corpus(courses: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Return (kept, dropped). kept has a 'clean_text' column ready to embed.

    Drops generic (x97/98/99) and null-description courses by design, then the
    cleaned placeholders. Only placeholder drops are returned for audit — the
    generic/null exclusions are already recorded in missing_descriptions.csv.
    """
    described = courses.filter(
        pl.col("is_generic").not_() & pl.col("description").is_not_null()
    ).with_columns(
        pl.col("description")
        .map_elements(clean_description, return_dtype=pl.Utf8)
        .alias("clean_text")
    )
    described = described.with_columns(
        pl.col("clean_text")
        .map_elements(is_placeholder, return_dtype=pl.Boolean)
        .alias("_is_placeholder")
    )

    kept = described.filter(pl.col("_is_placeholder").not_()).with_columns(
        pl.col("clean_text").str.len_chars().alias("n_chars")
    )
    dropped = described.filter(pl.col("_is_placeholder")).select(
        "course_id", "description_source", pl.col("description").alias("original_description")
    )
    return kept.drop("_is_placeholder"), dropped


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--device", default=None, help="mps|cpu|cuda; auto-detect if omitted")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument(
        "--prefix",
        default="",
        help="text prepended to every description before encoding. bge/mpnet/MiniLM "
        "take NONE (leave empty); e5 needs 'query: ' for symmetric similarity/clustering "
        "(same prefix on all texts, per its model card).",
    )
    ap.add_argument("--limit", type=int, default=None, help="embed only first N (smoke test)")
    args = ap.parse_args()

    if not COURSES_PARQUET.exists():
        raise SystemExit(f"missing {COURSES_PARQUET}; run build_canonical.py first")

    courses = pl.read_parquet(COURSES_PARQUET)
    kept, dropped = build_corpus(courses)

    # Diagnostic: surface any systemic leftover HTML-entity artifacts post-clean.
    residual = kept.filter(
        pl.col("clean_text").str.contains(r"&\w+;|amp;", literal=False)
    ).height
    described_non_generic = kept.height + dropped.height
    print(
        f"corpus: {kept.height} kept, {dropped.height} placeholders dropped "
        f"(of {described_non_generic} described non-generic)"
    )
    if residual:
        print(f"  ⚠ {residual} kept descriptions still contain entity-like artifacts (&...;)")

    if args.limit:
        kept = kept.head(args.limit)
        print(f"  --limit {args.limit}: embedding first {kept.height} only")

    device = pick_device(args.device)
    print(f"loading {args.model} on device={device} ...")
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(args.model, device=device)
    dim = model.get_sentence_embedding_dimension()

    texts = kept["clean_text"].to_list()
    if args.prefix:
        texts = [args.prefix + t for t in texts]
        print(f"  applying prefix {args.prefix!r} to all {len(texts)} texts (e5-style)")
    # normalize -> unit vectors so downstream cosine == dot; UMAP uses cosine.
    emb = model.encode(
        texts,
        batch_size=args.batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_numpy=True,
    ).astype(np.float32)
    assert emb.shape == (kept.height, dim), f"unexpected shape {emb.shape}"

    out_dir = DATA_DIR / "embeddings" / model_slug(args.model)
    out_dir.mkdir(parents=True, exist_ok=True)

    np.save(out_dir / "embeddings.npy", emb)
    emb_df = kept.select(
        "course_id", "dept_code", "title", "description_source", "n_chars"
    ).with_columns(
        pl.Series("embedding", [row.tolist() for row in emb], dtype=pl.List(pl.Float32))
    )
    emb_df.write_parquet(out_dir / "text_embeddings.parquet")
    dropped.write_csv(out_dir / "dropped_placeholders.csv")

    manifest = {
        "model": args.model,
        "dim": dim,
        "device": device,
        "prefix": args.prefix,
        "normalized": True,
        "n_courses": kept.height,
        "n_placeholders_dropped": dropped.height,
        "source_parquet": str(COURSES_PARQUET.relative_to(DATA_DIR.parent)),
        "built_at": dt.datetime.now().isoformat(timespec="seconds"),
        "row_order": "matches embeddings.npy and text_embeddings.parquet",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {kept.height} x {dim} embeddings -> {out_dir}")


if __name__ == "__main__":
    main()
