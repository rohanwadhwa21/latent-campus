# The Latent Campus — Phase 1 Summary & Teaching Notes

*A detailed walkthrough of everything built in Phase 1 (the data foundation): how each piece
works, the files that make it run, the hurdles we hit and how we beat them, the results, and
what the later phases hold. Written to be **learned from**, not just referenced.*

**Status:** Phase 1 COMPLETE (2026-07-01), ~4 of 12 weeks.

---

## 0. The thesis (what the whole project is for)

The Latent Campus builds a **multimodal institutional atlas of CMU**: it embeds courses,
faculty, departments, and buildings into *one shared latent space* and visualizes that space
against the physical campus, in order to **measure interdisciplinarity** — how much ideas at
CMU cross the boundaries we draw between departments.

"Latent space" is the key phrase. A **latent space** is a high-dimensional coordinate system
where *meaning* is encoded as *position*: things that mean similar things sit close together,
things that don't sit far apart. The entire project is: build that space well, then ask
geometric questions of it ("whose ideas sit near whose?") that translate into institutional
questions ("which departments are intellectual crossroads?").

Phase 1's job was to build the **first axis** of that atlas — the **course-text space** — and
prove that a real, defensible interdisciplinarity signal can be extracted from it. That is now
done and, crucially, **replicated** (more on why that word matters below).

---

## 1. The Phase 1 pipeline at a glance

```
  CMU Schedule of Classes (SOC)          CMU Course Catalog
  nightly complete-schedule dump         ~37 department /courses/ pages
        │                                        │
        ▼  (Week 1)                              ▼  (Week 2)
  scrape_courses.py                        scrape_descriptions.py
  42,557 offerings → 6,307 courses         3,276 catalog descriptions
        │                                        │
        └──────────────┬─────────────────────────┘
                       ▼  (Week 2)  fill_descriptions_soc.py  (+2,254 gap-fill)
                 build_canonical.py
             courses.parquet  (6,307 courses, 5,530 with descriptions)
                       │
                       ▼  (Week 3)  embed_text.py
        4 embedding spaces  ×  5,179 courses each
        bge-large(1024) · mpnet(768) · MiniLM(384) · e5-large(1024)
                       │
          ┌────────────┴────────────┐
          ▼                          ▼  (Phase 1 closer)
   umap_text.py                interdisciplinarity.py  (DES + LIS, size-controlled)
   2D map for the eye          per-course & per-dept scores  →  the FINDING
                                      │
                                      ▼  compare_spaces.py
                             replication across all 4 spaces  →  Phase 1 CLOSED
```

The design principle throughout: **each stage writes a checkpoint to disk (Parquet/npy) so the
next stage can start cold.** That is what let us resume across many sessions and re-run any one
stage in isolation.

---

## 2. Week 1 — Course ingestion

**Goal:** get every course CMU offers into a clean, deduplicated table.

**How it works.** CMU publishes a nightly "complete schedule" dump on its Schedule of Classes
(SOC) site. `scripts/scrape_courses.py` fetches that dump for each of **6 semesters** (S26,
F25, S25, F24, S24, F23 — we skip summers), and `soc_parse.py` turns the HTML into structured
rows. Each row is an **offering** (one course in one semester); we then collapse offerings into
**unique courses**.

- **Result:** 42,557 offerings → **6,307 unique courses**, 59 departments, 0 duplicate IDs.
- A course's canonical fields come from its *most recent* offering (titles/descriptions drift
  over time; recency wins).

**Concepts you learned here:**
- **Offering vs. course** — the same distinction as "a screening" vs. "a film." Modeling this
  explicitly (two tables, `course_offerings.parquet` and `courses.parquet`) keeps
  time-varying facts (who taught it, when) separate from stable facts (what the course *is*).
- **Idempotent scraping with a cache** — `PoliteFetcher` caches every raw HTML response, so
  re-running the scraper costs nothing and never re-hammers CMU's servers.
