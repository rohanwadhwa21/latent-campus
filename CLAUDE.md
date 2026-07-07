# The Latent Campus — project context for Claude Code

A portfolio ML project by an ECE/ML student at CMU (rohanw2105@gmail.com). It builds
a **multimodal institutional atlas of CMU** — embedding courses, faculty, departments,
and buildings into one latent space and visualizing that space against the physical
campus to measure interdisciplinarity. 12-week plan; we are in **Phase 1 (data
foundation)**.

The approved plan lives at
`~/.claude/plans/project-handoff-the-eager-umbrella.md` (model ladder, leakage rules,
two viz modes, week-by-week sequence). Read it for the full vision.

---

## ⚠️ Environment gotchas (READ FIRST — each cost real debugging time)

This machine is macOS, repo is in **iCloud-synced `~/Desktop`**, and the shell is zsh.

1. **Use `.venv/bin/python` with `PYTHONPATH=src` — never `uv run`.** `uv run` rebuilds
   the editable install on every call; concurrent invocations race and stall for
   minutes or raise spurious `ModuleNotFoundError: latent_campus`. The Makefile and all
   commands below already do this.

2. **Native imports (`polars` ~17–45s, `pyarrow` ~33s) stall at 0% CPU on first load**
   per OS-cache window — a macOS notarization check. `xattr -dr com.apple.quarantine
   .venv` helps (cut polars 45s→11s→cached 0.25s). Subsequent imports in the same
   window are instant. **Heavy disk I/O (a running scraper, a `tail -f`, brctl) starves
   these imports further** and can stall them for many minutes. Warm the import first
   (`.venv/bin/python -c "import polars, pyarrow"`) before launching a script that
   imports them, and don't run two heavy things at once. Run scripts with `python -u`
   so prints aren't block-buffered and you can see where a process actually is.

3. **The fetcher uses `curl`, not httpx.** httpx/httpcore stalls ~30s per request
   against CMU hosts (`enr-apps.as.cmu.edu`, `coursecatalog.web.cmu.edu`) due to
   IPv6-first then slow IPv4 fallback. curl does happy-eyeballs correctly (~0.4s).
   `src/latent_campus/common/fetch.py:PoliteFetcher` shells out to curl. SOC returns
   HTTP 500 for non-existent course+semester pairs — 5xx is NOT retried (body saved,
   parser decides); only transport failures retry.

4. **The raw HTML cache lives OUTSIDE iCloud** at `~/latent-campus-data/raw`, resolved
   via env var **`LATENT_CAMPUS_RAW_DIR`** (`config.py:RAW_DIR`; the Makefile sets it).
   Why: iCloud "Optimize Mac Storage" evicts large cached files to **dataless
   placeholders** under disk pressure; reads then time out (**Errno 60 / Operation
   timed out**) or hang. A **symlink inside the synced tree does NOT work** — iCloud
   renamed it to `raw 2` mid-run and broke it (caused `curl exit 23` +
   `FileNotFoundError`). Hence the env-var indirection. **The script's incremental
   resume log** (`soc_descriptions.jsonl`) also lives in `~/latent-campus-data/raw/details/`
   for the same reason — any file in the synced tree is evictable.
   - To relocate on a fresh machine: `export LATENT_CAMPUS_RAW_DIR=~/latent-campus-data/raw`
     (the Makefile defaults to this).
   - `~/latent-campus-data` is the **same APFS Data volume** (disk3s5), so this defeats
     iCloud *eviction* but NOT true disk-full. **Keep that volume below ~95%** — the
     earlier crashes (Errno 28, curl exit 23) were genuine disk-full at 95% / 11 GB free.

---

## Current status (as of 2026-07-01)

