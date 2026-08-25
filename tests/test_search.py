def test_lookup_by_number(index):
    assert index.get("6.1000")["title"].startswith("Introduction to Programming")


def test_lookup_is_insensitive_to_joint_marker(index):
    assert index.get("6.5400") is index.get("6.5400[J]")


def test_lookup_by_cross_listed_number(index):
    assert index.get("18.4041J") is not None


def test_unknown_number_returns_none(index):
    assert index.get("6.9999") is None


def test_title_hits_outrank_description_hits(index):
    hits = index.search("machine learning", limit=5)
    assert "machine learning" in hits[0].course["title"].lower()


def test_level_filter(index):
    assert all(h.course["level"] == "G" for h in index.search("algorithms", level="G"))


def test_term_filter(index):
    assert all("Fall" in h.course["terms_offered"]
               for h in index.search("circuits", term="Fall"))


def test_unit_filter(index):
    for h in index.search("laboratory", max_units=9):
        assert h.course["units"]["total"] <= 9


def test_query_by_subject_number_ranks_it_first(index):
    assert index.search("6.3900")[0].course["subject_id"] == "6.3900"


def test_empty_query_with_filters_returns_results(index):
    assert index.search("", term="IAP", limit=5)


def test_no_match_returns_empty(index):
    assert index.search("zzzznotarealtopiczzzz") == []
