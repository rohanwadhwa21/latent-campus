# Decision Log — The Latent Campus

A running log of the meaningful decisions (system design, methodology, data) made
across this project, newest entries appended under each week. The aim: a future
reader (or future me) can reconstruct *why* the project is shaped the way it is,
not just *what* the code does.

Format per entry: **what** was decided, **why**, and (where it matters) **what it
rules out**. Locked decisions should not be relitigated without a new dated entry
explaining the reversal.

---

## Cross-cutting / methodology

- **Interdisciplinarity finding must replicate across ≥3 of 4 embedding spaces.**
  bge-large is "space #1"; mpnet, MiniLM, e5 come later as robustness checks. *Why:*
  a single embedding model's quirks could manufacture a spurious finding; replication
  across independent encoders is the guard against that. *Rules out:* trusting any
  result that lives in only one space.
- **No physical-proximity leakage into the training graph.** Building/room adjacency
  is a *target* to measure the latent space against, never a training signal. *Why:*
  if proximity leaks into training, "courses near each other are similar" becomes
  circular and the interdisciplinarity claim is meaningless.
- **Evidence panel for every edge.** Every claimed relationship in the viz must be
  traceable to its source. *Why:* portfolio credibility — no unfalsifiable edges.
- **uv + `.venv`, not conda.** *Why:* conda would fragment the Makefile/toolchain;
  the whole pipeline already standardizes on `.venv/bin/python` + `PYTHONPATH=src`.

## Week 1 — Course ingestion

- **Scrape CMU directly** (SOC nightly complete-schedule dump + course catalog);
  ScottyLabs/cmucourses used only as a cross-validation check. *Why:* control over
  freshness and provenance; third-party mirrors lag and can silently drop fields.
- **6 semesters: S26, F25, S25, F24, S24, F23** (skip summers). Canonical course
  description = most recent non-empty.
- **SOC dept codes are the canonical Department key**; filter to Pittsburgh campus
  (exclude Qatar).

## Week 2 — Descriptions

- **Catalog primary, SOC `courseDetails` gap-fill** (hybrid). *Why:* the catalog is
  clean and semester-independent but structurally excludes Heinz (90-95) and many
  grad/professional courses; SOC fills those gaps for live semesters.
- **Drop the 777 discontinued no-description courses** from the embedding corpus
  (list in `data/canonical/missing_descriptions.csv`). *Why:* all last-seen ≤ S25
  with no catalog entry and no live SOC source — genuinely gone; revisit via
  Wayback/FCE in Phase 2 only if needed.

## Week 3 — Text embeddings (in progress)

- **Primary text encoder: BAAI/bge-large-en-v1.5 (1024-dim).** *Why:* strong general
  English sentence encoder, well-benchmarked; "space #1 of ≥4."
- **bge plain-document embedding takes NO instruction prefix.** *Why:* bge's query
  prefix ("Represent this sentence for searching...") is for *retrieval queries only*;
  documents are embedded bare. Adding it would distort the document geometry.
- **Normalize embeddings to unit vectors.** *Why:* makes cosine similarity == dot
  product, and lets UMAP use the cosine metric cleanly downstream.
- **Corpus = described, non-generic courses, minus pure placeholders.** Drop x97/98/99
  generics (independent study/thesis — no real shared content) and placeholders
  (TBA/N/A/"coming soon"/bare-URL). Projected ~5,198 courses; the script's filter is
  the source of truth for the exact count. *Why:* junk descriptions produce junk
  vectors that distort neighborhoods.