**✅ PHASE 1 COMPLETE — text atlas + interdisciplinarity metric built, verified, AND
replicated across 4 embedding spaces.** ~4 of 12 weeks. The bge-large space (5,179×1024)
exists; the DES+LIS metric runs (`make interdisciplinarity`, size-controlled via rank
residuals) and gave a clean finding: EPP/Heinz/Tepper/SCS most interdisciplinary,
Math/CompBio/MCS most insular (DES↔LIS Spearman +0.81). **The finding REPLICATES** across
bge, mpnet, MiniLM, and e5 (mean pairwise Spearman **+0.88**; the headline depts are top-20
in **all 4/4** spaces; 19 depts replicate at ≥3/4). See DECISIONS.md + the
`replication_report.md`. Metric code: `src/latent_campus/metrics/` +
`scripts/interdisciplinarity.py` + `scripts/compare_spaces.py`. **Next: Week 4 (faculty).**

### ✅ Week 1 — Course ingestion (complete, verified)
- 6 semesters scraped: **S26, F25, S25, F24, S24, F23** (skip summers).
- **42,557 offerings → 6,307 unique courses**, 59 depts, 0 duplicate IDs.
- Instructor coverage 82–91% for F23–S25; **0% for F25/S26** (CMU removed Bldg/Room +
  Instructor columns from the public SOC starting Fall 2025 — recent-semester
  instructors need FCE/SIO in Phase 2). F23–S25 columns recovered via Wayback snapshots.
- Instructor strings are **comma-joined LAST NAMES** ("Taylor, Kosbie" = 2 people).
- 28 parser tests green against real HTML fixtures.

### ✅ Week 2 — Descriptions (COMPLETE — gap-fill + merge done 2026-06-18)
- Catalog primary: **3,276** descriptions from coursecatalog.web.cmu.edu (~37 dept
  `/courses/` pages, semester-independent). Catalog **structurally excludes Heinz
  College (90-95) and many grad/professional courses**.
- SOC `courseDetails` gap-fill (live semesters S26/F25 only): gap set = **2,254**, now
  **all 2,254 fetched & parsed** (resume log + `soc_descriptions.parquet` both built,
  484K). The final ~549 fetched cleanly this session, no stalls.
- `make build-canonical` merged both into `courses.parquet`: **combined coverage
  5,530 / 6,307 = 88%** [catalog=3,276, soc=2,254, none=777]. Matched projection exactly.
- Residual **777 nulls** = genuinely discontinued courses (ALL last-seen ≤ S25, zero in
  live F25/S26 → no catalog entry and no live SOC courseDetails source). 28 are generic
  x97/98/99 (excluded by hygiene anyway); concentrated in Heinz (90/95) + StuCo (98).
  **USER DECISION (2026-06-20): DROP all 777** from the text-embedding space; revisit via
  Wayback/FCE in Phase 2 only if needed. Full list saved at
  `data/canonical/missing_descriptions.csv`.
- ✅ **`make test` re-run after merge: 38 passed** (2026-06-19).
- **Embedding corpus (CORRECTED 2026-06-23 via sanity query):** the 5,530 described
  courses are NOT all embeddable. Dropping the **172 described-but-generic** (x97/98/99)
  courses and **160 pure placeholders** (`TBA`/`TBD`/`N/A`/bare-URL non-content that
  slipped through as non-null) leaves a **projected ~5,198-course corpus**. Exact final
  count is logged by the embedding script's placeholder filter on first run (robust
  detection may drop a few more, e.g. "Coming soon"/URL-only stubs). The locked
  ~200-char DES/LIS minimum is a DOWNSTREAM metric-stage filter, NOT applied at
  embedding time (USER DECISION 2026-06-23) — short-but-real descriptions stay in the
  atlas. Also decided 2026-06-23: **clean descriptions with `html.unescape` +
  whitespace-normalize before embedding** (catalog/SOC text has leftover entities).

