"""The tool surface. These run without any API key - they exercise dispatch only."""
from mit_advisor.advisor.tools.registry import TOOL_DEFINITIONS, ToolRegistry


def test_every_tool_has_a_handler(index):
    reg = ToolRegistry(index)
    for t in TOOL_DEFINITIONS:
        assert hasattr(reg, f"_{t['name']}"), f"no handler for {t['name']}"


def test_tool_schemas_are_strict(index):
    for t in TOOL_DEFINITIONS:
        assert t.get("strict") is True
        assert t["input_schema"]["additionalProperties"] is False
        assert t["input_schema"].get("required")


def test_get_course(index):
    r = ToolRegistry(index).call("get_course", {"subject_number": "6.3900"})
    assert r["kind"] == "catalog_fact"
    assert r["course"]["title"] == "Introduction to Machine Learning"


def test_get_course_unknown_is_unavailable_not_invented(index):
    r = ToolRegistry(index).call("get_course", {"subject_number": "6.9999"})
    assert r["kind"] == "unavailable"


def test_check_prerequisites_satisfied(index):
    r = ToolRegistry(index).call("check_prerequisites", {
        "subject_number": "6.1020", "completed_courses": ["6.1010"]})
    assert r["kind"] == "computed_fact"
    assert r["status"] in {"SATISFIED", "NOT_SATISFIED", "UNKNOWN"}
    assert r["basis"]


def test_check_prerequisites_reports_missing(index):
    r = ToolRegistry(index).call("check_prerequisites", {
        "subject_number": "6.1020", "completed_courses": []})
    assert r["status"] != "SATISFIED"


def test_degree_requirements_refuses_to_invent(index):
    r = ToolRegistry(index).call("get_degree_requirements", {"program": "6-4"})
    assert r["kind"] == "unavailable"
    assert "authoritative_source" in r
    assert "GIR" in r["message"]


def test_search_returns_provenance_tagged_facts(index):
    r = ToolRegistry(index).call("search_courses", {"query": "robotics", "limit": 3})
    assert r["kind"] == "catalog_fact" and r["results"]


def test_build_course_plan_carries_its_caveat(index):
    r = ToolRegistry(index).call("build_course_plan", {
        "completed_courses": ["6.100A"], "num_terms": 2})
    assert r["kind"] == "computed_fact"
    assert "does NOT verify degree requirements" in r["caveat"]
    assert len(r["terms"]) == 2


def test_unknown_tool_is_an_error_not_a_crash(index):
    assert ToolRegistry(index).call("nope", {})["kind"] == "error"


def test_bad_arguments_are_an_error_not_a_crash(index):
    assert ToolRegistry(index).call("get_course", {"wrong": 1})["kind"] == "error"
