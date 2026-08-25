# Course 6 Advisor

A grounded academic advisor over MIT's Course 6 (EECS) subject catalog. It parses
the catalog into structured records, evaluates prerequisites as boolean expression
trees, and plans multi-semester course sequences — deterministically, with every
claim traceable to its source.

```bash
pip install -e ".[dev]"
python scripts/parse_catalog.py     # snapshot -> data/processed/courses.jsonl + quality report
python scripts/build_web.py         # -> web/index.html (self-contained)
python -m pytest                    # 98 tests
```

## What's here

```
src/mit_advisor/
  ingestion/catalog/
    normalize.py         subject-number canonicalisation (the system's join key)
    prereq_parser.py     recursive-descent parser -> prerequisite expression trees
    snapshot_parser.py   flattened catalog text -> structured records
  models/student.py      the student model (general; no personal data in code)
  services/
    prerequisite_engine.py  three-valued evaluation of prerequisite trees
    course_search.py        keyword + structured search
    planning_engine.py      constrained multi-semester scheduler
  quality/invariants.py  data-quality gate; fails the build on silent degradation
  advisor/               Claude tool surface + conversational CLI
web/                     self-contained browser app (deterministic engines in JS)
tests/                   98 tests, including JS/Python parity
```

## The two things that matter most

**Prerequisites are trees, not lists.** The catalog writes them as nested boolean
expressions:

```
( 6.100B , ( 18.03 , 18.06 , or 18.C06[J] ), and ( 6.3700 , 6.3800 , or 18.05 ))
or permission of instructor
```

A flat list of subject numbers cannot represent that, and `check_prerequisites`
must be deterministically correct, so `prereq_parser.py` parses it into an AST.
All 423 subjects in the snapshot parse; the grammar is pinned by tests built from
the real strings.

**Answers are three-valued.** `SATISFIED`, `NOT_SATISFIED`, and `UNKNOWN`, combined
with Kleene logic. An unreadable requirement — an instructor-permission clause, a
GIR the student hasn't recorded — evaluates to `UNKNOWN` and is never rounded up to
a yes. "I couldn't verify this" is a supported answer, not a failure.

## Fact vs. recommendation

Enforced at the data layer, not just in prompts. Every tool result carries a `kind`:

| `kind` | Meaning |
|---|---|
| `catalog_fact` | stated by the catalog; carries provenance |
| `computed_fact` | derived deterministically from catalog data + the student's record |
| `unavailable` | no authoritative source; the model must say so |

Interests affect **ranking only** — never whether a course is eligible.

## The web app

`web/index.html` is fully self-contained: the parsed catalog and the prerequisite
trees ship with the page, and the browser re-implements only the *evaluator*, never
the parser. `tests/test_web_parity.py` runs the shipped JavaScript under node against
the real catalog and asserts it agrees with the Python engine on every subject across
three student profiles — the two implementations cannot silently drift.

No language model runs in the page. Same inputs, same answer, every time.

## The conversational advisor

```bash
pip install -e ".[advisor]"
export ANTHROPIC_API_KEY=...        # or: ant auth login
python -m mit_advisor.advisor.cli --ask "Can I take 6.3900 if I've done 6.1010?"
```

Claude is the reasoning layer, not the database: it answers only through the tools
in `advisor/tools/registry.py`, and `advisor/prompts.py` instructs it to report
`UNKNOWN` and `unavailable` honestly rather than filling gaps from memory. It needs
an API key, so it is not part of the hosted page.

## What this does not know

These are dataset limits, surfaced in the UI rather than papered over:

* **No degree requirements at all** — no GIRs, HASS, CI-H/CI-M, major, minor or
  concentration requirements. There is no degree-progress bar because there is no
  authoritative source behind one.
* **Course 6 only.** Prerequisites naming other departments are shown but not
  resolvable.
* **CI-M and CI-H are missing entirely.** The original flattening dropped every
  communication designator before the snapshot was written — 6.UAT is a CI-M
  subject and carries no marker. The quality gate asserts this as a named `WARN`
  so it can't pass unnoticed.
* **No fetch date.** The snapshot records none, so offerings may be stale.
* **Instructors are heuristic** (~73% recovered) and labelled as such.
* **51 subjects have no description** — jointly listed, text under another department.

## Data quality

`scripts/parse_catalog.py` writes `data/processed/quality_report.json` and exits
non-zero if an error-severity invariant fails. Current run: 423/423 blocks parsed,
0 parse errors, 423/423 prerequisite trees parsed, 1 warning (the CI-M gap above).

The invariants exist because the original scraper printed success whether it
extracted 423 courses or zero. Extraction degrading silently while the pipeline
reports success is the failure mode this guards against.

## Ingestion status

The current pipeline parses the committed `mit_courses.txt` snapshot, because
`catalog.mit.edu` is unreachable from the environment this was built in. The parser
recovers everything the flattened text still supports; instructors and CI-M/CI-H
are the fields that flattening destroyed. Direct HTML ingestion — which would
recover both, plus proper element boundaries — is the next step, and
`ingestion/catalog/` is laid out so it slots in beside the snapshot parser rather
than replacing the pipeline.

## Not an official MIT tool

Unaffiliated student project. Course data is reproduced from the MIT subject catalog
for academic planning. Output is not an academic record — confirm with your
department and the official catalog.
