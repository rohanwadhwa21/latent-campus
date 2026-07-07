"""Polite, cached, resumable HTTP fetcher shared by all ingest sources.

Uses curl via subprocess rather than a Python HTTP client. On this network,
httpx/httpcore stalls ~30s per request against CMU hosts (IPv6-first then
slow IPv4 fallback); curl does happy-eyeballs correctly and is sub-second.

Behavior:
  - >= min_seconds_between_requests (+ jitter) between live requests
  - retries on curl transport failure (connect/timeout) with backoff;
    HTTP status codes (incl. 5xx) are NOT retried — the body is saved and
    the caller's parser decides (the SOC returns 500 for non-existent
    course/semester pairs, which retrying would never fix)
  - raw bytes cached to data/raw/<source>/html/<sha256>.html; any URL already
    fetched in a prior run is served from cache and not refetched
  - every network attempt appended to data/raw/<source>/fetch_log.jsonl

One instance per source name ("courses", "catalog", "details"). The fetch
log is the resume index: it maps already-fetched URLs to their cached file.
"""

import hashlib
import json
import random
import subprocess
import time
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from latent_campus.common.config import RAW_DIR, scraping_policy

PARSER_VERSION = "0.3.0"  # curl-based fetcher, GET + form POST


def encode_post_body(data: dict[str, str]) -> str:
    """Canonical urlencoded form body: sorted keys, so the same logical
    request always produces the same cache key regardless of dict order."""
    return urllib.parse.urlencode(sorted(data.items()))


def request_key(full_url: str, post_body: str | None) -> str:
    """Cache-index key. GETs keep the bare URL (backwards compatible with
    existing fetch logs); POSTs append the canonical body."""
    return full_url if post_body is None else f"{full_url}#POST#{post_body}"


class TransportError(Exception):
    """curl failed at the transport level (connect/timeout); safe to retry."""


@dataclass
class FetchResult:
    url: str
    content_path: Path
    content_hash: str
    from_cache: bool


class PoliteFetcher:
    def __init__(self, source: str) -> None:
        policy = scraping_policy()
        self._min_interval = float(policy["min_seconds_between_requests"])
        self._jitter = float(policy["jitter_seconds"])
        self._timeout = float(policy["timeout_seconds"])
        self._ua = policy["user_agent"]
        self._last_request_at = 0.0
        self.raw_dir = RAW_DIR / source
        self.html_dir = self.raw_dir / "html"
        self.fetch_log = self.raw_dir / "fetch_log.jsonl"
        self.html_dir.mkdir(parents=True, exist_ok=True)
        # request_key -> content_path index from the log, so reruns are no-ops.
        # Old log records have no post_data field and replay as plain-URL keys.
        self._url_index: dict[str, str] = {}
        if self.fetch_log.exists():
            with self.fetch_log.open() as f:
                for line in f:
                    rec = json.loads(line)
                    if rec.get("status_code") == 200 and rec.get("content_path"):
                        key = request_key(rec["url"], rec.get("post_data"))
                        self._url_index[key] = rec["content_path"]

    def fetch(
        self,
        url: str,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        force: bool = False,
    ) -> FetchResult:
        """GET by default; pass `data` for a form POST (urlencoded body)."""
        full_url = url + ("?" + urllib.parse.urlencode(params) if params else "")
        body = encode_post_body(data) if data is not None else None
        if not force and (cached := self._url_index.get(request_key(full_url, body))):
            path = Path(cached)
            if path.exists():
                return FetchResult(full_url, path, path.stem, from_cache=True)
        return self._fetch_live(full_url, body)

    @retry(
        retry=retry_if_exception_type(TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _fetch_live(self, url: str, post_body: str | None = None) -> FetchResult:
        self._throttle()
        started = time.monotonic()
        key = request_key(url, post_body)
        tmp = self.html_dir / f".tmp_{hashlib.sha1(key.encode()).hexdigest()}"
        record = {
            "url": url,
            "post_data": post_body,
            "fetched_at": datetime.now(UTC).isoformat(),
            "status_code": None,
            "content_hash": None,
            "content_path": None,
            "duration_ms": None,
            "error": None,
            "parser_version": PARSER_VERSION,
        }
        try:
            argv = ["curl", "-sS", "-L", "--max-time", str(int(self._timeout)),
                    "-A", self._ua, "-o", str(tmp), "-w", "%{http_code}"]
            if post_body is not None:
                argv += ["--data", post_body]
            proc = subprocess.run(
                argv + [url],
                capture_output=True, text=True, timeout=self._timeout + 15,
            )
            record["duration_ms"] = round((time.monotonic() - started) * 1000)
            if proc.returncode != 0:
                record["error"] = f"curl exit {proc.returncode}: {proc.stderr.strip()[:200]}"
                raise TransportError(record["error"])
            status = int(proc.stdout.strip() or 0)
            record["status_code"] = status
            content = tmp.read_bytes() if tmp.exists() else b""
            content_hash = hashlib.sha256(content).hexdigest()
            path = self.html_dir / f"{content_hash}.html"
            tmp.replace(path)
            record["content_hash"] = content_hash
            record["content_path"] = str(path)
            if status == 200:
                self._url_index[key] = str(path)
            return FetchResult(url, path, content_hash, from_cache=False)
        except subprocess.TimeoutExpired as exc:
            record["error"] = f"curl timeout after {self._timeout}s"
            raise TransportError(record["error"]) from exc
        finally:
            tmp.unlink(missing_ok=True)
            self._log(record)

    def _throttle(self) -> None:
        wait = self._min_interval + random.uniform(0, self._jitter)
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < wait:
            time.sleep(wait - elapsed)
        self._last_request_at = time.monotonic()

    def _log(self, record: dict) -> None:
        with self.fetch_log.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def close(self) -> None:  # kept for API compatibility (no client to close)
        pass
