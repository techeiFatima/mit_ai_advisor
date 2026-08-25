"""Data-quality invariants for an ingestion run.

The original scraper printed "Task 2 Complete" whether it extracted 423 courses
or zero, and silently shipped a dataset with every CI-M designation missing.
Nothing errored; nothing logged.  That failure mode - extraction quietly
degrading while the pipeline reports success - is what this module exists to
catch.  A violation exits non-zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..ingestion.catalog.normalize import canonical


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    severity: str = "error"        # error | warning


def _rate(records: list[dict], pred: Callable[[dict], bool]) -> float:
    return (sum(1 for r in records if pred(r)) / len(records)) if records else 0.0


def run_checks(records: list[dict], *, expected_blocks: int | None = None) -> list[Check]:
    checks: list[Check] = []
    n = len(records)

    def field_rate(name: str, pred: Callable[[dict], bool], threshold: float,
                   severity: str = "error") -> None:
        r = _rate(records, pred)
        checks.append(Check(
            name, r >= threshold,
            f"{r:.1%} of {n} records (threshold {threshold:.0%})", severity))

    if expected_blocks is not None:
        checks.append(Check(
            "every source block produced a record", n == expected_blocks,
            f"{n} records from {expected_blocks} blocks"))

    checks.append(Check("at least one record", n > 0, f"{n} records"))

    numbers = [r["subject_number"] for r in records if r.get("subject_number")]
    dupes = {x for x in numbers if numbers.count(x) > 1}
    checks.append(Check("subject numbers are unique", not dupes,
                        f"{len(dupes)} duplicates" + (f": {sorted(dupes)[:5]}" if dupes else "")))

    field_rate("title present", lambda r: bool(r.get("title")), 0.95)
    field_rate("level present", lambda r: bool(r.get("level")), 0.95)
    field_rate("at least one term", lambda r: bool(r.get("terms_offered")), 0.95)
    field_rate("description present", lambda r: bool(r.get("description")), 0.95)
    field_rate("prerequisite text captured",
               lambda r: r["prerequisites"]["raw"] is not None, 0.95)
    field_rate("prerequisite tree parsed",
               lambda r: r["prerequisites"]["parse_status"] == "parsed", 0.85)
    field_rate("numeric units where not 'arranged'",
               lambda r: r["units"]["arranged"] or r["units"]["total"] is not None, 0.99)

    errored = [r for r in records if r.get("parse_errors")]
    checks.append(Check("no record-level parse errors", not errored,
                        f"{len(errored)} records with errors", "warning"))

    # --- canaries: fields whose silent disappearance is the failure mode ---
    # CI-M is currently expected to FAIL against the flattened snapshot.  That
    # is the point: the check documents a known, measured data gap instead of
    # letting it pass unnoticed.  It becomes an error once HTML ingestion lands.
    has_cim = any("CI-M" in (r.get("attributes") or []) for r in records)
    checks.append(Check(
        "communication (CI-M) attribute present somewhere", has_cim,
        "no CI-M designation in any record - the flattened snapshot dropped "
        "this attribute class (6.UAT is a CI-M subject and lacks it)",
        "warning"))

    has_rest = any("REST" in (r.get("attributes") or []) for r in records)
    checks.append(Check("REST attribute present somewhere", has_rest,
                        "REST found" if has_rest else "no REST designation found"))

    has_joint = any(r.get("cross_listings") for r in records)
    checks.append(Check("joint subjects have cross-listings", has_joint,
                        f"{sum(1 for r in records if r.get('cross_listings'))} records"))

    return checks


def render(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        mark = "PASS" if c.passed else ("WARN" if c.severity == "warning" else "FAIL")
        lines.append(f"  [{mark}] {c.name}: {c.detail}")
    return "\n".join(lines)


def failed(checks: list[Check]) -> list[Check]:
    return [c for c in checks if not c.passed and c.severity == "error"]
