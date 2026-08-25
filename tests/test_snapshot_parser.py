"""Block-level extraction, including every edge case found in the corpus."""
from mit_advisor.ingestion.catalog.snapshot_parser import parse_block


def by_id(records, sid):
    return next(r for r in records if r["subject_id"] == sid)


def test_all_blocks_parse_without_errors(records):
    bad = [(r["subject_id"], r["parse_errors"]) for r in records if r["parse_errors"]]
    assert bad == []


def test_record_count(records):
    assert len(records) == 423


def test_subject_numbers_unique(records):
    nums = [r["subject_number"] for r in records]
    assert len(nums) == len(set(nums))


def test_units_triple_is_preserved(records):
    r = by_id(records, "6.1000")
    assert r["units"] == {"arranged": False, "lecture": 3, "lab": 0,
                          "preparation": 9, "total": 12}


def test_units_arranged(records):
    r = by_id(records, "6.9800")
    assert r["units"]["arranged"] is True and r["units"]["total"] is None


def test_joint_subject_cross_listing(records):
    r = by_id(records, "6.5400[J]")
    assert r["is_joint"] is True
    assert "18.4041J" in r["cross_listings"]
    assert "18.404" in r["meets_with"]


def test_stub_description_is_flagged(records):
    r = by_id(records, "6.5400[J]")
    assert r["description_is_stub"] is True
    assert r["description_source"] == "18.4041J"


def test_alternating_year_offering_is_not_a_prerequisite(records):
    r = by_id(records, "6.1100")
    assert r["offering_notes"]["academic_years"] == {
        "2025-2026": "not_offered", "2026-2027": "offered"}
    assert "Acad" not in (r["prerequisites"]["raw"] or "")
    assert r["prerequisites"]["raw"] == "6.1020 and 6.1910"


def test_sub_term_qualifier_is_captured(records):
    r = by_id(records, "6.120A")
    assert r["terms_offered"] == ["Spring"]
    assert r["offering_notes"]["term_note"] == "second half of term"


def test_credit_exclusion_does_not_eat_the_description(records):
    r = by_id(records, "6.3700")
    assert r["credit_excluded"] == ["18.600"]
    assert r["description"].startswith("An introduction to probability theory")


def test_top_level_coreq_is_a_separate_field(records):
    r = by_id(records, "6.2030")
    assert r["corequisites"]["raw"] == "Physics II (GIR)"
    assert r["prerequisites"]["raw"] is None or "Coreq" not in r["prerequisites"]["raw"]


def test_nested_coreq_stays_in_the_prerequisite_tree(records):
    r = by_id(records, "6.1910")
    assert r["corequisites"]["raw"] is None
    assert r["prerequisites"]["parse_status"] == "parsed"


def test_attributes_extracted(records):
    assert "REST" in by_id(records, "6.1000")["attributes"]


def test_repeatable_and_pdf_flags(records):
    r = by_id(records, "6.9800")
    assert r["repeatable"] is True and r["grading"]["pdf_option"] is True


def test_provenance_on_every_record(records):
    for r in records:
        p = r["provenance"]
        assert p["source_url"] and p["snapshot_sha256"].startswith("sha256:")
        assert p["parser_version"]


def test_malformed_block_does_not_crash():
    r = parse_block("this block has no subject number at all")
    assert r["parse_errors"] and r["subject_id"] is None


def test_empty_block_does_not_crash():
    r = parse_block("")
    assert r["parse_errors"]


def test_instructors_are_labelled_as_heuristic(records):
    with_names = [r for r in records if r["instructors"]]
    assert with_names, "expected some instructor extraction"
    assert all(r["instructors_extraction"] == "heuristic" for r in with_names)
