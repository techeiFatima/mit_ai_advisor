from mit_advisor.quality.invariants import failed, run_checks


def test_snapshot_passes_all_error_invariants(records):
    assert failed(run_checks(records, expected_blocks=len(records))) == []


def test_missing_records_fails_the_block_count_check(records):
    checks = run_checks(records[:-1], expected_blocks=len(records))
    assert any(not c.passed and "every source block" in c.name for c in checks)


def test_duplicate_subject_numbers_are_detected(records):
    dupe = list(records) + [records[0]]
    checks = run_checks(dupe)
    assert any(not c.passed and "unique" in c.name for c in checks)


def test_degraded_extraction_is_caught(records):
    """The CI-M failure mode: fields silently stop being extracted."""
    stripped = [dict(r, title=None) for r in records]
    checks = run_checks(stripped)
    assert any(not c.passed and c.name == "title present" for c in checks)


def test_empty_input_fails(records):
    assert failed(run_checks([])) != []
