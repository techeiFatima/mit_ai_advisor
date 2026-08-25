"""Multi-semester course planning.

The planner is a constrained greedy scheduler, not an optimiser, and that is a
deliberate choice: a student has to be able to read *why* a course landed in a
given term.  Every placement records the constraints it satisfied.

Constraints enforced (all deterministic, all from catalog data):
  * prerequisites, evaluated against courses completed *before* that term
  * term of offering (a Fall-only subject never lands in a Spring slot)
  * per-term unit cap
  * no repeats, and no course excluded for credit by something already planned

Interests only affect *ranking* within the eligible set — never eligibility.
That keeps the fact/recommendation boundary intact: what you *can* take is
computed; what we *suggest* is ranked.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..ingestion.catalog.normalize import canonical
from ..models.student import StudentProfile
from .course_search import tokens
from .prerequisite_engine import SATISFIED, UNKNOWN, evaluate

TERM_CYCLE = ["Fall", "Spring"]


@dataclass
class PlannedCourse:
    subject_id: str
    title: str
    units: int | None
    reasons: list[str] = field(default_factory=list)
    prereq_status: str = SATISFIED


@dataclass
class PlannedTerm:
    label: str
    term: str
    courses: list[PlannedCourse] = field(default_factory=list)
    total_units: int = 0
    notes: list[str] = field(default_factory=list)


def interest_score(course: dict, interests: list[str]) -> tuple[float, list[str]]:
    """How well a course matches stated interests. Ranking only - never a gate.

    A multi-word interest scores only when *all* of its tokens appear in the
    same field.  Scoring "machine learning" off a lone "learning" in a
    negotiation-skills description is exactly the kind of plausible-looking
    wrong answer this system must not produce.
    """
    if not interests:
        return 0.0, []
    title = set(tokens(course.get("title") or ""))
    desc = set(tokens(course.get("description") or ""))
    score, matched = 0.0, []
    for interest in interests:
        itoks = tokens(interest)
        if not itoks:
            continue
        if all(t in title for t in itoks):
            score += 10.0
            matched.append(interest)
        elif all(t in desc for t in itoks):
            score += 4.0
            matched.append(interest)
        elif len(itoks) > 1:
            # Partial match on a phrase: weak signal, and never named as a
            # match so the UI cannot claim an interest it did not find.
            score += 0.5 * sum(1 for t in itoks if t in title or t in desc)
    return score, sorted(set(matched))


def eligible_courses(index, profile: StudentProfile, *, term: str | None = None,
                     completed: set[str] | None = None,
                     include_unknown: bool = True) -> list[dict]:
    """Courses whose prerequisites are satisfied (or unknown) for this student."""
    done = completed if completed is not None else profile.completed_set
    perms = set(profile.permissions)
    out = []
    for c in index.courses:
        if canonical(c["subject_id"]) in done:
            continue
        if term and term not in (c.get("terms_offered") or []):
            continue
        ev = evaluate(c["prerequisites"]["ast"], completed=done,
                      in_progress=profile.current_set, permissions=perms)
        if ev.status == SATISFIED or (include_unknown and ev.status == UNKNOWN):
            out.append({"course": c, "evaluation": ev})
    return out


def build_plan(index, profile: StudentProfile, *, num_terms: int = 4,
               start_term: str = "Fall", max_units: int | None = None,
               emphasis: list[str] | None = None,
               max_courses_per_term: int = 5) -> list[PlannedTerm]:
    """Produce a term-by-term plan.

    ``emphasis`` overrides the profile's interests for this plan, which is how
    the caller generates several differently-weighted options from one profile.
    """
    interests = emphasis if emphasis is not None else profile.interests
    cap = max_units or profile.max_units_per_term
    completed = set(profile.completed_set) | set(profile.current_set)
    excluded: set[str] = set()
    def equivalents(course: dict) -> set[str]:
        return {canonical(x) for x in (course.get("credit_excluded", [])
                                       + course.get("meets_with", [])
                                       + course.get("cross_listings", []))}

    for num in completed:
        c = index.get(num)
        if c:
            excluded |= equivalents(c)

    terms: list[PlannedTerm] = []
    t_index = TERM_CYCLE.index(start_term) if start_term in TERM_CYCLE else 0
    year_offset = 0
    for i in range(num_terms):
        term_name = TERM_CYCLE[(t_index + i) % len(TERM_CYCLE)]
        if i > 0 and TERM_CYCLE[(t_index + i) % len(TERM_CYCLE)] == TERM_CYCLE[0]:
            year_offset += 1
        planned = PlannedTerm(label=f"{term_name} +{i}", term=term_name)

        candidates = []
        for item in eligible_courses(index, profile, term=term_name,
                                     completed=completed, include_unknown=False):
            c = item["course"]
            key = canonical(c["subject_id"])
            if key in excluded:
                continue
            units = (c.get("units") or {}).get("total")
            if units is None:
                continue                      # "Units arranged" can't be packed
            notes = c.get("offering_notes") or {}
            if notes.get("not_offered_regularly"):
                # The catalog explicitly declines to say when this runs, so
                # placing it in a named term would assert more than we know.
                continue
            iscore, matched = interest_score(c, interests)
            candidates.append((iscore, c, units, matched, item["evaluation"]))

        candidates.sort(key=lambda x: (-x[0], x[1]["subject_id"]))
        for iscore, c, units, matched, ev in candidates:
            if len(planned.courses) >= max_courses_per_term:
                break
            if planned.total_units + units > cap:
                continue
            if canonical(c["subject_id"]) in excluded:
                continue
            excluded |= equivalents(c)
            reasons = ["prerequisites satisfied", f"offered in {term_name}"]
            if interests and not matched:
                reasons.append("fills remaining units")
            if matched:
                reasons.append("matches interest: " + ", ".join(matched[:3]))
            planned.courses.append(PlannedCourse(
                subject_id=c["subject_id"], title=c.get("title") or "",
                units=units, reasons=reasons))
            planned.total_units += units

        if not planned.courses:
            planned.notes.append(
                "No course with a fully satisfied prerequisite tree and known "
                "unit count was available for this term.")
        for pc in planned.courses:
            completed.add(canonical(pc.subject_id))
            c = index.get(pc.subject_id)
            if c:
                excluded |= equivalents(c)
        terms.append(planned)
    return terms
