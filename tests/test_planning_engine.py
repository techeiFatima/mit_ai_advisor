"""Planner constraints. Interests may reorder; they may never make a course eligible."""
from mit_advisor.models.student import StudentProfile
from mit_advisor.services.planning_engine import (
    build_plan, eligible_courses, interest_score,
)


def test_plan_respects_unit_cap(index):
    p = StudentProfile(completed_courses=["6.100A", "6.100B"])
    for term in build_plan(index, p, num_terms=4, max_units=36):
        assert term.total_units <= 36


def test_plan_respects_term_of_offering(index):
    p = StudentProfile(completed_courses=["6.100A"])
    for term in build_plan(index, p, num_terms=4):
        for pc in term.courses:
            assert term.term in index.get(pc.subject_id)["terms_offered"]


def test_plan_never_repeats_a_course(index):
    p = StudentProfile(completed_courses=["6.100A"])
    seen = [pc.subject_id for t in build_plan(index, p, num_terms=4) for pc in t.courses]
    assert len(seen) == len(set(seen))


def test_plan_never_schedules_a_completed_course(index):
    done = ["6.100A", "6.100B", "6.1010"]
    p = StudentProfile(completed_courses=done)
    for t in build_plan(index, p, num_terms=4):
        for pc in t.courses:
            assert pc.subject_id not in done


def test_plan_only_schedules_prerequisite_satisfied_courses(index):
    from mit_advisor.services.prerequisite_engine import SATISFIED, evaluate
    p = StudentProfile(completed_courses=["6.100A", "6.100B"])
    completed = set(p.completed_set)
    for t in build_plan(index, p, num_terms=3):
        for pc in t.courses:
            c = index.get(pc.subject_id)
            r = evaluate(c["prerequisites"]["ast"], completed=completed)
            assert r.status == SATISFIED, f"{pc.subject_id} scheduled without prereqs"
        for pc in t.courses:
            completed.add(pc.subject_id)


def test_prerequisites_unlock_across_terms(index):
    # 6.1020 requires 6.1010; a student with neither should still be able to
    # reach 6.1020 in a later term than 6.1010.
    p = StudentProfile(completed_courses=["6.100A", "6.100B"])
    plan = build_plan(index, p, num_terms=6, max_units=48)
    placement = {pc.subject_id: i for i, t in enumerate(plan) for pc in t.courses}
    if "6.1010" in placement and "6.1020" in placement:
        assert placement["6.1010"] < placement["6.1020"]


def test_interest_does_not_gate_eligibility(index):
    a = StudentProfile(completed_courses=["6.100A"], interests=[])
    b = StudentProfile(completed_courses=["6.100A"], interests=["robotics"])
    assert {c["course"]["subject_id"] for c in eligible_courses(index, a)} == \
           {c["course"]["subject_id"] for c in eligible_courses(index, b)}


def test_interest_phrase_requires_all_tokens():
    course = {"title": "Negotiation and Influence Skills",
              "description": "Covers learning to negotiate."}
    score, matched = interest_score(course, ["machine learning"])
    assert "machine learning" not in matched


def test_interest_phrase_matches_when_complete():
    course = {"title": "Introduction to Machine Learning", "description": ""}
    score, matched = interest_score(course, ["machine learning"])
    assert matched == ["machine learning"] and score >= 10


def test_units_arranged_courses_are_not_packed(index):
    p = StudentProfile(completed_courses=["6.100A"])
    for t in build_plan(index, p, num_terms=4):
        for pc in t.courses:
            assert pc.units is not None


def test_empty_profile_still_produces_a_plan(index):
    plan = build_plan(index, StudentProfile(), num_terms=2)
    assert len(plan) == 2


def test_irregularly_offered_subjects_are_not_scheduled(index):
    """The catalog declines to say when these run; a plan must not assert a term."""
    from mit_advisor.models.student import StudentProfile
    p = StudentProfile(completed_courses=["6.100A", "6.100B"])
    for t in build_plan(index, p, num_terms=6):
        for pc in t.courses:
            notes = index.get(pc.subject_id)["offering_notes"]
            assert not notes.get("not_offered_regularly"), pc.subject_id


def test_filler_courses_are_labelled_honestly(index):
    """A course placed only to use up units must not imply an interest match."""
    from mit_advisor.models.student import StudentProfile
    p = StudentProfile(completed_courses=["6.100A"], interests=["machine learning"])
    for t in build_plan(index, p, num_terms=4):
        for pc in t.courses:
            has_match = any(r.startswith("matches interest") for r in pc.reasons)
            has_filler = "fills remaining units" in pc.reasons
            assert has_match != has_filler, pc.subject_id
