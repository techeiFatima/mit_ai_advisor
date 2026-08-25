"""The prerequisite grammar, case by case, from strings in the real corpus."""
import pytest

from mit_advisor.ingestion.catalog.prereq_parser import (
    iter_courses, parse_prerequisite,
)


def flat(node):
    """Render a tree compactly so assertions read like the catalog text."""
    if node is None:
        return "-"
    op = node["op"]
    if op == "COURSE":
        return node["id"]
    if op == "GIR":
        return f"GIR:{node['id']}"
    if op == "PERMISSION":
        return f"PERM:{node['who']}"
    if op == "COREQ":
        return f"COREQ({flat(node['operand'])})"
    if op in ("NONE", "OPAQUE"):
        return op
    return f"{op}({', '.join(flat(c) for c in node['operands'])})"


def test_none():
    r = parse_prerequisite("None")
    assert r.status == "parsed" and flat(r.ast) == "NONE"


def test_trailing_period_is_not_an_unreadable_requirement():
    assert parse_prerequisite("None.").status == "parsed"


def test_single_course():
    assert flat(parse_prerequisite("6.1910").ast) == "6.1910"


def test_permission_only():
    assert flat(parse_prerequisite("Permission of instructor").ast) == "PERM:instructor"


def test_simple_and():
    assert flat(parse_prerequisite("6.1020 and 6.1200[J]").ast) == "AND(6.1020, 6.1200[J])"


def test_comma_list_with_or_is_flat_not_nested():
    # "A, B, or C" is a three-way OR - not OR(AND(A,B), C).
    assert flat(parse_prerequisite("6.3700 , 6.3800 , or 18.05").ast) == \
        "OR(6.3700, 6.3800, 18.05)"


def test_comma_list_with_and():
    assert flat(parse_prerequisite("6.1200[J] , 6.1210 , and 18.404").ast) == \
        "AND(6.1200[J], 6.1210, 18.404)"


def test_nested_groups():
    raw = ("( 6.100B , ( 18.03 , 18.06 , or 18.C06[J] ), and "
           "( 6.3700 , 6.3800 , 14.30 , 16.09 , or 18.05 )) or permission of instructor")
    assert flat(parse_prerequisite(raw).ast) == (
        "OR(AND(6.100B, OR(18.03, 18.06, 18.C06[J]), "
        "OR(6.3700, 6.3800, 14.30, 16.09, 18.05)), PERM:instructor)")


def test_gir_is_an_atom_not_a_paren_group():
    r = parse_prerequisite("Calculus II (GIR)")
    assert flat(r.ast) == "GIR:Calculus II (GIR)"


def test_gir_inside_a_group():
    raw = ("( Physics II (GIR) , 18.03 , and ( 2.005 , 6.2000 , 6.3000 , 10.301 , "
           "or 20.110[J] )) or permission of instructor")
    assert flat(parse_prerequisite(raw).ast) == (
        "OR(AND(GIR:Physics II (GIR), 18.03, "
        "OR(2.005, 6.2000, 6.3000, 10.301, 20.110[J])), PERM:instructor)")


def test_mixed_and_or_uses_boolean_precedence():
    # 6.1910: the "; or permission" applies to the whole conjunction.
    raw = ("Physics II (GIR) , 6.100A , and ( Coreq: 6.1903 or 6.1904 ); "
           "or permission of instructor")
    r = parse_prerequisite(raw)
    assert r.status == "parsed"
    assert flat(r.ast) == ("OR(AND(GIR:Physics II (GIR), 6.100A, "
                           "COREQ(OR(6.1903, 6.1904))), PERM:instructor)")


def test_letter_prefixed_department():
    # CMS.301 - MIT departments are not all numeric.
    assert flat(parse_prerequisite("6.100A or CMS.301").ast) == "OR(6.100A, CMS.301)"


def test_unreadable_text_becomes_opaque_not_dropped():
    r = parse_prerequisite("6.1010 and interview with the lab director")
    assert "OPAQUE" in flat(r.ast)
    assert r.status == "partial"


def test_comma_list_with_no_connective_is_flagged():
    # The catalog means "all of", but we record the assumption rather than
    # silently presenting a guess as a parsed fact.
    r = parse_prerequisite("( 2.005 , 6.2000 )")
    assert r.status == "partial"
    assert any("assumed AND" in w for w in r.warnings)


def test_iter_courses_walks_the_whole_tree():
    raw = "( 6.100B , ( 18.03 or 18.06 )) and ( Coreq: 6.1903 )"
    ids = {c["id"] for c in iter_courses(parse_prerequisite(raw).ast)}
    assert ids == {"6.100B", "18.03", "18.06", "6.1903"}


@pytest.mark.parametrize("raw", ["", None, "   "])
def test_empty_input_is_unparsed_not_a_crash(raw):
    assert parse_prerequisite(raw).status == "unparsed"
