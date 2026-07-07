# Targets call the venv Python directly. `uv run` rebuilds the editable
# install on every invocation and can stall on this setup, so we avoid it.
# Run `make setup` once to create .venv.
# Raw HTML cache lives outside the iCloud-synced repo (see README "Layout").
# Override LATENT_CAMPUS_RAW_DIR to relocate it.
LATENT_CAMPUS_RAW_DIR ?= $(HOME)/latent-campus-data/raw
# The venv ALSO lives outside the iCloud-synced repo tree. iCloud "Optimize Mac
# Storage" evicts large native libs (e.g. torch's 248MB libtorch_cpu.dylib) to
# dataless placeholders under disk pressure; importing them then hangs at 0% CPU
# streaming from iCloud (or is unrecoverable if the upload never finished). Same
# APFS volume, just not synced. Build with `make setup`; override VENV to relocate.
VENV ?= $(HOME)/latent-campus-venv
PY := PYTHONPATH=src LATENT_CAMPUS_RAW_DIR=$(LATENT_CAMPUS_RAW_DIR) $(VENV)/bin/python
RUFF := $(VENV)/bin/ruff

.PHONY: setup scrape-courses scrape-all scrape-descriptions fill-descriptions-soc \
        build-canonical embed-text umap-text umap-interactive nn interdisciplinarity \
        compare-spaces scrape-directory resolve-faculty validate test lint

setup:
	UV_PROJECT_ENVIRONMENT=$(VENV) uv sync

scrape-courses:  ## Week 1: most recent semester only
	$(PY) scripts/scrape_courses.py

scrape-all:      ## all configured semesters
	$(PY) scripts/scrape_courses.py --all

scrape-descriptions:    ## catalog pages -> catalog_descriptions.parquet
	$(PY) scripts/scrape_descriptions.py

fill-descriptions-soc:  ## SOC courseDetails gap-fill -> soc_descriptions.parquet (~90 min)
	$(PY) scripts/fill_descriptions_soc.py

build-canonical:
	$(PY) scripts/build_canonical.py

embed-text:     ## Week 3: bge-large embeddings of described courses (downloads ~1.3GB on first run)
	$(PY) -u scripts/embed_text.py

umap-text:      ## Week 3.5: unsupervised UMAP of the text embeddings -> umap_2d.{parquet,png}
	$(PY) -u scripts/umap_text.py

nn:             ## probe the space by hand: make nn Q="machine learning"
	$(PY) scripts/nn_query.py "$(Q)"

umap-interactive:  ## hover-able UMAP -> umap_2d.html (open in a browser)
	$(PY) scripts/umap_interactive.py

interdisciplinarity:  ## Phase 1 closer: DES + LIS metrics, size-controlled, ranked (pass SLUG=<model>)
	$(PY) -u scripts/interdisciplinarity.py $(if $(SLUG),--model-slug $(SLUG),)

compare-spaces:  ## cross-space replication: pairwise Spearman + top-20 in >=3 of 4 -> replication_report.md
	$(PY) -u scripts/compare_spaces.py

scrape-directory:  ## Week 4: CMU directory lookup for every instructor surname (~2.5h first run; resumable)
	$(PY) -u scripts/scrape_directory.py

resolve-faculty:  ## Week 4: surname+dept -> directory person; faculty.parquet + course_faculty.parquet
	$(PY) -u scripts/resolve_faculty.py

validate:
	$(PY) scripts/validation_report.py

test:
	$(PY) -m pytest -q

lint:
	$(RUFF) check src scripts tests
