# Latent Campus

A multimodal institutional atlas of CMU: courses, faculty, departments, and
buildings embedded in one latent space, visualized against the physical campus.
Measures where CMU's intellectual structure aligns — or fails to align — with
its administrative and spatial structure.

**Status: Phase 1, Week 1 complete** — course ingestion working end-to-end:
6 semesters (F23–S26), ~42.5k offerings, ~6.3k unique courses. No faculty,
buildings, embeddings, or frontend yet (deliberately — see the phased plan).

## Setup

```sh
uv sync
```

## Data sources (verified 2026-06-13)

Courses come from the SOC "complete schedule" — a nightly single-file HTML
dump per cycle (one fetch per semester, no dept-by-dept crawling):

- **F23–S25**: Wayback Machine snapshots of the dump. These have the full
  10-column format including **Bldg/Room and Instructor**.
- **F25–S26**: live dump. CMU removed the Bldg/Room and Instructor columns
  from the public SOC starting with Fall 2025 — recent-semester instructor
  data must come from another source (FCEs / SIO) in Phase 2.
- Instructor strings are comma-joined **last names** (`"Taylor, Kosbie"` is
  two people); full identity resolution happens in Phase 2 ER.
- Course **descriptions** are not in the dump. Primary source is the official
  course catalog (semester-independent, ~37 dept pages). The catalog excludes
  graduate/professional schools (Heinz 90-95, etc.), so those gaps are filled
  from the SOC `courseDetails` endpoint (live semesters only). See SCHEMAS.md.

Snapshot timestamps and endpoints live in `configs/sources.yaml`.

## Pipeline

```sh
make scrape-courses        # SOC dumps -> data/raw/courses/ -> parsed offerings JSON
make scrape-descriptions   # course catalog -> catalog_descriptions.parquet
make fill-descriptions-soc # SOC courseDetails gap-fill -> soc_descriptions.parquet (~90 min)
make build-canonical       # merge all -> data/canonical/{courses,course_offerings}.parquet
make validate              # -> data/canonical/validation_report.md
make test
```

Re-running any fetch is a no-op for already-fetched URLs (content-hash cache,
keyed off the fetch log). Rate limit: 1 request / ~2s + jitter, custom UA with
contact email. The fetcher uses **curl** (httpx stalls ~30s/request on CMU hosts).

**Local gotcha:** prefer `.venv/bin/python` over `uv run` — `uv run` rebuilds the
editable install on every call and can stall. Native imports (pyarrow, lxml) also
hit a slow first-load per OS-cache window; `xattr -dr com.apple.quarantine .venv`
helps. The `make` targets call the venv Python directly.

## Layout

- `configs/` — semesters to scrape, source endpoints, scraping policy
- `src/latent_campus/common/` — config loading, pydantic schemas
- `src/latent_campus/ingest/` — SOC fetcher, parser, validation report
- `scripts/` — thin CLI runners
- `data/` — gitignored; schemas documented in [SCHEMAS.md](SCHEMAS.md)
  - The **raw HTML cache lives outside the repo** at `~/latent-campus-data/raw`
    (override with `LATENT_CAMPUS_RAW_DIR`). This repo sits in an iCloud-synced
    `~/Desktop`, which evicts large cached files to dataless placeholders under
    disk pressure (reads then time out) — and even removes a symlink placed in
    the synced tree, so the location is resolved from an env var, not a symlink.
    The cache is regenerable; `data/canonical/` parquets stay in-repo.

Modules for embeddings, graph construction, metrics, and viz export are added
when their phase begins, not before.