### ✅ Week 3 — Text embeddings (COMPLETE & VERIFIED 2026-06-29)
Model: **BAAI/bge-large-en-v1.5** (1024-dim, space #1 of ≥4). The embedding space exists,
is validated, and is semantically coherent.

**Run results (2026-06-29):**
- **5,179 courses embedded** (179 placeholders dropped from the 5,358 described
  non-generic — matched the ~5,198 projection). Outputs in
  `data/embeddings/bge-large-en-v1.5/`: `embeddings.npy` (5179×1024 float32),
  `text_embeddings.parquet`, `manifest.json`, `dropped_placeholders.csv`.
- **Validated:** L2 norms all exactly 1.0 (unit-normalized → cosine == dot), no NaN/inf,
  5,179 unique course_ids, npy↔parquet row counts aligned.
- **Nearest-neighbor sanity check passed** — space is real: Organic Chem I → other
  organic-chem courses (0.80–0.88); Shakespeare Tragedies → Shakespeare Comedies (0.948);
  "ML for Scientists" → Computational Genomics / ML for Biomedical Engineers /
  Computational Medicine (depts 02/42/95) — the cross-department concept spread is exactly
  the interdisciplinarity signal we're after. Similarities span a healthy 0.75–0.95.
- **Tests green:** `test_embed_text.py` 20/20; full suite **58 passed**.
- **MPS confirmed** (`torch.backends.mps.is_available()` = True); full encode ~8 min.
- ⚠ **88 kept descriptions still carry `&...;`-like artifacts** post-`html.unescape`
  (the bare-`amp;` case where the `&` was stripped upstream). Logged, NOT yet fixed —
  low-priority cleanup. Diagnostic in `scripts/embed_text.py`.
- ⚠ **Near-duplicate course entries observed** in NN results (cross-listed / same course
  across semesters with separate IDs). Data-quality note for a later dedup pass.

**UMAP first look (2026-06-29) — `scripts/umap_text.py`, `make umap-text`:**
- Outputs `data/embeddings/bge-large-en-v1.5/umap_2d.{parquet,png}`. UNSUPERVISED
  (dept labels only color, never fit), cosine metric, n_neighbors=15, min_dist=0.1,
  seed=42. View clipped to 1–99 pct (133 outlier embeddings off-frame).
- **Finding:** space is semantically coherent (local dept arms: Drama=54, MechE=24,
  History=79 visible) BUT departments barely separate globally —
  **silhouette(cosine) ≈ −0.007 all-depts / +0.056 top-12**, only → +0.064 after the
  200-char filter. The text space is a **continuum, not disciplinary silos** — the
  precondition that makes an interdisciplinarity metric meaningful (clean separation
  would mean nothing to find). Silhouette is a PROXY; the rigorous claim awaits the
  DES/LIS z-score-vs-shuffled-nulls metric.
- **Data-quality note:** boilerplate courses recur across depts with near-identical
  text — "Independent Study", "Study Abroad", "Internship", "Reading and Research"
  (9% have <200-char descriptions). NOT x97/98/99 generics; the 200-char downstream
  filter catches most. Plus the earlier near-duplicate (cross-listed) entries.

**Interaction tools (2026-06-29) — for hands-on testing + feedback:**
- `scripts/nn_query.py` (`make nn Q="..."`) — nearest-neighbor probe by title keyword
  or course_id; no model load, instant. The fast "is the space sane?" check.
- `scripts/umap_interactive.py` (`make umap-interactive`) — hover-able + SEARCHABLE
  Plotly HTML (`umap_2d.html`, self-contained ~5.7 MB): a hand-written HTML+JS shell
  (search box circles matching courses on the map, clickable result list zooms to a
  course, zoom/reset buttons) wrapped around the figure; plus hover=title/dept/id,
  zoom into the mixing zone, legend toggles colleges/depts. Reuses `umap_2d.parquet`
  (no re-fit). Same best-effort dept→college map (VERIFY: 17→SCS, 66→Dietrich, etc.).
- `plotly` added to deps. College-level silhouette +0.023 vs dept −0.007 (broad
  structure separates, fine departments don't — interdisciplinarity lives in between).

**Major infra fixes this session (2026-06-29) — see DECISIONS.md + env-gotchas:**
- **venv moved OUTSIDE iCloud** to `~/latent-campus-venv` (Makefile `VENV` var; build with
  `make setup` = `UV_PROJECT_ENVIRONMENT=$(VENV) uv sync`). The old in-repo `.venv` had
  1,554 files / 874 MB of native libs (incl. torch's 248 MB `libtorch_cpu.dylib`) evicted
  by iCloud to unrecoverable dataless placeholders → torch import hung 40+ min at 0% CPU.
- **HF anonymous downloads are throttled** (model stalled at 192 MB/1.3 GB twice); fixed
  with `hf auth login` (token in `~/.cache/huggingface/token`, outside iCloud).
- **`--batch-size 16` (not the default 64) for the MPS encode** — batch-64 of the longest
  descriptions spiked unified memory, swapped the process out (state `U`, thrashing).

### 🔄 Week 4 — Faculty entity-resolution (IN PROGRESS, started 2026-07-06)

**Phase 2 plan approved** (`~/.claude/plans/remind-yourself-of-what-calm-sloth.md`: Wk4
faculty → Wk5 buildings/PLG/BID → Wk6 OpenAlex pilot). Week 4 infrastructure is BUILT and
TESTED (92 tests green); the bulk directory fetch was launched 2026-07-06 and is the
gating step.

**Built this session (all tested, ruff-clean):**
- `PoliteFetcher` now does form POSTs (cache key = URL + canonical sorted body; old GET
  logs replay unchanged). `tests/test_fetch.py`.
- `directory:` source in `configs/sources.yaml` — **Task-0 findings:** anonymous search is
  name-only (dept search needs Shibboleth); use ADVANCED search `last_name=` (whole-word;
  BASIC matches substrings anywhere — "Lee" hits first-name "Leen"); results HARD-CAPPED
  at 200 (Lee/Li/Wu/Zhang capped; capped pools can't prove uniqueness → manual queue);
  single-hit searches return the person DETAIL page directly.
- `ingest/directory_parse.py` (3 page shapes) + 4 real fixtures + 11 tests.
- `scripts/scrape_directory.py` (`make scrape-directory`) — one advanced search per
  distinct F23–S25 surname (2,294), detail pages for Faculty/Staff hits only, JSONL resume
  log in `$LATENT_CAMPUS_RAW_DIR/directory/`, `--limit N` smoke, `--rebuild-only`.
  → `directory_candidates.parquet`, `directory_queries.parquet`, capped CSV.
- `resolve/faculty.py` (pure, 9 tests): (surname, dept) pair → dept-unique >
  global-unique > ambiguous/capped→manual-queue > no-match. Casefolded surname keys
  ("AAZAM"/"Aazam" variants). NO course text read anywhere (leakage rule).
- `scripts/resolve_faculty.py` (`make resolve-faculty`) → `faculty.parquet` +
  `course_faculty.parquet` + `faculty_ambiguous.csv`; `--report-unmapped` seeds the dept
  map; `--sample-labels N` writes the precision-check CSV. Refuses to run until every
  surname has been queried.
- `Faculty` + `CourseFacultyEdge` schemas (no email/phone — directory acceptable-use);
  SCHEMAS.md + DECISIONS.md updated.

**MACHINE SIDE DONE (2026-07-07):** fetch complete (2,294 surnames, 3,140 candidates, 11
capped), dept map drafted (66 mapped / 374 null, 8 `# TODO verify code`), resolution run:
**2,337/3,594 pairs resolved → 23,082 TEACHES edges (79.1% of tokens), 1,696 faculty
nodes** (1,257 Faculty + 439 Staff; 1,023 with building codes for Wk5). Spot checks pass.
Full numbers in DECISIONS.md "Week 4 first full run".

**TO CLOSE WEEK 4 — needs the USER (the acceptance gate):**
1. Review the 8 `# TODO verify code` entries + umbrella mappings in
   `configs/dept_directory_map.yaml`, then rerun `make resolve-faculty` if edited.
2. Hand-label `data/canonical/faculty_label_sample.csv` (100 pairs; verdict column;
   ~99% precision target, judge dept-unique / global-unique separately — drop
   global-unique from edges if it fails).
3. Optionally triage `faculty_ambiguous.csv` (592 pairs: 468 ambiguous + 124 capped).
4. Record the precision result in DECISIONS.md → Week 4 CLOSED → start Week 5 (buildings;
   Overpass Task-0 already verified, see below).

⚠ **DISK: 3.0 GiB free / 99% (2026-07-07)** — and at this level iCloud began **evicting
the repo's own source files** (133 dataless files across src/scripts/tests/configs/data
overnight 2026-07-06→07; a dataless `.py` read during a network gap = the Errno 60 import
crash). All rehydrated 2026-07-07 by force-reading the tree (`find … -exec cat`). Gotcha #4
now applies to the REPO TREE, not just big caches. Mitigations: keep disk <95% (root
cause); **the repo has NO git repo/remote — strongly consider `git init` + private GitHub
push as the eviction/loss safety net**; check `ls -lO | grep dataless` when imports hang
or reads time out.

Optional Phase-1 polish still pending: mini-post #1 writeup (material in
`PHASE_1_SUMMARY.md`); `--color-by lis` UMAP recolor. FCE/SIO for F25/S26 instructors:
deferred (default), pending user decision.

### ⏳ Not started (Weeks 5–12)
Buildings/PLG/BID (Wk 5), OpenAlex pilot (Wk 6), model ladder (graph-smoothed →
metapath2vec → HGT), leakage checks (Wk 9), two viz modes.
- **Wk5 Task-0 ALREADY VERIFIED (2026-07-06):** Overpass building query works — bbox
  (40.4385,-79.9530,40.4475,-79.9345) on overpass-api.de returns 697 buildings, 131 named,
  incl. ALL probed campus buildings (GHC "Gates and Hillman Centers", Wean, Porter, Tepper,
  CFA, Mellon Institute) with `out tags center;` centroids. Response saved at
  `~/latent-campus-data/raw/overpass/taskzero_cmu_bbox_20260706.json`. Satellites (Mill 19,
  Bakery Sq, NREC) are OUTSIDE this bbox — widen or query separately in Week 5.

Environment reminders (full detail in DECISIONS.md + env-gotchas):
- Use **`~/latent-campus-venv/bin/python`** (NOT `.venv`). `hf auth login` already done.
- ⚠ **DISK: ~6–7 GB free / 97%.** The bge MODEL cache was deleted 2026-07-01 (embeddings
  kept) to make room for e5; re-embedding bge would re-download 1.3 GB. Keep the Data volume
  below ~95%; macOS parks freed space as *purgeable* so `df` lags after deletes.
- After any dep change: `xattr -dr com.apple.quarantine ~/latent-campus-venv`.
- Keep MPS `--batch-size 16` to avoid swap thrash. `embed_text.py` now has `--prefix`
  (empty for bge/mpnet/MiniLM; `"query: "` for e5).

---

## Repo map

```
configs/semesters.yaml      # [S26, F25, S25, F24, S24, F23]
configs/sources.yaml        # SOC + catalog URLs, Wayback timestamps, scraping policy
                            #   (UA "latent-campus-research (rohanw2105@gmail.com)", 2s rate)
src/latent_campus/common/
  config.py                 # load_config, REPO_ROOT/DATA_DIR/CONFIG_DIR, RAW_DIR (env-overridable)
  schemas.py                # pydantic Course/CourseOffering/Meeting; normalize_course_id; GENERIC_NUMBER_RE
  fetch.py                  # PoliteFetcher (curl-based, cached, JSONL fetch log, retries)
src/latent_campus/ingest/
  soc_fetch.py / soc_parse.py     # complete-schedule dump fetch + parse (OLD 10-col / NEW 8-col)
  catalog_fetch.py / catalog_parse.py   # course-catalog pages -> CatalogEntry
  details_parse.py          # courseDetails HTML -> DetailsEntry (desc, cross-listed, prereqs)
src/latent_campus/embed/
  text.py                   # clean_description + is_placeholder (stdlib-only corpus hygiene)
src/latent_campus/ingest/
  directory_parse.py        # directory search pages (multi/single/empty, 200-cap flag)  (Wk4)
src/latent_campus/resolve/
  faculty.py                # pure (surname, dept) -> directory-person resolution rules  (Wk4)
scripts/
  scrape_courses.py         # SOC dumps -> raw/courses/json -> parsed offerings
  scrape_descriptions.py    # catalog pages -> catalog_descriptions.parquet
  fill_descriptions_soc.py  # SOC courseDetails gap-fill -> soc_descriptions.parquet  (ACTIVE)
  build_canonical.py        # offerings -> courses.parquet + course_offerings.parquet;
                            #   enrich_descriptions() coalesces catalog(1st) + soc(2nd)
  embed_text.py             # courses.parquet -> data/embeddings/<model>/ (bge-large; Wk3)
  scrape_directory.py       # directory search per instructor surname -> candidates    (Wk4)
  resolve_faculty.py        # -> faculty.parquet + course_faculty.parquet + queues     (Wk4)
  validation_report.py
tests/                      # 38 tests vs checked-in HTML fixtures + test_embed_text.py (pure-logic)
Makefile                    # setup, scrape-courses/-all, scrape-descriptions, fill-descriptions-soc,
                            #   build-canonical, embed-text, validate, test, lint

# data (gitignored):
data/canonical/*.parquet           # in-repo: courses, course_offerings, catalog_descriptions,
                                   #   (soc_descriptions.parquet built by the fill step)
data/embeddings/<model>/           # bge-large-en-v1.5/: embeddings.npy + text_embeddings.parquet
                                   #   + manifest.json + dropped_placeholders.csv (built by embed-text)
~/latent-campus-data/raw/          # OUTSIDE iCloud: courses/, catalog/, details/ html caches,
  details/soc_descriptions.jsonl   #   + the incremental resume log
```

Stack: uv, polars, pyarrow, beautifulsoup4/lxml, pydantic v2, tenacity, duckdb, pytest,
ruff (line-length 100); **sentence-transformers + torch** (Wk3 embeddings, MPS on Apple
Silicon). Parquet + DuckDB storage. Schemas documented in `SCHEMAS.md`.

**`PHASE_1_SUMMARY.md`** — a detailed teaching-oriented walkthrough of all of Phase 1 (how
each stage works, the finding, the environment hurdles + fixes, and the Phase 2+ roadmap).
Read it for the full narrative; `DECISIONS.md` is the terse decision log.

---

## Locked decisions (don't relitigate)

- 6 semesters (above); canonical course description = most recent non-empty.
- **Scrape CMU directly** (SOC nightly complete-schedule dump + course catalog);
  ScottyLabs/cmucourses only as a cross-validation check.
- Descriptions: **catalog primary, SOC courseDetails gap-fill** (hybrid). 777 discontinued
  no-description courses DROPPED from the embedding corpus (list in
  `data/canonical/missing_descriptions.csv`).
- Primary text encoder: **BAAI/bge-large-en-v1.5** (1024-dim). Finding must replicate
  across ≥3 of 4 spaces, so this is space #1 of several.
- uv over poetry. Unsupervised UMAP. **No physical proximity leakage** into the training
  graph. Evidence panels for every edge. Model ladder text → graph-smoothed →
  metapath2vec (a control, never the final-viz space) → HGT.
- Faculty: non-faculty instructors get no node; Faculty node only on directory
  resolution; never fall back to taught-course text (leakage). OpenAlex = Week 6 pilot
  only (full integration is v1.5).
- DES/LIS hygiene: exclude x97/x98/x99 independent-study/thesis numbers, min description
  ~200 chars, z-score against shuffled-label nulls. Finding "replicates" if top-20 in
  ≥3 of 4 embedding spaces. PLG: main-campus-only primary; rank-based residuals.
- SOC dept codes are the canonical Department key. Filter to Pittsburgh campus (exclude
  Qatar).

---

## Persistent memory

Project-specific gotchas are also in the auto-loaded memory at
`~/.claude/projects/-Users-rohanwadhwa-Desktop-LatentCampus/memory/`
(`env-gotchas.md`, `soc-data-quirks.md`, indexed in `MEMORY.md`). This CLAUDE.md is the
fuller narrative; those are the one-line recall hooks.
