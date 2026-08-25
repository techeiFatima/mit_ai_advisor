#!/usr/bin/env python3
"""Parse a catalog snapshot into structured records and report data quality.

    python scripts/parse_catalog.py [--input mit_courses.txt] [--out data/processed]

Exits non-zero if an error-severity invariant fails.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from mit_advisor.ingestion.catalog.snapshot_parser import SEPARATOR, parse_snapshot
from mit_advisor.quality.invariants import failed, render, run_checks

DEFAULT_SOURCE = "https://catalog.mit.edu/subjects/6/"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="mit_courses.txt")
    ap.add_argument("--out", default="data/processed")
    ap.add_argument("--source-url", default=DEFAULT_SOURCE)
    ap.add_argument("--fetched-at", default="unknown",
                    help="ISO timestamp of the snapshot; 'unknown' for the "
                         "committed file, which carries no fetch date")
    args = ap.parse_args()

    root = pathlib.Path(__file__).resolve().parent.parent
    src = (root / args.input) if not pathlib.Path(args.input).is_absolute() else pathlib.Path(args.input)
    text = src.read_text(encoding="utf-8")
    blocks = len([b for b in text.split(SEPARATOR) if b.strip()])

    records = parse_snapshot(text, source_url=args.source_url,
                             fetched_at=args.fetched_at,
                             snapshot_path=str(src.relative_to(root)))

    outdir = (root / args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    jsonl = outdir / "courses.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    checks = run_checks(records, expected_blocks=blocks)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_url": args.source_url,
        "input": str(src.relative_to(root)),
        "blocks_in": blocks,
        "records_out": len(records),
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail,
                    "severity": c.severity} for c in checks],
    }
    (outdir / "quality_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    print(f"parsed {len(records)} records from {blocks} blocks -> {jsonl}")
    print(render(checks))
    bad = failed(checks)
    if bad:
        print(f"\nFAILED {len(bad)} invariant(s).", file=sys.stderr)
        return 1
    print("\nAll error-severity invariants passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
