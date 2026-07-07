"""CMU dept-code -> college mapping, shared by the viz and the metrics.

Best-effort from CMU's course numbering, user-verified 2026-06-30 (86->MCS,
65->Dietrich, 67->Heinz; 17->SCS, 66->Dietrich, 62->CFA confirmed). Departments not
listed map to "Other". NOTE: administrative college != intellectual field — Statistics
(36) is administered by Dietrich but is intellectually quantitative; the metrics that
use these labels inherit that imperfection (a known caveat, see DECISIONS.md).
"""

COLLEGE = {
    # CFA — College of Fine Arts
    "48": "CFA", "51": "CFA", "54": "CFA", "57": "CFA", "60": "CFA", "62": "CFA",
    # CIT — Engineering
    "06": "CIT", "12": "CIT", "18": "CIT", "19": "CIT", "24": "CIT", "27": "CIT", "42": "CIT",
    # MCS — Mellon College of Science
    "03": "MCS", "09": "MCS", "21": "MCS", "33": "MCS", "38": "MCS", "86": "MCS",
    # SCS — School of Computer Science
    "02": "SCS", "05": "SCS", "07": "SCS", "08": "SCS", "10": "SCS", "11": "SCS",
    "15": "SCS", "16": "SCS", "17": "SCS",
    # Dietrich — Humanities & Social Sciences
    "36": "Dietrich", "65": "Dietrich", "66": "Dietrich", "73": "Dietrich", "76": "Dietrich",
    "79": "Dietrich", "80": "Dietrich", "82": "Dietrich", "84": "Dietrich", "85": "Dietrich",
    "88": "Dietrich",
    # Tepper — Business
    "45": "Tepper", "46": "Tepper", "47": "Tepper", "70": "Tepper",
    # Heinz — Public Policy / Information Systems
    "67": "Heinz", "90": "Heinz", "91": "Heinz", "92": "Heinz", "93": "Heinz",
    "94": "Heinz", "95": "Heinz",
    # student-led
    "98": "StuCo",
}


def to_college(dept_codes: list[str]) -> list[str]:
    """Map dept codes to college names ('Other' if unmapped)."""
    return [COLLEGE.get(d, "Other") for d in dept_codes]
