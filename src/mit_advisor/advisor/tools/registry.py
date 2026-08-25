"""Tool surface exposed to Claude.

Claude is the reasoning and orchestration layer; it is not the database.  Every
academic fact in an answer must come through one of these functions, each of
which reads the parsed catalog or runs a deterministic engine.

Each result carries a ``kind`` field that classifies the claim:

    "catalog_fact"    stated by the MIT catalog (carries provenance)
    "computed_fact"   derived deterministically from catalog data + the profile
    "unavailable"     we have no authoritative source; the model must say so

That tag is what keeps §10's fact/recommendation boundary enforceable at the
data layer instead of relying on the prompt alone.
"""
from __future__ import annotations

from typing import Any

from ...ingestion.catalog.normalize import canonical
from ...models.student import StudentProfile
from ...services.planning_engine import build_plan, eligible_courses
from ...services.prerequisite_engine import evaluate, explain

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_courses",
        "description": (
            "Search the MIT subject catalog by keyword, with optional structured "
            "filters. Returns matching subjects with number, title, units, terms "
            "and a description excerpt. Use this to discover subjects by topic."),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic keywords, e.g. 'reinforcement learning'."},
                "level": {"type": "string", "enum": ["U", "G"], "description": "Undergraduate or graduate."},
                "term": {"type": "string", "enum": ["Fall", "Spring", "IAP", "Summer"]},
                "max_units": {"type": "integer"},
                "limit": {"type": "integer", "description": "Default 10, max 40."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "get_course",
        "description": (
            "Look up one subject by number (e.g. '6.3900' or '6.5400[J]'). Returns "
            "the full catalog record including prerequisites, units, terms, "
            "cross-listings and provenance."),
        "input_schema": {
            "type": "object",
            "properties": {"subject_number": {"type": "string"}},
            "required": ["subject_number"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "get_prerequisites",
        "description": (
            "Return the prerequisite expression for a subject, both as the "
            "catalog's raw text and as a parsed boolean tree. Use this when the "
            "student asks what a subject requires."),
        "input_schema": {
            "type": "object",
            "properties": {"subject_number": {"type": "string"}},
            "required": ["subject_number"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "check_prerequisites",
        "description": (
            "Deterministically decide whether a student may take a subject. "
            "Returns SATISFIED, NOT_SATISFIED or UNKNOWN, the specific missing "
            "subjects, and a readable evaluation tree. UNKNOWN means the "
            "requirement could not be verified - report that honestly rather "
            "than guessing."),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject_number": {"type": "string"},
                "completed_courses": {"type": "array", "items": {"type": "string"}},
                "current_courses": {"type": "array", "items": {"type": "string"}},
                "gir_credit": {
                    "type": "array", "items": {"type": "string"},
                    "description": "GIRs the student has completed, e.g. 'Calculus II (GIR)'.",
                },
            },
            "required": ["subject_number", "completed_courses"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "find_eligible_courses",
        "description": (
            "List subjects whose prerequisites the student currently satisfies, "
            "optionally filtered to a term. Use this for 'what can I take next "
            "semester'."),
        "input_schema": {
            "type": "object",
            "properties": {
                "completed_courses": {"type": "array", "items": {"type": "string"}},
                "term": {"type": "string", "enum": ["Fall", "Spring", "IAP", "Summer"]},
                "level": {"type": "string", "enum": ["U", "G"]},
                "interests": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer"},
            },
            "required": ["completed_courses"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "build_course_plan",
        "description": (
            "Generate a multi-semester plan honouring prerequisites, term of "
            "offering and a per-term unit cap. Interests affect ranking only, "
            "never eligibility. Call it more than once with different "
            "'emphasis' values to offer the student contrasting options."),
        "input_schema": {
            "type": "object",
            "properties": {
                "completed_courses": {"type": "array", "items": {"type": "string"}},
                "num_terms": {"type": "integer", "description": "Default 4."},
                "start_term": {"type": "string", "enum": ["Fall", "Spring"]},
                "max_units_per_term": {"type": "integer", "description": "Default 48."},
                "emphasis": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Topics to prioritise in ranking, e.g. ['machine learning'].",
                },
            },
            "required": ["completed_courses"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "get_degree_requirements",
        "description": (
            "Look up official degree requirements (GIRs, HASS, CI-H/CI-M, major "
            "or minor requirements) for a program. IMPORTANT: this dataset "
            "currently contains no authoritative requirements source, so this "
            "tool reports what is unavailable. Call it before making any claim "
            "about degree requirements, and relay its answer rather than "
            "supplying requirements from memory."),
        "input_schema": {
            "type": "object",
            "properties": {"program": {"type": "string", "description": "e.g. '6-4'."}},
            "required": ["program"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def _course_summary(c: dict) -> dict:
    return {
        "subject_number": c["subject_id"],
        "title": c["title"],
        "level": c["level"],
        "units": c["units"]["total"] if not c["units"]["arranged"] else "arranged",
        "terms_offered": c["terms_offered"],
        "prerequisites_raw": c["prerequisites"]["raw"],
        "attributes": c["attributes"],
        "description": (c["description"] or "")[:400],
        "cross_listings": c["cross_listings"],
        "description_is_stub": c["description_is_stub"],
    }


class ToolRegistry:
    """Dispatches tool calls against the loaded catalog."""

    def __init__(self, index) -> None:
        self.index = index

    def call(self, name: str, args: dict) -> dict:
        fn = getattr(self, f"_{name}", None)
        if fn is None:
            return {"kind": "error", "error": f"unknown tool: {name}"}
        try:
            return fn(**args)
        except TypeError as exc:
            return {"kind": "error", "error": f"bad arguments for {name}: {exc}"}

    # ------------------------------------------------------------------ tools
    def _search_courses(self, query, level=None, term=None, max_units=None, limit=10):
        hits = self.index.search(query, level=level, term=term,
                                 max_units=max_units, limit=min(int(limit or 10), 40))
        return {"kind": "catalog_fact", "source": "MIT subject catalog",
                "result_count": len(hits),
                "results": [dict(_course_summary(h.course), matched=h.matched)
                            for h in hits]}

    def _get_course(self, subject_number):
        c = self.index.get(subject_number)
        if not c:
            return {"kind": "unavailable",
                    "message": f"No subject {subject_number} in the loaded catalog "
                               f"(Course 6 only)."}
        return {"kind": "catalog_fact", "source": c["provenance"]["source_url"],
                "fetched_at": c["provenance"]["fetched_at"],
                "course": _course_summary(c),
                "note": ("Description lives under the cross-listed subject; not "
                         "in this dataset." if c["description_is_stub"] else None)}

    def _get_prerequisites(self, subject_number):
        c = self.index.get(subject_number)
        if not c:
            return {"kind": "unavailable", "message": f"No subject {subject_number}."}
        p = c["prerequisites"]
        return {"kind": "catalog_fact", "subject_number": c["subject_id"],
                "raw": p["raw"], "parse_status": p["parse_status"],
                "tree": p["ast"], "corequisites_raw": c["corequisites"]["raw"],
                "source": c["provenance"]["source_url"]}

    def _check_prerequisites(self, subject_number, completed_courses,
                             current_courses=None, gir_credit=None):
        c = self.index.get(subject_number)
        if not c:
            return {"kind": "unavailable", "message": f"No subject {subject_number}."}
        ev = evaluate(c["prerequisites"]["ast"],
                      completed={canonical(x) for x in completed_courses},
                      in_progress={canonical(x) for x in (current_courses or [])},
                      gir_credit=set(gir_credit or []))
        return {"kind": "computed_fact", "subject_number": c["subject_id"],
                "status": ev.status, "missing": ev.missing,
                "could_not_verify": ev.unknown_reasons,
                "prerequisite_raw": c["prerequisites"]["raw"],
                "evaluation": explain(ev.detail),
                "basis": "MIT catalog prerequisite text, evaluated deterministically"}

    def _find_eligible_courses(self, completed_courses, term=None, level=None,
                               interests=None, limit=25):
        profile = StudentProfile(completed_courses=list(completed_courses),
                                 interests=list(interests or []))
        items = eligible_courses(self.index, profile, term=term,
                                 include_unknown=False)
        if level:
            items = [i for i in items if i["course"]["level"] == level]
        from ...services.planning_engine import interest_score
        scored = []
        for i in items:
            s, matched = interest_score(i["course"], profile.interests)
            scored.append((s, i["course"], matched))
        scored.sort(key=lambda x: (-x[0], x[1]["subject_id"]))
        return {"kind": "computed_fact",
                "basis": "prerequisite trees evaluated against completed_courses",
                "eligible_count": len(scored),
                "results": [dict(_course_summary(c), interest_match=m)
                            for _, c, m in scored[: int(limit or 25)]]}

    def _build_course_plan(self, completed_courses, num_terms=4, start_term="Fall",
                           max_units_per_term=48, emphasis=None):
        profile = StudentProfile(completed_courses=list(completed_courses),
                                 interests=list(emphasis or []))
        plan = build_plan(self.index, profile, num_terms=int(num_terms or 4),
                          start_term=start_term,
                          max_units=int(max_units_per_term or 48),
                          emphasis=list(emphasis or []))
        return {
            "kind": "computed_fact",
            "basis": ("greedy scheduler constrained by prerequisites, term of "
                      "offering and unit cap; interests affect ranking only"),
            "caveat": ("This plan satisfies prerequisites and unit limits. It "
                       "does NOT verify degree requirements - no authoritative "
                       "requirements source is loaded."),
            "terms": [{"label": t.label, "term": t.term,
                       "total_units": t.total_units, "notes": t.notes,
                       "courses": [{"subject_number": pc.subject_id,
                                    "title": pc.title, "units": pc.units,
                                    "reasons": pc.reasons} for pc in t.courses]}
                      for t in plan],
        }

    def _get_degree_requirements(self, program):
        return {
            "kind": "unavailable",
            "program": program,
            "message": (
                "No authoritative MIT degree-requirements source is loaded in "
                "this dataset. The catalog snapshot covers Course 6 SUBJECT "
                "listings only - it contains no GIR, HASS, CI-H/CI-M, major, "
                "minor or concentration requirements."),
            "instruction_to_model": (
                "Tell the student plainly that you cannot verify degree "
                "requirements, and point them to the official MIT source. Do "
                "NOT supply requirements from memory."),
            "authoritative_source": "https://catalog.mit.edu/degree-charts/",
        }
