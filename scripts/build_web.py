#!/usr/bin/env python3
"""Bundle the parsed catalog into the self-contained web app.

The published page has no backend, so the prerequisite *trees* travel with it
and the browser only re-implements the evaluator (~40 lines), never the parser.
That keeps one grammar implementation in Python and guarantees the site and the
CLI agree about what a prerequisite means.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

PLACEHOLDER = "/*__CATALOG_DATA__*/null/*__END__*/"


def compact(rec: dict) -> dict:
    u = rec["units"]
    return {
        "id": rec["subject_id"],
        "num": rec["subject_number"],
        "t": rec["title"],
        "lv": rec["level"],
        "u": None if u["arranged"] else [u["lecture"], u["lab"], u["preparation"], u["total"]],
        "tm": rec["terms_offered"],
        "tn": rec["offering_notes"].get("term_note"),
        "ay": rec["offering_notes"].get("academic_years") or None,
        "nr": rec["offering_notes"].get("not_offered_regularly") or None,
        "pr": rec["prerequisites"]["raw"],
        "ps": rec["prerequisites"]["parse_status"],
        "pa": rec["prerequisites"]["ast"],
        "cr": rec["corequisites"]["raw"],
        "ca": rec["corequisites"]["ast"],
        "xl": rec["cross_listings"] or None,
        "mw": rec["meets_with"] or None,
        "cx": rec["credit_excluded"] or None,
        "at": rec["attributes"] or None,
        "rp": rec["repeatable"] or None,
        "pdf": rec["grading"]["pdf_option"] or None,
        "el": rec["enrollment_limited"] or None,
        "st": rec["description_source"] if rec["description_is_stub"] else None,
        "d": rec["description"],
        "ins": rec["instructors"] or None,
    }


def main() -> int:
    src = ROOT / "data" / "processed" / "courses.jsonl"
    if not src.exists():
        raise SystemExit("Run scripts/parse_catalog.py first.")
    with src.open(encoding="utf-8") as fh:
        records = [json.loads(l) for l in fh if l.strip()]

    report = json.loads((ROOT / "data" / "processed" / "quality_report.json").read_text())
    bundle = {
        "generated_at": report["generated_at"],
        "source_url": report["source_url"],
        "snapshot": records[0]["provenance"]["snapshot_path"],
        "snapshot_sha256": records[0]["provenance"]["snapshot_sha256"],
        "fetched_at": records[0]["provenance"]["fetched_at"],
        "department": "6",
        "checks": report["checks"],
        "courses": [compact(r) for r in records],
    }

    template = (ROOT / "web" / "template.html").read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise SystemExit("template.html is missing the data placeholder")
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    # The bundle sits inside a <script> block, so a literal "</script>" in any
    # description would end the block early.
    payload = payload.replace("</", "<\\/")
    out = ROOT / "web" / "index.html"
    out.write_text(template.replace(PLACEHOLDER, payload), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size/1024:.0f} KB, {len(records)} courses)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
