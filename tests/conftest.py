import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mit_advisor.ingestion.catalog.snapshot_parser import parse_snapshot
from mit_advisor.services.course_search import CourseIndex


@pytest.fixture(scope="session")
def records():
    text = (ROOT / "mit_courses.txt").read_text(encoding="utf-8")
    return parse_snapshot(text, source_url="https://catalog.mit.edu/subjects/6/",
                          fetched_at="unknown", snapshot_path="mit_courses.txt")


@pytest.fixture(scope="session")
def index(records):
    return CourseIndex(records)