- **Schema validation** — `schemas.py` uses **pydantic** to define `Course`/`CourseOffering`
  as typed objects. Bad rows fail loudly at parse time instead of silently corrupting the
  dataset downstream.

**Data quirks discovered (documented in `soc-data-quirks.md`):**
- Instructor strings are **comma-joined last names** ("Taylor, Kosbie" = *two* people). This
  matters a lot for Week 4 faculty resolution.
- CMU **removed the instructor & room columns** from the public SOC starting Fall 2025, so
  instructor coverage is 82–91% for F23–S25 but **0% for F25/S26**. We recovered the older
  columns from **Wayback Machine** snapshots; recent instructors will need FCE/SIO in Phase 2.

---

## 3. Week 2 — Course descriptions (the text we actually embed)

**Goal:** attach a real prose description to each course — that text is the raw material the
embedding models read.

**How it works — a hybrid, two-source strategy:**
1. **Catalog primary.** `scrape_descriptions.py` pulls ~37 department `/courses/` pages from
   `coursecatalog.web.cmu.edu`. These are semester-independent and clean. → **3,276**
   descriptions. But the catalog **structurally excludes Heinz College (90–95)** and many
   grad/professional courses.
2. **SOC gap-fill.** For courses the catalog misses, `fill_descriptions_soc.py` fetches the
   per-course `courseDetails` pages from the live SOC (S26/F25 only). → **+2,254**.
3. **Merge.** `build_canonical.py`'s `enrich_descriptions()` coalesces the two sources
   (catalog first, SOC second) into `courses.parquet`.

- **Result:** **5,530 / 6,307 = 88%** coverage. The residual **777** are genuinely
  discontinued courses (last seen ≤ S25, no catalog entry, no live SOC page). **User decision:
  drop them** from the embedding corpus (list saved in `missing_descriptions.csv`).

**Concepts you learned here:**
- **Coverage vs. purity trade-off** — one clean source covered only ~half the courses; a
  hybrid got us to 88% at the cost of two code paths. Documenting *why* each source exists (in
  DECISIONS.md) is what makes that defensible later.
- **Corpus hygiene.** `src/latent_campus/embed/text.py` holds two stdlib-only functions:
  `clean_description` (HTML-unescape + whitespace-normalize — the raw text had leftover
  `&amp;`-style entities) and `is_placeholder` (drops "TBA"/"TBD"/"N/A"/bare-URL stubs that
  are technically non-null but carry no meaning). **Garbage text → garbage embeddings**, so
  this filter is load-bearing.

---

## 4. Week 3 — Text embeddings (building the latent space)

**Goal:** turn each course's cleaned description into a **vector** — a list of numbers that
encodes its meaning as a position in high-dimensional space.

### 4.1 What an embedding actually is

An **embedding model** is a neural network trained so that texts with similar meaning get
mapped to nearby points. Feed it "Organic Chemistry I" and it returns, say, 1024 numbers; feed
it "Organic Chemistry II" and it returns 1024 *different but nearby* numbers. "Shakespeare's
Tragedies" lands in a completely different region. The model learned this geometry from
enormous amounts of text; we just *use* it.

We **unit-normalize** every vector (scale it to length 1). This is a small but important trick:
once all vectors have length 1, the **cosine similarity** between two of them (the angle
between the arrows, the standard way to measure "how similar") equals their **dot product** —
a single fast matrix multiply. So `embeddings @ embeddings.T` gives us the full
course-to-course similarity matrix in one operation. Every downstream tool relies on this.

### 4.2 How we run it

`scripts/embed_text.py` is **model-agnostic**: `--model <hf-name>` picks any HuggingFace
sentence encoder, and it writes to `data/embeddings/<slug>/`:
- `embeddings.npy` — the raw `[N × dim]` float32 matrix (fast to load for math)
- `text_embeddings.parquet` — same vectors + metadata (course_id, dept, title) for joins
- `manifest.json` — provenance (model, dim, date, prefix, N)
- `dropped_placeholders.csv` — audit trail of what got filtered

