"""Parse the committed flattened-text catalog snapshot into structured records.

This is a *recovery* parser.  The original scraper called ``get_text()`` on each
``courseblock`` div, which destroyed the element boundaries; this module rebuilds
as much structure as the flattened text still supports.

It is deliberately separate from the HTML parser this project should eventually
use.  Two fields are not recoverable here and are reported as missing rather
than guessed:

* **instructors** — appended to the description with no delimiter.  A strict
  trailing-initials heuristic is applied and the result is labelled
  ``extraction_method: "heuristic"`` so callers can discount it.
* **CI-M / CI-H attributes** — absent from the snapshot entirely (0 of 423
  blocks, including 6.UAT, which is a CI-M subject).  They were dropped before
  the text was written, so no parser can recover them.

Field order in a block, established empirically over all 423 blocks:

    NUMBER TITLE [(New)] [Same subject as ...] [Subject meets with ...]
    Prereq: ... [Acad Year YYYY-YYYY: ...] LEVEL (TERMS)
    [Not offered regularly; consult department] UNITS [[P/D/F]] [attributes]
    [Can be repeated for credit.] [Credit cannot also be received for ...]
    DESCRIPTION [instructors]
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .normalize import (SUBJECT_PATTERN, canonical, department, find_subjects,
                        is_joint, parse_range)
from .prereq_parser import parse_prerequisite

SEPARATOR = "-" * 50

_NUMBER_RE = re.compile(rf"^\s*({SUBJECT_PATTERN}(?:\s*[-–]\s*{SUBJECT_PATTERN})?)\s+")
_LEVEL_RE = re.compile(r"\b([UG])\s*\(\s*([^)]{1,60}?)\s*\)")
_TERM_WORDS = ("Fall", "Spring", "IAP", "Summer")
_UNITS_RE = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{1,2})\s+units\b\.?")
_UNITS_ARRANGED_RE = re.compile(r"\bUnits\s+arranged\b", re.I)
_ACAD_YEAR_RE = re.compile(r"Acad\s+Year\s+(\d{4}-\d{4})\s*:\s*(Not\s+offered)?", re.I)
_SAME_AS_RE = re.compile(r"Same\s+subject\s+as\s+(.*?)(?=Subject\s+meets\s+with|Prereq:|$)", re.S)
_MEETS_WITH_RE = re.compile(r"Subject\s+meets\s+with\s+(.*?)(?=Prereq:|$)", re.S)
_CREDIT_EXCL_RE = re.compile(
    rf"Credit\s+cannot\s+also\s+be\s+received\s+for\s+"
    rf"({SUBJECT_PATTERN}(?:\s*,\s*(?:or\s+)?{SUBJECT_PATTERN})*)"
)
_STUB_RE = re.compile(rf"See\s+description\s+under\s+subject\s+({SUBJECT_PATTERN})", re.I)
_PDF_RE = re.compile(r"\[P/D/F\]")
_REPEAT_RE = re.compile(r"Can\s+be\s+repeated\s+for\s+credit\.?", re.I)
_NOT_REGULAR_RE = re.compile(r"Not\s+offered\s+regularly;\s*consult\s+department", re.I)
_ENROLL_RE = re.compile(r"Enrollment\s+(?:limited|may\s+be\s+limited)", re.I)
_NEW_RE = re.compile(r"\(New\)")

# Attribute badges that DID survive flattening.  CI-M/CI-H did not - see module
# docstring; their absence is asserted as an invariant, not silently accepted.
_ATTRIBUTE_PATTERNS = [
    (re.compile(r"\bREST\b"), "REST"),
    (re.compile(r"\bInstitute\s+LAB\b", re.I), "Institute LAB"),
    (re.compile(r"\bPartial\s+Lab\b", re.I), "Partial LAB"),
    (re.compile(r"\bHASS-(A|H|S)\b"), "HASS"),
    (re.compile(r"\bCI-M\b"), "CI-M"),
    (re.compile(r"\bCI-H\b"), "CI-H"),
]

# A trailing run of "A. Surname" / "A. B. Surname" / "Staff", comma separated.
_NAME = r"(?:[A-Z]\.\s*){1,3}[A-Z][A-Za-z'’\-]+(?:\s+[A-Z][A-Za-z'’\-]+){0,2}"
_INSTRUCTOR_TAIL_RE = re.compile(
    rf"(?<=[.!?])\s+((?:{_NAME}|Staff)(?:\s*,\s*(?:{_NAME}|Staff))*)\s*$"
)


def _find_top_level_coreq(text: str) -> tuple[int, int] | None:
    """Locate a ``Coreq:`` marker outside any parentheses.

    6.1910 writes ``... and ( Coreq: 6.1903 or 6.1904 )`` - that corequisite is
    an operand of the prerequisite expression, not a separate clause, so only a
    depth-0 marker splits the field.
    """
    depth = 0
    for m in re.finditer(r"[()]|Coreq\s*:", text, re.I):
        tok = m.group(0)
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            return (m.start(), m.end())
    return None


def _split_subject_list(blob: str) -> list[str]:
    return find_subjects(blob)


def _extract_instructors(description: str) -> tuple[str, list[str], str]:
    """Split a trailing instructor run off the description.

    Returns ``(description, instructors, method)``.  Only a confident match is
    accepted; otherwise the description is returned whole and instructors are
    empty.  ``method`` is always ``"heuristic"`` when names were taken, so the
    uncertainty travels with the data.
    """
    m = _INSTRUCTOR_TAIL_RE.search(description)
    if not m or m.start() == 0:
        return description, [], "none"
    head = description[: m.start()].rstrip()
    if not head.endswith((".", "!", "?")):
        return description, [], "none"
    names = [n.strip() for n in m.group(1).split(",") if n.strip()]
    if not names or any(len(n) > 40 for n in names):
        return description, [], "none"
    return head, names, "heuristic"


def parse_block(block: str, *, provenance: dict[str, Any] | None = None) -> dict:
    """Parse one flattened ``courseblock`` into a structured record."""
    errors: list[str] = []
    text = " ".join(block.split())

    rec: dict[str, Any] = {
        "subject_id": None,
        "subject_number": None,
        "department": None,
        "is_joint": False,
        "number_range": None,
        "title": None,
        "level": None,
        "units": {"arranged": True, "lecture": None, "lab": None,
                  "preparation": None, "total": None},
        "terms_offered": [],
        "offering_notes": {"not_offered_regularly": False, "academic_years": {}},
        "prerequisites": {"raw": None, "parse_status": "unparsed", "ast": None,
                          "warnings": []},
        "corequisites": {"raw": None, "parse_status": "unparsed", "ast": None,
                         "warnings": []},
        "cross_listings": [],
        "meets_with": [],
        "credit_excluded": [],
        "attributes": [],
        "grading": {"pdf_option": False},
        "repeatable": False,
        "enrollment_limited": False,
        "is_new": False,
        "description": "",
        "description_is_stub": False,
        "description_source": None,
        "instructors": [],
        "instructors_extraction": "none",
        "provenance": dict(provenance or {}),
        "parse_errors": errors,
    }

    # --- subject number -------------------------------------------------
    m = _NUMBER_RE.match(text)
    if not m:
        errors.append("no subject number at start of block")
        rec["description"] = text
        return rec
    number = " ".join(m.group(1).split())
    rest = text[m.end():]
    rng = parse_range(number)
    if rng:
        # Keep the range as its own key - 6.S193 also exists as a standalone
        # subject, so collapsing to the first endpoint creates a duplicate.
        rec["number_range"] = list(rng)
        rec["subject_id"] = number
        rec["subject_number"] = f"{canonical(rng[0])}-{canonical(rng[1])}"
    else:
        rec["subject_id"] = number
        rec["subject_number"] = canonical(number)
    rec["is_joint"] = is_joint(number)
    rec["department"] = department(number)

    # --- title, cross-listings, meets-with -------------------------------
    head_end = len(rest)
    for rx in (re.compile(r"Same\s+subject\s+as"), re.compile(r"Subject\s+meets\s+with"),
               re.compile(r"Prereq:")):
        mm = rx.search(rest)
        if mm:
            head_end = min(head_end, mm.start())
    title = rest[:head_end].strip()
    if _NEW_RE.search(title):
        rec["is_new"] = True
        title = _NEW_RE.sub("", title).strip()
    rec["title"] = title or None
    if not title:
        errors.append("empty title")

    mm = _SAME_AS_RE.search(rest)
    if mm:
        rec["cross_listings"] = _split_subject_list(mm.group(1))
    mm = _MEETS_WITH_RE.search(rest)
    if mm:
        rec["meets_with"] = _split_subject_list(mm.group(1))

    # --- level and terms (the anchor that ends the prereq span) ----------
    lm = None
    for cand in _LEVEL_RE.finditer(rest):
        inside = cand.group(2)
        term_part = inside.split(";")[0]
        terms = [t.strip() for t in term_part.split(",") if t.strip() in _TERM_WORDS]
        if not terms:
            continue          # e.g. "(GIR)" or prose - not the level marker
        lm = cand
        rec["level"] = cand.group(1)
        rec["terms_offered"] = terms
        if ";" in inside:
            rec["offering_notes"]["term_note"] = inside.split(";", 1)[1].strip()
        break
    if lm is None:
        errors.append("no level/terms marker")

    # --- prerequisites ---------------------------------------------------
    pm = re.search(r"Prereq:\s*", rest)
    if pm:
        span_end = lm.start() if lm else len(rest)
        prereq_span = rest[pm.end(): span_end].strip() if span_end > pm.end() else ""
        # Alternating-year offering text lives inside this span; lift it out
        # before parsing so it is never mistaken for a requirement.
        for am in _ACAD_YEAR_RE.finditer(prereq_span):
            rec["offering_notes"]["academic_years"][am.group(1)] = (
                "not_offered" if am.group(2) else "offered"
            )
        prereq_span = _ACAD_YEAR_RE.sub(" ", prereq_span).strip(" ,;")
        # A "Coreq:" clause can follow the prereq clause.
        cm = _find_top_level_coreq(prereq_span)
        if cm is not None:
            coreq_raw = prereq_span[cm[1]:].strip(" ,;.")
            prereq_span = prereq_span[: cm[0]].strip(" ,;.")
            cres = parse_prerequisite(coreq_raw)
            rec["corequisites"] = {"raw": coreq_raw, "parse_status": cres.status,
                                   "ast": cres.ast, "warnings": cres.warnings}
        prereq_span = prereq_span.strip(" ,;.")
        rec["prerequisites"]["raw"] = prereq_span or None
        pres = parse_prerequisite(prereq_span)
        rec["prerequisites"].update(parse_status=pres.status, ast=pres.ast,
                                    warnings=pres.warnings)
    else:
        errors.append("no Prereq: marker")

    # --- everything after the level marker -------------------------------
    tail = rest[lm.end():] if lm else rest

    if _NOT_REGULAR_RE.search(tail):
        rec["offering_notes"]["not_offered_regularly"] = True
        tail = _NOT_REGULAR_RE.sub(" ", tail)

    um = _UNITS_RE.search(tail)
    if um:
        lec, lab, prep = (int(um.group(i)) for i in (1, 2, 3))
        rec["units"] = {"arranged": False, "lecture": lec, "lab": lab,
                        "preparation": prep, "total": lec + lab + prep}
        tail = tail[: um.start()] + " " + tail[um.end():]
    elif _UNITS_ARRANGED_RE.search(tail):
        tail = _UNITS_ARRANGED_RE.sub(" ", tail)
    else:
        errors.append("no units found")

    if _PDF_RE.search(tail):
        rec["grading"]["pdf_option"] = True
        tail = _PDF_RE.sub(" ", tail)

    for rx, label in _ATTRIBUTE_PATTERNS:
        am = rx.search(tail)
        if am:
            rec["attributes"].append(am.group(0).strip() if label == "HASS" else label)
            tail = tail[: am.start()] + " " + tail[am.end():]

    if _REPEAT_RE.search(tail):
        rec["repeatable"] = True
        tail = _REPEAT_RE.sub(" ", tail)

    cm2 = _CREDIT_EXCL_RE.search(tail)
    if cm2:
        rec["credit_excluded"] = _split_subject_list(cm2.group(1))
        tail = tail[: cm2.start()] + " " + tail[cm2.end():]

    if _ENROLL_RE.search(tail):
        rec["enrollment_limited"] = True

    sm = _STUB_RE.search(tail)
    if sm:
        rec["description_is_stub"] = True
        rec["description_source"] = sm.group(1)

    description = " ".join(tail.split()).strip(" ,;")
    description, instructors, method = _extract_instructors(description)
    description = description.strip(" ,;")
    if description and not description.endswith((".", "!", "?")):
        description += "."
    rec["description"] = description
    rec["instructors"] = instructors
    rec["instructors_extraction"] = method

    if not description:
        errors.append("empty description")
    return rec


def parse_snapshot(text: str, *, source_url: str, fetched_at: str,
                   snapshot_path: str) -> list[dict]:
    """Parse the whole flattened snapshot into records."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    blocks = [b.strip() for b in text.split(SEPARATOR) if b.strip()]
    out = []
    for idx, block in enumerate(blocks):
        provenance = {
            "source_url": source_url,
            "fetched_at": fetched_at,
            "snapshot_path": snapshot_path,
            "snapshot_sha256": f"sha256:{digest}",
            "block_index": idx,
            "parser": "snapshot_parser",
            "parser_version": "0.1.0",
        }
        out.append(parse_block(block, provenance=provenance))
    return out
