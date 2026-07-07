"""PoliteFetcher POST support: cache-key logic + log-replay, no network."""

import json

import latent_campus.common.fetch as fetch_mod
from latent_campus.common.fetch import PoliteFetcher, encode_post_body, request_key


class TestEncodePostBody:
    def test_sorts_keys(self):
        a = encode_post_body({"b": "2", "a": "1"})
        b = encode_post_body({"a": "1", "b": "2"})
        assert a == b == "a=1&b=2"

    def test_urlencodes_values(self):
        assert encode_post_body({"search": "van der Berg"}) == "search=van+der+Berg"


class TestRequestKey:
    def test_get_key_is_bare_url(self):
        assert request_key("https://x/y", None) == "https://x/y"

    def test_post_key_includes_body(self):
        key = request_key("https://x/y", "a=1")
        assert key == "https://x/y#POST#a=1"
        assert key != request_key("https://x/y", "a=2")


class TestCacheReplay:
    def _make_fetcher(self, tmp_path, monkeypatch, records):
        monkeypatch.setattr(fetch_mod, "RAW_DIR", tmp_path)
        html_dir = tmp_path / "test" / "html"
        html_dir.mkdir(parents=True)
        log = tmp_path / "test" / "fetch_log.jsonl"
        with log.open("w") as f:
            for rec in records:
                content = html_dir / f"{rec['content_hash']}.html"
                content.write_text("cached")
                rec = {"status_code": 200, "content_path": str(content), **rec}
                f.write(json.dumps(rec) + "\n")
        return PoliteFetcher("test")

    def test_old_get_record_without_post_field_still_replays(self, tmp_path, monkeypatch):
        fetcher = self._make_fetcher(
            tmp_path, monkeypatch, [{"url": "https://x/get", "content_hash": "aaa"}]
        )
        result = fetcher.fetch("https://x/get")
        assert result.from_cache

    def test_post_record_replays_only_for_same_body(self, tmp_path, monkeypatch):
        fetcher = self._make_fetcher(
            tmp_path,
            monkeypatch,
            [{"url": "https://x/cgi", "post_data": "a=1&b=2", "content_hash": "bbb"}],
        )
        hit = fetcher.fetch("https://x/cgi", data={"b": "2", "a": "1"})
        assert hit.from_cache
        # a different body must not be served from the same entry
        assert request_key("https://x/cgi", encode_post_body({"a": "9"})) not in fetcher._url_index

    def test_get_and_post_to_same_url_are_distinct_entries(self, tmp_path, monkeypatch):
        fetcher = self._make_fetcher(
            tmp_path,
            monkeypatch,
            [
                {"url": "https://x/cgi", "content_hash": "ccc"},
                {"url": "https://x/cgi", "post_data": "q=1", "content_hash": "ddd"},
            ],
        )
        assert fetcher.fetch("https://x/cgi").content_hash == "ccc"
        assert fetcher.fetch("https://x/cgi", data={"q": "1"}).content_hash == "ddd"
