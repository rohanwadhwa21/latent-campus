"""Parse CMU directory (directory.andrew.cmu.edu) search-result pages.

The resolution source for Week 4 faculty entity-resolution. Anonymous search
is name-only (POST /index.cgi); a query returns one of three page shapes
(verified 2026-07-06, Task 0):

  - zero hits   -> the bare search-form page (no results markup at all)
  - one hit     -> the person DETAIL page directly:
                     <h1 id="listing">David Scott Kosbie (Faculty)</h1>
                     <b>Andrew UserID:</b> koz<br/>
                     <h2>Contact Information</h2><b>On Campus:</b> GHC 5001...
                     <h2>Departmental Affiliations</h2>
                     <b>Job Title According to HR:</b><br/>Teaching Professor...
                     <b>Department with which this person is affiliated:</b>...
  - many hits   -> <table id="sortabletable"> with columns
                     Last | First | AndrewID | Affiliation | Department
                   and per-person guid links (index.cgi?searchtype=guid&guid=...)

Results are HARD-CAPPED at 200 ("You have reached the search limit of 200
results") — capped pages are flagged so those surnames go to the manual queue.

Acceptable-use compliance: we deliberately do NOT extract email or phone —
only name, andrew_id, affiliation, HR job title, departments, campus room.
"""

import re

from bs4 import BeautifulSoup, NavigableString, Tag
from pydantic import BaseModel

CAP_MESSAGE = "search limit of 200 results"
GUID_RE = re.compile(r"guid=([0-9A-Fa-f-]+)")
H1_NAME_RE = re.compile(r"^(?P<name>.*?)\s*\((?P<affiliation>[^)]*)\)\s*$")

# Department cells comma-join MULTIPLE affiliations, but some department names
# may themselves contain commas — so we keep the raw string alongside the
# naive split and let the dept-mapping layer correct mis-splits explicitly.


class DirectoryHit(BaseModel):
    """One row of a multi-result search table."""

    last_name: str
    first_name: str
    andrew_id: str
    affiliation: str  # "Faculty" / "Staff" / "Student" / "Sponsored" / ...
    departments_raw: str
    departments: list[str]
    guid: str


class DirectoryPerson(BaseModel):
    """A person detail page (guid link target, or a single-hit search)."""

    display_name: str
    affiliation: str | None
    andrew_id: str | None
    campus_room: str | None
    job_titles: list[str] = []
    departments: list[str] = []


class SearchPage(BaseModel):
    """Parsed shape of one search response."""

    kind: str  # "multi" | "single" | "empty"
    capped: bool
    hits: list[DirectoryHit] = []
    person: DirectoryPerson | None = None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _split_departments(raw: str) -> list[str]:
    return [d for d in (_clean(p) for p in raw.split(",")) if d]


def _lines_after(label_tag: Tag) -> list[str]:
    """Text lines following a <b>Label:</b> tag, <br/>-separated, up to the
    next <b>/<h2> (the next labeled field or section)."""
    parts: list[str] = []
    for sib in label_tag.next_siblings:
        if isinstance(sib, Tag) and sib.name in ("b", "h2"):
            break
        if isinstance(sib, Tag) and sib.name == "br":
            parts.append("\n")
        elif isinstance(sib, NavigableString):
            parts.append(str(sib))
        elif isinstance(sib, Tag):
            parts.append(sib.get_text(" ", strip=True))
    return [line for line in (_clean(x) for x in "".join(parts).split("\n")) if line]


def _value_after(soup: BeautifulSoup, label: str) -> list[str]:
    for b in soup.find_all("b"):
        if b.get_text(strip=True).rstrip(":").lower() == label.lower():
            return _lines_after(b)
    return []


def parse_person_detail(html: str) -> DirectoryPerson | None:
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1", id="listing")
    if h1 is None:
        return None
    heading = _clean(h1.get_text(" ", strip=True))
    m = H1_NAME_RE.match(heading)
    name, affiliation = (m["name"], m["affiliation"]) if m else (heading, None)

    andrew_id = next(iter(_value_after(soup, "Andrew UserID")), None)
    campus_room = next(iter(_value_after(soup, "On Campus")), None)
    job_titles = _value_after(soup, "Job Title According to HR")
    departments = _value_after(soup, "Department with which this person is affiliated")

    return DirectoryPerson(
        display_name=name,
        affiliation=affiliation,
        andrew_id=andrew_id,
        campus_room=campus_room,
        job_titles=job_titles,
        departments=departments,
    )


def parse_search_results(html: str) -> SearchPage:
    capped = CAP_MESSAGE in html
    soup = BeautifulSoup(html, "lxml")

    if soup.find("h1", id="listing") is not None:
        return SearchPage(kind="single", capped=capped, person=parse_person_detail(html))

    table = soup.find("table", id="sortabletable")
    if table is None:
        return SearchPage(kind="empty", capped=capped)

    hits: list[DirectoryHit] = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != 5:
            continue  # header row (th) or malformed
        link = tds[0].find("a")
        guid_m = GUID_RE.search(link["href"]) if link and link.has_attr("href") else None
        if guid_m is None:
            continue
        dept_raw = _clean(tds[4].get_text(" ", strip=True))
        hits.append(
            DirectoryHit(
                last_name=_clean(tds[0].get_text(" ", strip=True)),
                first_name=_clean(tds[1].get_text(" ", strip=True)),
                andrew_id=_clean(tds[2].get_text(" ", strip=True)),
                affiliation=_clean(tds[3].get_text(" ", strip=True)),
                departments_raw=dept_raw,
                departments=_split_departments(dept_raw),
                guid=guid_m.group(1),
            )
        )
    return SearchPage(kind="multi", capped=capped, hits=hits)
