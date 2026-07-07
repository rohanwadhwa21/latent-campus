"""Parse CMU course-catalog department pages into description records.

Each department /courses/ page is a <dl> of "courseblock" entries:

    <dt class="keepwithnext">18-059 Introduction to Amateur Radio</dt>
    <dd>Spring: 3 units<br />A technical introduction to ...</dd>

The <dt> gives course_id + title; the <dd> opens with "<terms>: <units>"
then a <br/> and the prose description.
"""

import re

from bs4 import BeautifulSoup
from pydantic import BaseModel

from latent_campus.common.schemas import COURSE_ID_RE, normalize_course_id

# "18-059 Introduction to Amateur Radio" -> ("18-059", "Introduction ...")
DT_RE = re.compile(r"^\s*(\d{2}-?\d{3})\s+(.*)$", re.S)
# "Fall and Spring: 12 units" / "Spring: 3 units" / "Intermittent: 9 units"
HEAD_RE = re.compile(r"^(?P<terms>.*?):\s*(?P<units>[\d.]+|VAR)\s*units?\b", re.IGNORECASE)


class CatalogEntry(BaseModel):
    course_id: str
    title: str
    description: str
    offered_terms: str | None = None  # "Fall and Spring", as printed
    units_text: str | None = None  # "12", "VAR"


def parse_catalog_page(html: str) -> list[CatalogEntry]:
    soup = BeautifulSoup(html, "lxml")
    entries: list[CatalogEntry] = []
    for dt in soup.select("dt.keepwithnext"):
        m = DT_RE.match(dt.get_text(" ", strip=True))
        if not m:
            continue
        course_id = normalize_course_id(m.group(1))
        if not COURSE_ID_RE.match(course_id):
            continue
        title = re.sub(r"\s+", " ", m.group(2)).strip()

        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        offered_terms = units_text = None
        # split on the first <br/>: head = "terms: units", rest = description
        if dd.br is not None:
            head = "".join(str(s) for s in dd.br.previous_siblings)
            head_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", head)).strip()
            if hm := HEAD_RE.match(head_text):
                offered_terms = hm.group("terms").strip() or None
                u = hm.group("units")
                units_text = None if u.upper() == "VAR" else u
            parts = []
            for node in dd.br.next_siblings:
                text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else str(node)
                if text.strip():
                    parts.append(text.strip())
            description = " ".join(parts)
        else:
            description = dd.get_text(" ", strip=True)

        description = re.sub(r"\s+", " ", description).strip()
        if not description:
            continue
        entries.append(
            CatalogEntry(
                course_id=course_id,
                title=title,
                description=description,
                offered_terms=offered_terms,
                units_text=units_text,
            )
        )
    return entries
