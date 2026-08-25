"""Three-valued prerequisite evaluation.

The property that matters most: an unreadable requirement must never report
SATISFIED.  Several of these tests exist only to pin that down.
"""
from mit_advisor.ingestion.catalog.prereq_parser import parse_prerequisite
from mit_advisor.services.prerequisite_engine import (
    NOT_SATISFIED, SATISFIED, UNKNOWN, evaluate,
)


def ev(raw, done=(), **kw):
    return evaluate(parse_prerequisite(raw).ast, completed=set(done), **kw)


def test_none_is_satisfied():
    assert ev("None").status == SATISFIED


def test_missing_prereq_tree_is_satisfied():
    assert evaluate(None, completed=set()).status == SATISFIED


def test_single_course_satisfied():
    assert ev("6.1010", done={"6.1010"}).status == SATISFIED


def test_single_course_not_satisfied():
    r = ev("6.1010")
    assert r.status == NOT_SATISFIED and r.missing == ["6.1010"]


def test_and_requires_all():
    assert ev("6.1010 and 6.1020", done={"6.1010"}).status == NOT_SATISFIED
    assert ev("6.1010 and 6.1020", done={"6.1010", "6.1020"}).status == SATISFIED


def test_or_requires_any():
    assert ev("6.1010 or 6.1020", done={"6.1020"}).status == SATISFIED


def test_joint_number_matches_either_spelling():
    # 6.1200[J] on the record, "6.1200" on the student's transcript.
    assert ev("6.1200[J]", done={"6.1200"}).status == SATISFIED


def test_permission_is_unknown_not_satisfied():
    # We cannot know whether an instructor would grant permission.
    assert ev("Permission of instructor").status == UNKNOWN


def test_permission_satisfied_when_asserted():
    assert ev("Permission of instructor", permissions={"instructor"}).status == SATISFIED


def test_or_with_permission_is_unknown_when_course_missing():
    # Never NOT_SATISFIED: the permission branch might still open the door.
    assert ev("6.1010 or permission of instructor").status == UNKNOWN


def test_or_with_permission_is_satisfied_when_course_done():
    assert ev("6.1010 or permission of instructor", done={"6.1010"}).status == SATISFIED


def test_gir_is_unknown_without_explicit_credit():
    assert ev("Calculus II (GIR)").status == UNKNOWN


def test_gir_satisfied_when_credit_supplied():
    r = ev("Calculus II (GIR)", gir_credit={"Calculus II (GIR)"})
    assert r.status == SATISFIED


def test_unreadable_requirement_never_satisfies_an_and():
    r = ev("6.1010 and interview with the lab director", done={"6.1010"})
    assert r.status == UNKNOWN
    assert any("unparsed" in u for u in r.unknown_reasons)


def test_unreadable_branch_does_not_block_a_satisfied_or():
    r = ev("6.1010 or interview with the lab director", done={"6.1010"})
    assert r.status == SATISFIED


def test_and_with_a_definite_failure_is_not_satisfied_even_with_unknown():
    # A missing course is decisive; the unknown branch cannot rescue an AND.
    assert ev("6.9999 and permission of instructor").status == NOT_SATISFIED


def test_coreq_may_be_taken_concurrently():
    r = ev("( Coreq: 6.1903 )", done=set(), in_progress={"6.1903"})
    assert r.status == SATISFIED


def test_nested_structure_is_evaluated_correctly():
    raw = "( 6.1210 and ( 6.1800 or 6.1810 )) or permission of instructor"
    assert ev(raw, done={"6.1210", "6.1810"}).status == SATISFIED
    assert ev(raw, done={"6.1800"}).status == UNKNOWN


def test_detail_tree_mirrors_the_ast():
    r = ev("6.1010 and 6.1020", done={"6.1010"})
    assert r.detail["op"] == "AND"
    assert [c["status"] for c in r.detail["operands"]] == [SATISFIED, NOT_SATISFIED]


def test_real_catalog_course(index):
    c = index.get("6.1910")
    r = evaluate(c["prerequisites"]["ast"], completed={"6.100A"},
                 in_progress={"6.1903"}, gir_credit={"Physics II (GIR)"})
    assert r.status == SATISFIED