- **The ~200-char DES/LIS minimum is a DOWNSTREAM metric-stage filter, NOT applied at
  embedding time** (2026-06-23). *Why:* short-but-real descriptions ("A one-hour
  private lesson per week for all music majors") are legitimate courses and belong in
  the atlas; the length cut only matters when computing the interdisciplinarity metric.
- **Clean descriptions with `html.unescape` + whitespace-normalize before embedding**
  (2026-06-23). *Why:* catalog/SOC text carries leftover HTML entities (`&amp;`,
  `&#39;`) and non-breaking spaces from extraction; left in, they become noise tokens.
- **The Python venv lives OUTSIDE the iCloud-synced repo, at `~/latent-campus-venv`**
  (2026-06-29). Referenced via a `VENV` variable in the Makefile; built with
  `UV_PROJECT_ENVIRONMENT=$(VENV) uv sync`. *Why:* the in-repo `.venv` (in
  iCloud-synced `~/Desktop`) was silently gutted by iCloud "Optimize Mac Storage" — at
  100% disk it evicted 1,554 files / ~874 MB of native libraries (incl. torch's 248 MB
  `libtorch_cpu.dylib`) to dataless placeholders. `brctl download` could not recover
  them (the upload likely never finished at 100% disk), so every torch import hung at
  0% CPU for 40+ min. This is the **same hazard, and same fix, already applied to the
  raw HTML cache** (`~/latent-campus-data` via `LATENT_CAMPUS_RAW_DIR`). *Rules out:*
  ever trusting a venv inside `~/Desktop`/`~/Documents`. A symlink inside the synced
  tree is NOT a substitute — iCloud renames it (documented in CLAUDE.md). *Also:* clear
  `com.apple.quarantine` on the venv after any install (`xattr -dr`) — fresh wheels
  carry the flag and trip the macOS notarization wall (`trustd`) at 0% CPU on import.
- **MPS encode runs at `--batch-size 16`, not the default 64** (2026-06-29). *Why:*
  sentence-transformers sorts inputs by length, so the first batch is the 64 *longest*
  descriptions; at batch-64 that spiked the unified (CPU+GPU shared) memory on this
  RAM-tight machine, the OS swapped the Python process out, and it thrashed in
  uninterruptible-sleep (`state=U`, ~6 MB RSS, 0 batches done in 11 min). Batch-16 keeps
  peak activation memory low — the full 5,179-course run then finished in ~8 min,
  accelerating from 4.8 s/batch (long texts) to ~4 batches/s (short texts). *Rules out:*
  assuming a batch size that's fine on a big-RAM/CUDA box transfers to MPS here.
- **HF model downloads require `hf auth login`** (2026-06-29). *Why:* anonymous HF Hub
  downloads are rate-capped — the 1.3 GB bge weights stalled dead at exactly 192 MB
  twice. An authenticated token (stored at `~/.cache/huggingface/token`, outside iCloud)
  lifts the cap; the resumable `.incomplete` blob means a restart continues, not restarts.

## Week 3.5 — First look (UMAP, done 2026-06-29)

- **Unsupervised UMAP with the cosine metric** for the first latent-space visualization.
  *Why:* embeddings are unit-normalized so cosine is the right geometry; unsupervised
  (no labels fed in) so any department clustering is discovered, not imposed — the honest
  way to ask "does the text space already separate disciplines?" Params: n_neighbors=15,
  min_dist=0.1, seed=42 (fixed seed → reproducible layout, forces single-thread).
- **View clipped to 1–99 percentile, data NOT clipped.** *Why:* a handful of degenerate
  embeddings land far out and squish the bulk; all points stay in `umap_2d.parquet`, only
  the PNG axes are bounded (133 off-frame, labeled). Don't drop the outlier *data* on a
  cosmetic basis.
- **Finding (first-look, proxy-level):** the text space is a **continuum, not disciplinary
  silos** — silhouette(cosine) ≈ 0 (−0.007 all-depts, +0.056 top-12, +0.064 after 200-char
  filter) despite visible local department arms. *Why it matters:* this is the *desired*
  precondition — a cleanly separated space would mean no interdisciplinarity to measure.
  The rigorous claim still requires the DES/LIS z-score-vs-shuffled-nulls metric; silhouette
  is only a sanity proxy here.
- **OPEN QUESTION (not yet decided):** boilerplate courses ("Independent Study", "Study
  Abroad", "Internship", "Reading and Research") recur across many depts with near-identical
  text and pile into the central mixing zone. They are NOT x97/98/99 generics. The locked
  200-char downstream filter removes most (9% of corpus is <200 char), but whether to also
  drop them at *embedding* time, or dedup cross-listed near-duplicates, is unresolved —
  revisit when building the DES/LIS metric.

### User-feedback findings from the interactive map (2026-06-30)

- **Department-size base-rate confound is REAL and large** — confirms why the metric must
  be null-model/rank-based, not raw. corr(log dept size, same-dept-NN-fraction) = **+0.68**.
  Big depts (Drama n=430 → 81% same-dept neighbors) look "coherent" largely because the
  pool is big; small depts (n=12 → 14%) can't accumulate same-dept neighbors regardless of
  true coherence. Dept sizes are very skewed: max=430, median=73, min=3 across 59 depts.
  *Implication:* a naive "% cross-dept neighbors" interdisciplinarity score is size-biased;
  the locked shuffled-label-null z-score / rank-based residual neutralizes it (null computed
  at each dept's own n). KEEP niche-but-substantive courses (they don't bias the
  size-controlled metric); only LOW-CONTENT boilerplate needs filtering.
- **UMAP 2-D distance is lossy — trust cosine/kNN, not visual distance for "are these
  close?"** Computer Graphics (15-362) vs Computer Vision (16-385) cosine = 0.796 (Vision
  is in Graphics' top-6 NN) yet they sit in different map regions: each is pulled into its
  own tighter cluster (graphics→geometry/rendering, vision→ML/recognition). Use the map for
  macro-structure; confirm pair closeness with `make nn`/cosine.
- **Cross-listed courses are NOT co-located, and that's correct** — 15-151 vs 21-128 (same
  course, cross-listed) cosine = 0.845 because their catalog *descriptions* are written for
  different audiences ("CS freshmen" vs "MCS math majors"). Ugrad/masters pair 15-463/15-663
  = 0.954. **OPEN: merge cross-listed IDs into one atlas node?** (schema tracks
  `cross_listed_ids`). Motivated example found; decide at graph-construction time.
- **College map corrections (user-verified 2026-06-30):** 86→MCS, 65→Dietrich, 67→Heinz;
  17→SCS, 66→Dietrich, 62→CFA confirmed. Remaining "Other" codes (04,14,32,49,52,53,69,99)
  left unmapped intentionally.
- **Niche ≠ low-content — KEEP niche-but-substantive courses.** "Bananas, Baseball &
  Borders" (79-288, 1568 ch) and "Queer Representations in Contemporary Lit from Japan"
  (82-275, 715 ch) are rich, real seminars. They are NOT filtered. Only boilerplate/thin
  descriptions get filtered.
- **Genuine STEM↔humanities bridges are RARE** (~4% of STEM+HUM courses have ≥8/15 cross
  neighbors; ~20% have ≥3) — confirms the user's visual impression. AND the top apparent
  bridges are a **labeling artifact: administrative college ≠ intellectual field** — most
  "humanities courses near STEM" are Statistics (dept 36, admin-Dietrich but intellectually
  STEM). Real bridges (e.g. 24-609 Entertainment Engineering) are rarer still. *Implication
  for the metric:* dept/college labels are imperfect proxies; the null-model/rank approach
  and care around quantitative-but-humanities-housed depts (Statistics, SDS) matter.

### Interdisciplinarity metric — built & first finding (2026-06-30)

- **Metrics: DES + LIS, ranked by SIZE-RESIDUAL (not z-score).** Built in
  `src/latent_campus/metrics/` (knn, diversity, nulls) + `scripts/interdisciplinarity.py`.
  **Methodology change from the approved plan, justified by the run:** the plan said
  "z-score against shuffled-label nulls," but the verification showed z-scores do NOT
  control size — the std of a group mean shrinks as 1/sqrt(n), so |z| scales with
  sqrt(size) and the confound persisted (corr stayed -0.57). Switched to **rank-based
  residuals** (regress dept-mean metric on log size, rank by residual) — the same
  approach the plan already prescribes for PLG. Result: corr(size, residual) = **+0.00**
  (was -0.64 raw). The `metrics/nulls.py` permutation engine is kept (tested, reusable)
  for *significance* and later modalities, just not as the ranking score.
- **First finding (bge space, k=10, 4,738 courses ≥200 char):** DES and LIS agree at
  **Spearman +0.81** (cross-metric robustness). Most interdisciplinary depts: **Engineering
  & Public Policy (19), Heinz policy (94/90/95/67), Tepper business (45), ISR/societal
  computing (17)** — exactly the units CMU designs to be interdisciplinary, rediscovered
  from text alone. Most insular: **Math (21), Physics (33), Computational Biology (02),
  Music performance (57), Modern Languages (82)** — deep self-contained fields. Nuance:
  "Computational Biology" ranks *insular* despite the name — a coherent field, not an
  interdisciplinary one. STILL TODO: replicate across ≥3 of 4 embedding spaces.
- **Caveat:** "Other"-college depts (04,14,32,69) have less meaningful LIS (Other is a
  grab-bag); their DES (dept-based) is fine.

### Possible project direction (user-originated 2026-06-30)

- **Course-discovery application of the atlas:** surface courses conceptually adjacent to a
  student's interests but administratively far from their home department ("cool courses a
  STEM major would never find"). A *use* of the interdisciplinarity space, not a competitor
  to the metric. Needs the niche courses KEPT (don't enrollment-filter them away). Enrollment
  data (for any popularity weighting) is Phase 2 (FCE/SIO) — not available yet.

### Cross-space replication — PHASE 1 CLOSED (2026-07-01)

- **The finding replicates across 4 independent encoders → it is about CMU, not bge.**
  Embedded the *identical* 5,179-course corpus with 3 more models beside bge:
  **all-mpnet-base-v2 (768-d), all-MiniLM-L6-v2 (384-d), intfloat/e5-large-v2 (1024-d).**
  All model-agnostic via `scripts/embed_text.py --model <hf> --batch-size 16`; outputs in
  `data/embeddings/<slug>/`. e5 needed a **uniform `--prefix "query: "`** (added an opt-in
  `--prefix` flag, default empty so bge/mpnet/MiniLM are unchanged) — per e5's card, symmetric
  similarity/clustering tasks use the `query:` prefix on every text, not `passage:`.
- **Per-space metric** re-run with `interdisciplinarity.py --model-slug <slug>` (outputs now
  **namespaced** to `data/metrics/<slug>/` so all four survive for comparison). Every space
  independently reproduced: size confound corr(size, residual) ≈ 0.00, DES↔LIS Spearman
  **+0.79 … +0.83**.
- **Comparison (`scripts/compare_spaces.py` → `data/metrics/replication_report.md`):**
  - **Mean pairwise Spearman(des_resid) = +0.88** (range +0.78 mpnet↔e5 … +0.94
    bge↔MiniLM / mpnet↔MiniLM). Strong ordering agreement across architectures/sizes.
  - **19 depts replicate** (top-20 by des_resid in ≥3 of 4; the locked protocol). The
    headline units are **all 4/4**: Heinz (94/90/95/67), Tepper (45), **EPP (19)**, SCS (17).
    Insular side likewise stable: Math (21), MCS/CompBio (33/09/02), a Tepper sub-unit (46),
    CFA (57).
  - Also-replicating grab-bag/`Other` codes (04/14/98-StuCo/99/11) escape their own label
    partly *because* those labels are heterogeneous — expected, and why the academic
    headline (EPP/Heinz/Tepper/SCS) is the defensible claim.
- **Robustness even in the weakest model:** MiniLM (384-d, deliberately tiny) reproduces the
  ranking → the signal is in the course text, not in any one model's capacity.
- Full suite green after the script edits: **65 passed**. Known cosmetic-only bug: the
  compare-script's stdout "tags" print `bge,all,all,e5` (mpnet & MiniLM both start `all-`);
  the persisted report uses counts, unaffected.
- **⇒ Phase 1 is CLOSED.** Text atlas + interdisciplinarity metric built, verified, and
  replicated. Next: **Week 4 — faculty entity-resolution.**

---

## Week 4 — Faculty entity-resolution (Phase 2, started 2026-07-06)

- **Resolution source: directory.andrew.cmu.edu, queried by surname via the ADVANCED
  search** (`POST /index.cgi`, `last_name=` field). *Why:* Task-0 probes showed (a)
  anonymous search is name-only — search-by-department needs Shibboleth; (b) BASIC search
  matches substrings anywhere in the name ("Lee" matches first-name "Leen") — noise; the
  advanced field is a whole-word match on the surname, which is exactly the ER semantics.
  *Rules out:* per-department directory browsing without login.
- **Results are HARD-CAPPED at 200** ("You have reached the search limit of 200 results" —
  Lee/Li/Wu/Zhang hit it; Smith=88 doesn't). A capped pool is truncated and **can never
  prove uniqueness**, so capped surnames NEVER auto-resolve — they go to the manual queue
  (`faculty_ambiguous.csv`). First-letter splitting can't beat the cap (advanced fields are
  whole-word matches: `first_name=a` returns nothing).
- **Single-hit searches return the person DETAIL page directly** (no results table) —
  parser handles three shapes: multi (table), single (detail), empty (bare form).
- **Candidate filter: affiliation ∈ {Faculty, Staff}.** *Why:* adjunct instructors appear
  as Staff ("Music Extension - Adjunct Instructor"); Students/Sponsored never get nodes
  (locked Week-0 decision: non-faculty instructors get no node).
- **Acceptable-use compliance:** the directory forbids mailing/solicitation use. We store
  only name, andrew_id, affiliation, HR job title, departments, campus room — **no email,
  no phone**, by schema design.
- **Detail pages are the authoritative dept/title source** (line-separated), not the
  results-table cell (comma-joined, ambiguous when a dept name contains a comma). Detail
  pages fetched only for Faculty/Staff hits (pre-filtered from the table).
- **Resolution unit = (surname, offering-dept) pair**, methods ranked:
  `dept-unique` (offering dept ∈ candidate's mapped SOC codes, exactly one such candidate)
  > `global-unique` (surname has exactly one Faculty/Staff candidate at all of CMU).
  ≥2 matches → ambiguous → manual queue. Methods are recorded on every edge (evidence
  panel); `global-unique` is droppable independently if the labeled-pair precision check
  (~100 pairs, ~99% target) shows it's weak.
- **HR dept name → SOC code mapping is a hand-verified config**
  (`configs/dept_directory_map.yaml`), seeded from observed names
  (`resolve_faculty.py --report-unmapped`). HR names are messy/truncated ("SEI Ai Do") —
  exact-string keys, null = non-teaching unit.
- **Surname keys are casefolded** in resolution (SOC has case variants "AAZAM"/"Aazam");
  raw tokens are preserved on edges as evidence.
- **PoliteFetcher gained form-POST support** (curl `--data`); cache key = URL + canonical
  sorted body, so GET caches/logs are untouched and identical logical POSTs dedupe.
- **F25/S26 TEACHES edges deferred** (0% instructor coverage in the public SOC; FCE/SIO
  needs authenticated export — user decision pending, default defer).

### Week 4 first full run (2026-07-07) — pending user verification

- **Bulk fetch complete:** 2,294 surnames → 1,115 single-hit / 850 multi / 329 empty
  (instructors gone from the directory since F23 — expected churn), only **11 capped**;
  **3,140 distinct Faculty/Staff candidates**.
- **Dept map drafted programmatically** (440 entries: 66 mapped incl. alias variants, 374
  null admin/SEI/Qatar units), 8 entries flagged `# TODO verify code` (III=49?, Ni=86?,
  Athletics=69?, NavalROTC=32?). **Umbrella mappings:** Heinz HR units → all Heinz codes
  {90,91,92,93,94,95} (92 was initially omitted — caught by dept-92's 45% resolution rate,
  fixed); Tepper → {45,46,47,70,73} (**no separate Economics HR unit exists**).
- **Resolution result:** 3,594 (surname, dept) pairs → **2,337 resolved (65%)**
  [1,704 dept-unique + 633 global-unique], 468 ambiguous + 124 capped → manual queue
  (592 pairs), 665 no-match. **Edges: 23,082 (79.1% of the 29,187 tokens), 1,696 faculty
  nodes (1,257 Faculty + 439 Staff), 1,023 with building codes.** Spot checks pass (Kosbie
  → 62×15-112; Drama 54-101; Heinz 94-216 all correct people).
- Low-resolution depts are structurally expected: 98 StuCo (student-taught), 32 ROTC,
  62 BXA, 38/39/52/65/66 college-wide codes (deliberately no HR mapping — deans-office
  staff must not create false dept-unique matches).
- **GATE before accepting:** user reviews the 8 TODO mappings + labels
  `data/canonical/faculty_label_sample.csv` (100 pairs, ~99% precision target,
  dept-unique and global-unique evaluated separately).
