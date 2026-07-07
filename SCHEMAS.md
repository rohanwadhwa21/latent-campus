# Parquet schemas

Canonical data contracts. Pydantic source of truth: `src/latent_campus/common/schemas.py`.

## data/canonical/courses.parquet

One row per unique catalog course (semester-independent). Cross-listed courses
are a **single canonical row** with `cross_listed_ids` — never duplicated.

| column | type | notes |
|---|---|---|
| course_id | str | `"15-440"` — canonical key, `dept-number` |
| dept_code | str | `"15"` — SOC dept code, canonical Department key |
| course_number | str | `"440"` |
| title | str | most recent semester's title |
| description | str? | from course catalog, else SOC courseDetails; null if neither has it |
| description_source | str | `catalog` (undergrad-oriented depts) \| `soc` (grad/Heinz gap-fill via courseDetails) \| `none` |
| units | float? | null when variable |
| cross_listed_ids | list[str] | other course_ids merged into this canonical course |
| is_generic | bool | x97/x98/x99 independent-study/thesis shells; excluded from DES/LIS |
| first_seen_semester | str | e.g. `F23` |
| last_seen_semester | str | e.g. `S26` |

## data/canonical/course_offerings.parquet

One row per (course, semester, section).

| column | type | notes |
|---|---|---|
| offering_id | str | `"15-440_F25_A"` |
| course_id | str | FK to courses |
| semester | str | `[FS]\d\d`; summers excluded by design |
| section | str | as printed |
| title | str | title as printed that semester (may drift) |
| instructor_names_raw | list[str] | **last names only**, split from SOC's comma-joined string; empty for F25+ (column removed from public SOC) |
| instructor_ids | list[str] | empty until Phase 2 entity resolution |
| mini | int? | 1 / 2 / null — currently always null; the complete-schedule dump has no Mini column (title-suffix heuristic only) |
| units_raw | str? | `"12.0"`, `"VAR"`, ... |
| meetings | list[struct] | see Meeting |

### Meeting struct

| field | type | notes |
|---|---|---|
| days | str? | `"MW"` |
| begin / end | str? | `"09:30AM"` |
| room | str? | verbatim, `"GHC 4401"` |
| building_code | str? | parsed, `"GHC"` — free course→building signal for Phase 3 |
| campus | str? | used to filter to Pittsburgh |

## Intermediate description tables

Two source-specific tables, merged into `courses.parquet` by `build_canonical`
(catalog wins, SOC fills the rest):

- **data/canonical/catalog_descriptions.parquet** — from coursecatalog.web.cmu.edu
  department `/courses/` pages. `course_id, title, description, offered_terms,
  units_text`. Covers undergrad-oriented departments; **excludes Heinz College
  (90-95) and many graduate/professional courses** (no `/courses/` page exists).
- **data/canonical/soc_descriptions.parquet** — from the SOC `courseDetails`
  endpoint, fetched only for catalog-gap courses offered in a live semester
  (S26/F25). `course_id, description, cross_listed_ids, prerequisites`. Fills
  the grad/Heinz gap and is the source for `cross_listed_ids`.

## data/canonical/faculty.parquet (Week 4)

One row per **directory-resolved** person. A Faculty node exists ONLY on a
confident CMU-directory match; unresolved instructors get no node (their raw
surname stays on the offering). Leakage rule: attributes come from the
directory only — never from taught-course text. No email/phone by design
(directory acceptable-use).

| column | type | notes |
|---|---|---|
| faculty_id | str | Andrew ID — stable canonical key |
| display_name | str | directory display name |
| affiliation | str | `Faculty` \| `Staff` (teaching staff, e.g. adjunct instructors) |
| job_titles | list[str] | HR titles, verbatim |
| hr_departments | list[str] | directory affiliation lines, verbatim |
| dept_codes | list[str] | SOC codes via `configs/dept_directory_map.yaml` |
| campus_room | str? | `"GHC 5001"` — faculty→building signal for Week 5 |
| building_code | str? | parsed from campus_room when well-formed |

## data/canonical/course_faculty.parquet (Week 4)

One row per (offering, resolved instructor token) TEACHES edge, with evidence.
F23–S25 only (public SOC has no instructors from F25 on).

| column | type | notes |
|---|---|---|
| offering_id | str | FK to course_offerings |
| course_id / semester | str | denormalized for convenience |
| faculty_id | str | FK to faculty |
| surname_token | str | the raw instructor token that produced this edge |
| dept_code | str | offering dept used to disambiguate |
| match_method | str | `dept-unique` (dept ∩ directory dept) \| `global-unique` (surname unique among Faculty/Staff) |

## Directory intermediates (Week 4)

- **data/canonical/directory_candidates.parquet** — every Faculty/Staff person
  returned by a surname query: `query_surname, query_capped, andrew_id,
  display_name, affiliation, job_titles, departments, campus_room, guid`.
- **data/canonical/directory_queries.parquet** — one row per queried surname
  (`surname, kind, capped, n_people`); lets the resolver distinguish a real
  no-match from a never-queried surname. Searches are HARD-CAPPED at 200
  results; capped surnames can't prove uniqueness → manual queue.
- **data/canonical/faculty_ambiguous.csv** — manual-review queue
  (ambiguous + capped pairs with their candidate pools).

## data/raw/{courses,catalog,details,directory}/fetch_log.jsonl

Append-only fetch provenance (JSONL, not parquet — it's a log).

`url, post_data, fetched_at, status_code, content_hash, content_path, duration_ms, error, parser_version`

`post_data` (v0.3.0+) is the urlencoded form body for POST requests (the
directory search is a POST); it is part of the cache key, so the same URL with
different bodies caches separately. Older GET-only records replay unchanged.

Raw HTML cached at `data/raw/<source>/html/<sha256>.html`; reruns hit the cache.
The fetcher (`common/fetch.py`) shells out to **curl**, not a Python HTTP
client — httpx stalls ~30s/request against CMU hosts (IPv6-first fallback).
