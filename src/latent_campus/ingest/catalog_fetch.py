"""Fetch CMU course-catalog department pages (configs/sources.yaml:course_catalog)."""

from latent_campus.common.config import load_config
from latent_campus.common.fetch import FetchResult, PoliteFetcher


def fetch_all_catalog_pages() -> list[FetchResult]:
    cat = load_config("sources")["course_catalog"]
    base = cat["base_url"].rstrip("/")
    fetcher = PoliteFetcher("catalog")
    try:
        return [fetcher.fetch(base + path) for path in cat["course_pages"]]
    finally:
        fetcher.close()