It runs on **MPS** (Apple Silicon's GPU) via PyTorch. The primary model is
**BAAI/bge-large-en-v1.5** (1024-dim).

- **Result:** **5,179 courses embedded** (5,530 described − 179 placeholders − generics).
- **Validated:** all L2 norms exactly 1.0, no NaN/inf, row counts aligned across npy↔parquet.
- **Nearest-neighbor sanity check passed** — the space is *real*: "ML for Scientists" →
  Computational Genomics / ML for Biomedical Engineers / Computational Medicine (departments
  02, 42, 95). That cross-department spread is *exactly* the interdisciplinarity signal.

### 4.3 UMAP — seeing the space

A 1024-dimensional space is impossible to look at. **UMAP** (Uniform Manifold Approximation
and Projection) is a **dimensionality-reduction** algorithm that squashes those 1024 dims down
to **2** for plotting, while trying to preserve which points are neighbors.

Two teaching points we hit head-on:
- **UMAP is used UNSUPERVISED.** We never feed it the department labels — labels only *color*
  the finished plot. If we let labels influence the layout, we'd be drawing the answer we're
  trying to discover (circular reasoning).
- **A 2D picture is lossy.** We saw cross-listed near-identical courses (15-151 & 21-128) land
  farther apart in 2D than expected. That's not a bug in the space — it's the price of
  crushing 1024 dims into 2. **Lesson: the metric is computed in the full-dimensional space;
  the 2D map is for intuition only.** Silhouette scores confirmed the space is a *continuum*,
  not clean disciplinary silos — which is the precondition that makes measuring
  interdisciplinarity meaningful (if departments were perfectly separated, there'd be nothing
  to find).

**Interaction tools built for you to poke at it:**
- `scripts/nn_query.py` (`make nn Q="..."`) — instant nearest-neighbor probe, no model load.
- `scripts/umap_interactive.py` — a searchable, hover-able Plotly HTML map.

---

## 5. The Phase 1 closer — the interdisciplinarity metric

This is the intellectual heart of the phase. **How do you turn "who is near whom" into a
number that says how interdisciplinary a department is?**

### 5.1 The two metrics

Built in `src/latent_campus/metrics/` (pure NumPy, tested), driven by
`scripts/interdisciplinarity.py`:

- **DES — Department Escape score.** For each course, find its *k* nearest neighbors (k=10) in
  the embedding space and compute the **fraction that belong to a different department**. A
  course whose neighbors are all in its own department = insular (DES 0); a course whose
  neighbors scatter across departments = a bridge (DES near 1). `metrics/diversity.py::des`.
- **LIS — Latent Interdisciplinarity Score.** The **normalized Shannon entropy** of the
  *college* labels among a course's neighbors. Entropy measures *variety + balance*: neighbors
  spread evenly across many colleges → high LIS; neighbors all one college → low LIS. This
  generalizes DES to a coarser, richer level. `metrics/diversity.py::lis`.

We compute both per-course, then average to per-department, then **rank** departments. We
report **Spearman correlation between DES and LIS** as a cross-metric robustness check (they
agree at +0.79–0.83 — two different definitions telling the same story).

### 5.2 The size confound — and the methodology correction we made

This is the most important lesson of the phase, and a genuinely subtle statistical trap.

**The problem:** bigger departments *automatically* look more insular. If a department has 300
courses, any given course has lots of same-department neighbors to cluster with, purely by
counting. We measured it: **corr(log department size, raw DES) = −0.64.** That's a huge
confound — without correcting it, we'd just be measuring department size, not interdisciplinarity.

**The plan's original fix (and why it failed):** the approved plan said to **z-score against a
shuffled-label null** — reshuffle the department labels many times, recompute the score, and
see how many standard deviations the real score sits above random. The engine for this is built
and tested in `metrics/nulls.py`. **But when we ran it, the confound didn't go away** (corr
stayed ≈ −0.57). Why? The standard deviation of a group's *mean* shrinks as 1/√n. So a big
department has a tiny null-std, which *inflates* its |z| by roughly √(size) — re-introducing
size through the back door. **This is a real, non-obvious statistical pitfall.**

