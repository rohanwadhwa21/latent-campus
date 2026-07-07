"""SOC-specific fetching: resolve a semester to its nightly-dump URL.

The polite/cached/resumable mechanics live in common.fetch.PoliteFetcher;
this module only adds SOC's semester -> URL resolution (live asset or
Wayback snapshot). Endpoints live in configs/sources.yaml.
"""

from latent_campus.common.config import load_config
from latent_campus.common.fetch import FetchResult, PoliteFetcher

# re-exported so existing imports (RAW_DIR, FetchResult) keep working
_fetcher_dir = PoliteFetcher  # noqa: F401 (documentation anchor)


def semester_url(semester: str) -> str:
    """Resolve a semester to its nightly-dump URL (live asset or Wayback snapshot).

    Wayback URLs use the `id_` flag to get the original page bytes without
    the archive toolbar injected.
    """
    cfg = load_config("sources")
    soc = cfg["soc"]
    try:
        src = soc["semester_sources"][semester]
    except KeyError:
        raise ValueError(f"no source configured for semester {semester!r}") from None
    asset = soc["complete_schedule"][src["cycle"]]
    if src["kind"] == "live":
        return asset
    return f"{cfg['wayback_prefix']}/{src['timestamp']}id_/{asset}"


def fetch_semester(semester: str) -> FetchResult:
    """Fetch the complete-schedule dump for one semester (single file)."""
    fetcher = PoliteFetcher("courses")
    try:
        return fetcher.fetch(semester_url(semester))
    finally:
        fetcher.close()


def course_details_url() -> str:
    return load_config("sources")["soc"]["course_details"]

