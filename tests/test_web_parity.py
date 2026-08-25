"""The browser evaluator must agree with the Python engine, course for course.

The published page has no backend, so services/prerequisite_engine.py is ported
to JavaScript.  Two implementations of the same rules is exactly the setup where
a subtle divergence goes unnoticed for months - especially in three-valued
logic, where the interesting cases are the UNKNOWN ones nobody eyeballs.  This
test runs the real shipped evaluator under node against the real catalog and
compares all three verdicts on every subject.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

from mit_advisor.ingestion.catalog.normalize import canonical
from mit_advisor.services.prerequisite_engine import evaluate

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "web" / "template.html"

PROFILES = [
    {"done": [], "now": [], "gir": [], "perm": False},
    {"done": ["6.100A", "6.100B", "6.1010", "6.1210"], "now": ["6.1200[J]"],
     "gir": ["Calculus II (GIR)", "Physics II (GIR)"], "perm": False},
    {"done": ["6.100A", "6.1010", "6.1020", "6.1910", "6.3700"], "now": [],
     "gir": ["Calculus I (GIR)", "Calculus II (GIR)", "Physics I (GIR)",
             "Physics II (GIR)"], "perm": True},
]


def extract_evaluator() -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"/\*__EVAL_START__\*/(.*?)/\*__EVAL_END__\*/", src, re.S)
    assert m, "evaluator markers missing from web/template.html"
    body = m.group(1)
    # The block references COURSES for its lookup map; node supplies it.
    return body


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_browser_evaluator_matches_python(records, tmp_path):
    courses = [{"id": r["subject_id"], "pa": r["prerequisites"]["ast"],
                "xl": r["cross_listings"]} for r in records]

    script = tmp_path / "parity.mjs"
    script.write_text(
        "const COURSES = " + json.dumps(courses) + ";\n"
        + extract_evaluator()
        + "\nconst PROFILES = " + json.dumps(PROFILES) + ";\n"
        + """
const out = PROFILES.map(p => {
  const ctx = {completed:new Set(p.done.map(canon)),
               inProgress:new Set(p.now.map(canon)),
               gir:new Set(p.gir),
               perms:new Set(p.perm?["instructor","department"]:[])};
  const o = {};
  for (const c of COURSES) o[c.id] = evaluate(c.pa, ctx).status;
  return o;
});
process.stdout.write(JSON.stringify(out));
""", encoding="utf-8")

    res = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    js_results = json.loads(res.stdout)

    for profile, js in zip(PROFILES, js_results):
        completed = {canonical(x) for x in profile["done"]}
        in_progress = {canonical(x) for x in profile["now"]}
        perms = {"instructor", "department"} if profile["perm"] else set()
        mismatches = []
        for r in records:
            py = evaluate(r["prerequisites"]["ast"], completed=completed,
                          in_progress=in_progress, permissions=perms,
                          gir_credit=set(profile["gir"])).status
            if py != js.get(r["subject_id"]):
                mismatches.append((r["subject_id"], py, js.get(r["subject_id"])))
        assert not mismatches, f"JS/Python divergence: {mismatches[:8]}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_all_three_verdicts_are_exercised(records):
    """A parity test that only ever sees one verdict proves nothing."""
    completed = {canonical(x) for x in ["6.100A", "6.100B", "6.1010", "6.1210"]}
    seen = {evaluate(r["prerequisites"]["ast"], completed=completed,
                     gir_credit={"Calculus II (GIR)"}).status for r in records}
    assert seen == {"SATISFIED", "NOT_SATISFIED", "UNKNOWN"}