**The fix we switched to: rank-based residuals.** We regress each department's mean score on
`log(size)` (a straight-line fit), and rank departments by the **residual** — how far above or
below the size-predicted line they sit. This is literally "interdisciplinary *beyond what its
size predicts*." `scripts/interdisciplinarity.py::size_residual`.
- **Result: corr(size, residual) = +0.00.** Confound gone.
- We kept the `nulls.py` permutation engine (it's tested and reusable) for *significance
  testing* and later modalities — just not as the *ranking* score.

**What you learned:** (1) always verify that a correction actually corrected the thing; the
built-in `corr(size, residual)` print is what caught the z-score failure. (2) A more
sophisticated method (permutation z-scores) is not automatically the right one — the simpler
residual approach was both correct *and* the one the plan already prescribed for the physical
(PLG) metric. Consistency across the project won.

### 5.3 The finding

On the metric corpus (**4,738 courses** with ≥200-char descriptions, 59 departments):

- **Most interdisciplinary:** Engineering & Public Policy (19), Heinz policy schools
  (94/90/95/67), Tepper business (45), SCS/societal computing (17).
- **Most insular:** Math (21), Computational Biology (02), other MCS units (33/09), a Tepper
  sub-unit (46), CFA music/art (57).

These are *exactly* the units CMU **designs** to be interdisciplinary (EPP and Heinz literally
exist to bridge fields) — rediscovered from **course text alone**, with no human labels. A
nice nuance worth internalizing: "Computational Biology" ranks *insular* despite its name —
it's a coherent, self-contained field, not a scattering of other fields. The metric measures
*intellectual spread*, not buzzwords.

### 5.4 Replication — why the finding is trustworthy

A finding measured in **one** model's space could be a quirk of *that model*. So the
pre-committed bar (locked in DECISIONS.md) was: **the finding must replicate across ≥3 of 4
independent embedding spaces.**

We embedded the *identical* corpus with three more encoders — **mpnet (768-d), MiniLM (384-d),
e5-large (1024-d)** — and re-ran the metric on each. `scripts/compare_spaces.py` then compared
the four rankings:

- **Mean pairwise Spearman = +0.88** (range +0.78 to +0.94). The four models strongly *agree*
  on the ordering.
- **The headline departments (Heinz, Tepper, EPP, SCS) are top-20 in ALL 4/4 spaces.** 19
  departments replicate at ≥3/4.
- Even **MiniLM** — a deliberately tiny 384-dim model — reproduces it. That's the strongest
  evidence: the signal lives in the **course text**, not in any one model's capacity.

**⇒ The interdisciplinarity of CMU, as read from course descriptions, is a robust, model-
independent fact.** Phase 1 is closed on that note. Full details in
`data/metrics/replication_report.md`.

**What you learned:** **replication is what separates a plot from a finding.** One model gives
you a hypothesis; agreement across independent models gives you a result. This is the same
logic as reproducibility in science, applied to ML embeddings.

---

## 6. The hurdles — environment war stories (and the fixes)

This machine (macOS, repo in iCloud-synced `~/Desktop`, tight disk) fought us the entire way.
Each of these cost real debugging time and is now permanently solved. They're worth
understanding because they're the kind of thing no tutorial warns you about.

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | `uv run` stalls for minutes / spurious `ModuleNotFoundError` | `uv run` rebuilds the editable install every call; concurrent calls race | Call `~/latent-campus-venv/bin/python` with `PYTHONPATH=src` directly; the Makefile does this everywhere |
| 2 | `import polars/pyarrow/torch` hangs at **0% CPU** on first load | macOS **notarization check** (Gatekeeper/trustd) scans un-trusted native libs on first open per OS-cache window | `xattr -dr com.apple.quarantine <venv>` (cut polars 45s→0.25s cached); warm imports before launching |
| 3 | httpx stalls ~30s **per request** to CMU hosts | IPv6-first then slow IPv4 fallback | `PoliteFetcher` shells out to **curl** (does happy-eyeballs correctly, ~0.4s) |
| 4 | Reads time out with **Errno 60 / Operation timed out**; a symlink got renamed to `raw 2` mid-run | iCloud "Optimize Mac Storage" **evicts** large cached files to dataless placeholders under disk pressure | Move the raw cache **outside** the synced tree via env var `LATENT_CAMPUS_RAW_DIR`; a symlink inside the tree does NOT work |
| 5 | **torch import hung 40+ min at 0% CPU** | iCloud evicted the venv's 248 MB `libtorch_cpu.dylib` to an unrecoverable placeholder | Move the **whole venv outside iCloud** to `~/latent-campus-venv` (the big permanent fix) |
| 6 | HF model download stalled at exactly 192 MB, twice | Anonymous HuggingFace downloads are throttled | `hf auth login` (token cached outside iCloud) |
| 7 | Full embed swap-thrashed (process state `U`, 6 MB RSS) | batch-64 of the longest descriptions spiked unified memory on MPS | `--batch-size 16` |
| 8 | `df` barely moves after deleting GBs | macOS parks freed space as **purgeable**, reclaimed only under pressure; APFS local snapshots also hold deleted-file space | Expected behavior; `tmutil thinlocalsnapshots /` forces reclamation if needed |

**The meta-lesson:** on a constrained, cloud-synced machine, *the environment is part of the
engineering problem.* The two structural fixes — **relocating the raw cache and the venv
outside iCloud via indirection** — are the pattern: don't let an automatic system (iCloud) touch
files a long-running process depends on.

---

## 7. What each file does (the map)

```
configs/
  semesters.yaml         6 semesters to scrape
  sources.yaml           SOC + catalog URLs, Wayback timestamps, polite-scraping policy

src/latent_campus/
  common/
    config.py            paths (DATA_DIR, RAW_DIR — env-overridable), config loader
    schemas.py           pydantic Course/CourseOffering; normalize_course_id; generic-number regex
    fetch.py             PoliteFetcher — curl-based, cached, retrying HTTP with a JSONL log
  ingest/
    soc_fetch.py/parse   SOC dump fetch + parse (handles OLD 10-col and NEW 8-col layouts)
    catalog_fetch/parse  course-catalog pages → CatalogEntry
    details_parse.py     SOC courseDetails HTML → description/cross-listed/prereqs
  embed/
    text.py              clean_description + is_placeholder (corpus hygiene, stdlib-only)
  metrics/               ← the Phase 1 closer
    colleges.py          dept-code → college map (with your 2026-06-30 corrections)
    knn.py               k-NN from the embedding matrix (emb @ emb.T, exclude self)
    diversity.py         des(), lis(), rao_stirling() per-node scores
    nulls.py             shuffled-label permutation engine (kept for significance/later use)

scripts/
  scrape_courses.py          SOC dumps → offerings                     (Week 1)
  scrape_descriptions.py     catalog pages → catalog_descriptions      (Week 2)
  fill_descriptions_soc.py   SOC gap-fill → soc_descriptions           (Week 2)
  build_canonical.py         merge → courses.parquet                   (Week 2)
  embed_text.py              courses → data/embeddings/<slug>/          (Week 3, model-agnostic, --prefix)
  umap_text.py               embeddings → 2D umap_2d.{parquet,png}     (Week 3.5)
  umap_interactive.py        searchable/hover-able HTML map            (Week 3.5)
  nn_query.py                instant nearest-neighbor probe            (Week 3.5)
  interdisciplinarity.py     DES + LIS, size-residual ranking          (Phase 1 closer)
  compare_spaces.py          cross-space replication verdict           (Phase 1 closer)

data/  (gitignored)
  canonical/       courses.parquet, course_offerings.parquet, *_descriptions.parquet
  embeddings/<slug>/   embeddings.npy + text_embeddings.parquet + manifest.json  (×4 spaces)
  metrics/<slug>/      interdisciplinarity_{courses,departments}.parquet + report.md  (×4)
  metrics/replication_report.md    the cross-space verdict

~/latent-campus-data/raw/   (OUTSIDE iCloud) raw HTML caches + incremental resume logs

DECISIONS.md     the running log of every locked decision + methodology change
CLAUDE.md        project narrative + status + immediate-next-step for the next session
Makefile         every command (setup, scrape-*, embed-text, interdisciplinarity, compare-spaces, test, lint)
tests/           65 tests: parsers vs. real HTML fixtures, embed hygiene, metric math
```

**Stack:** uv (env), polars + pyarrow + duckdb (data), beautifulsoup4/lxml (parsing), pydantic
v2 (schemas), tenacity (retries), sentence-transformers + torch on MPS (embeddings),
umap-learn + matplotlib + plotly (viz), scipy (stats), pytest + ruff (quality).

---

## 8. What's in store — Phases 2+ (the roadmap)

Phase 1 built **one axis** (course text) of the atlas. The rest of the project adds the other
modalities and fuses them into a single graph, then paints it onto the physical campus.

**Immediately next — Week 4: Faculty.** Entity-resolve instructors against the CMU directory.
The hard rules (locked): a **Faculty node exists only when we can resolve a real person from
the directory**; non-faculty instructors get no node; and we **never** describe a faculty
member by the text of the courses they teach (that would leak the very course-text signal into
the faculty representation — circular). Remember instructor strings are comma-joined *last
names*, and F25/S26 have 0% instructor data, so recent faculty need FCE/SIO.

**Week 5 — Buildings & physical layout (PLG).** Bring in where things physically are, enabling
the second visualization mode (latent space *vs.* physical campus) and the **BID** (Building
Intellectual Diversity) metric — deferred from Phase 1 precisely because it needs buildings.
Hard rule: **no physical-proximity leakage into the training graph** — physical location is
something we *compare against*, never something we let shape the latent space.

**Week 6 — OpenAlex pilot.** A first look at research publications / labs (this is when the
project expands beyond courses to research output). Full integration is v1.5, not now.

**Weeks 7–12 — the model ladder & fusion.** Progress from the text space → a graph-smoothed
space → **metapath2vec** (a control baseline, explicitly *never* the final viz space) → an
**HGT** (Heterogeneous Graph Transformer) that fuses courses + faculty + departments +
buildings into one space. Plus **leakage checks** (Week 9) and the **two visualization modes**.
**Bridge Centrality** (betweenness on the fused graph) is deferred to here, because it needs the
fused graph and a *graph-rewiring* null, not the label null we used in Phase 1.

**The connective tissue:** every new modality reuses Phase 1's spine — the k-NN/diversity
math in `metrics/`, the permutation-null engine, the "evidence panel for every edge" principle,
and the discipline of *replicating findings across representations* before believing them.

---

## 9. The five ideas to walk away with

1. **A latent space turns meaning into geometry.** Once you have good embeddings, hard
   qualitative questions ("is this department a crossroads?") become simple geometric ones
   ("how far do its courses' neighbors scatter?").
2. **Confounds hide in plain sight, and the obvious fix can be wrong.** Department size faked
   an interdisciplinarity signal; the textbook correction (permutation z-scores) *failed* on a
   √n technicality; simple size-residuals worked. Always verify the correction.
3. **Replication is the difference between a plot and a finding.** Four independent models
   agreeing (+0.88) is what makes the result about CMU, not about bge.
4. **Checkpoints everywhere.** Parquet/npy at every stage is what made a 12-week, many-session,
   flaky-machine project actually resumable.
5. **On a constrained machine, the environment is part of the engineering.** The biggest
   time-sinks weren't ML — they were iCloud eviction and macOS notarization. Structural fixes
   (move state outside the sync boundary) beat repeated firefighting.
