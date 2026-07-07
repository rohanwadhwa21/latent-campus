"""Description text cleaning + corpus hygiene for the embedding pipeline.

Stdlib-only on purpose: no polars/torch import here so the filtering rules are
fast to unit-test and the heavy embedding script (scripts/embed_text.py) can
reuse them. The two public functions decide, per course description:

  clean_description(raw)  -> normalized text (HTML entities decoded, whitespace
                             collapsed). Always call before is_placeholder.
  is_placeholder(cleaned) -> True if the cleaned text carries no real content
                             ("TBA", "N/A", a bare URL, ...) and the course
                             should be DROPPED from the embedding corpus.

Per the locked Week-3 decision, the ~200-char DES/LIS minimum is NOT applied
here — that is a downstream *metric*-stage filter. Here we only strip genuine
non-content so the bge embeddings aren't polluted by junk vectors.
"""

import html
import re

# Cleaned, lowercased, trailing-punctuation-stripped descriptions equal to any
# of these are pure placeholders the SOC/catalog uses for "no description yet".
PLACEHOLDER_TOKENS = frozenset(
    {
        "",
        "-",
        "–",  # en dash
        "—",  # em dash
        ".",
        "tba",
        "tbd",
        "tbc",
        "n/a",
        "na",
        "none",
        "to be announced",
        "to be determined",
        "to be decided",
        "to be confirmed",
    }
)

# A description that is *only* a URL (e.g. "Course Website: https://..." with no
# prose) carries no embeddable content. Match a leading optional label.
_URL_ONLY_RE = re.compile(
    r"^(course\s*website:?\s*)?https?://\S+$", re.IGNORECASE
)

_WS_RE = re.compile(r"\s+")


def clean_description(raw: str | None) -> str:
    """Decode HTML entities and collapse whitespace; return '' for None.

    Catalog/SOC text arrives with leftover entities ('&amp;', '&#39;') and
    non-breaking spaces from HTML extraction. html.unescape fixes the standard
    entity cases; we then normalize all whitespace runs to single spaces so
    length thresholds and equality checks are meaningful.
    """
    if raw is None:
        return ""
    text = html.unescape(raw)
    # Normalize non-breaking / zero-width spaces that survive unescape.
    text = text.replace("\xa0", " ").replace("​", "")
    return _WS_RE.sub(" ", text).strip()


def is_placeholder(cleaned: str) -> bool:
    """True if a cleaned description is non-content and should be dropped.

    Expects the output of clean_description. Checks: empty, a known placeholder
    token (case/punctuation-insensitive), a "Coming soon"-style stub, or a bare
    URL with no surrounding prose.
    """
    if not cleaned:
        return True
    norm = cleaned.lower().strip().rstrip(".").strip()
    if norm in PLACEHOLDER_TOKENS:
        return True
    if norm.startswith("coming soon"):
        return True
    if _URL_ONLY_RE.match(cleaned):
        return True
    return False
