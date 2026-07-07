"""Parse a SOC courseDetails page into a description record.

Used to fill description gaps the public course catalog can't reach —
notably Heinz College (90-95) and other graduate/professional courses,
which have no /courses/ page in the catalog. Keyed to our exact course
IDs and only valid for courses offered in a live semester.

Page structure (verified Task 0):
    <div id="course-detail-description"><h4>Description:</h4><p>...</p></div>
    <dl><dt>Cross-Listed Courses</dt><dd>None | 15-... 16-...</dd></dl>
    <dl><dt>Prerequisites</dt><dd>None | ...</dd></dl>

A non-existent (course, semester) pair returns an application-error page
with no description div -> parse_course_details returns None.
"""

import re

from bs4 import BeautifulSoup
from pydantic import BaseModel

from latent_campus.common.schemas import normalize_course_id

COURSE_ID_IN_TEXT = re.compile(r"\b\d{2}-?\d{3}\b")


class DetailsEntry(BaseModel):
    course_id: str
    description: str
    cross_listed_ids: list[str] = []
    prerequisites: str | None = None


def _dd_for(soup, label: str) -> str | None:
    for dt in soup.find_all("dt"):
        if dt.get_text(strip=True).lower().startswith(label.lower()):
            dd = dt.find_next_sibling("dd")
            if dd is not None:
                text = re.sub(r"\s+", " ", dd.get_text(" ", strip=True)).strip()
                return text or None
    return None


def parse_course_details(html: str, course_id: str) -> DetailsEntry | None:
    if "error has occurred in this application" in html:
        return None
    soup = BeautifulSoup(html, "lxml")
    desc_div = soup.find(id="course-detail-description")
    if desc_div is None:
        return None
    p = desc_div.find("p")
    description = re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip() if p else ""
    if not description:
        return None

    cross_raw = _dd_for(soup, "Cross-Listed Courses")
    cross_ids: list[str] = []
    if cross_raw and cross_raw.lower() != "none":
        for m in COURSE_ID_IN_TEXT.findall(cross_raw):
            cid = normalize_course_id(m)
            if cid != course_id and cid not in cross_ids:
                cross_ids.append(cid)

    prereq = _dd_for(soup, "Prerequisites")
    if prereq and prereq.lower() == "none":
        prereq = None

    return DetailsEntry(
        course_id=course_id,
        description=description,
        cross_listed_ids=cross_ids,
        prerequisites=prereq,
    )
