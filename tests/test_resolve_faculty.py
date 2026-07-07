"""Pure resolution-logic tests (no I/O): every branch of resolve_pair."""

from latent_campus.resolve.faculty import (
    Candidate,
    attach_dept_codes,
    map_departments,
    resolve_pair,
)

DEPT_MAP = {
    "Computer Science Department": ["15"],
    "Robotics Institute - Campus": ["16"],
    "Machine Learning": ["10"],
    "SCS Dean's Office": None,  # non-teaching unit
}


def _cand(andrew_id: str, departments: list[str]) -> Candidate:
    c = Candidate(
        andrew_id=andrew_id, display_name=andrew_id.title(), affiliation="Faculty",
        departments=departments,
    )
    return attach_dept_codes([c], DEPT_MAP)[0]


class TestMapDepartments:
    def test_union_of_mapped_codes(self):
        codes = map_departments(
            ["Computer Science Department", "Machine Learning"], DEPT_MAP
        )
        assert codes == {"15", "10"}

    def test_null_and_unmapped_names_contribute_nothing(self):
        assert map_departments(["SCS Dean's Office", "Totally Unknown Unit"], DEPT_MAP) == set()


class TestResolvePair:
    def test_dept_unique_among_several(self):
        pool = [_cand("alpha", ["Computer Science Department"]),
                _cand("beta", ["Robotics Institute - Campus"])]
        r = resolve_pair("Chen", "15", pool, capped=False)
        assert r.status == "resolved" and r.method == "dept-unique" and r.andrew_id == "alpha"
        assert r.n_candidates == 2 and r.n_dept_matches == 1

    def test_two_dept_matches_is_ambiguous(self):
        pool = [_cand("alpha", ["Computer Science Department"]),
                _cand("beta", ["Computer Science Department"])]
        r = resolve_pair("Chen", "15", pool, capped=False)
        assert r.status == "ambiguous" and r.andrew_id is None

    def test_global_unique_without_dept_match(self):
        pool = [_cand("gamma", ["SCS Dean's Office"])]  # maps to no teaching dept
        r = resolve_pair("Berntsen", "21", pool, capped=False)
        assert r.status == "resolved" and r.method == "global-unique" and r.andrew_id == "gamma"

    def test_several_candidates_no_dept_match_is_ambiguous(self):
        pool = [_cand("alpha", ["Machine Learning"]), _cand("beta", ["SCS Dean's Office"])]
        r = resolve_pair("Chen", "21", pool, capped=False)
        assert r.status == "ambiguous"

    def test_empty_pool_is_no_match(self):
        r = resolve_pair("Ghost", "15", [], capped=False)
        assert r.status == "no-match" and r.n_candidates == 0

    def test_capped_pool_never_auto_resolves(self):
        # even a would-be dept-unique match must not resolve from a truncated pool
        pool = [_cand("alpha", ["Computer Science Department"])]
        r = resolve_pair("Lee", "15", pool, capped=True)
        assert r.status == "capped" and r.andrew_id is None


class TestAttachDeptCodes:
    def test_codes_attached_and_original_untouched(self):
        raw = Candidate(andrew_id="x", display_name="X", affiliation="Faculty",
                        departments=["Computer Science Department"])
        [with_codes] = attach_dept_codes([raw], DEPT_MAP)
        assert with_codes.dept_codes == {"15"}
        assert raw.dept_codes == set()
