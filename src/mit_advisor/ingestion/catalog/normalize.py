"""Canonicalisation of MIT subject numbers.

The subject number is the join key for the entire system, so every shape the
catalog actually uses has to round-trip.  Shapes observed in the Course 6
snapshot (423 blocks):

    6.1000      6.S058      6.5400[J]    6.C20[J]
    6.UAT       6.EPE       6.THG        6.3900A
    18.4041J    6.S193-6.S198  (a range)

Note the two joint-subject spellings: the catalog writes ``6.5400[J]`` when the
subject is listed in this department and ``18.4041J`` when it is referring to
another department's listing of the same subject.  Both denote the same thing,
so canonicalisation strips the marker and callers compare on the canonical form.
"""
from __future__ import annotations

import re

# Department prefixes are numeric (6, 18, 21A) or alphabetic (CMS, STS, ES, HST).
DEPT = r"(?:\d{1,2}[A-Z]?|[A-Z]{2,4})"
# 6.1000 / 6.S058 / 6.UAT / 6.3900A / 18.4041J / 6.5400[J] / CMS.301 / ES.1806
SUBJECT_PATTERN = rf"{DEPT}\.[A-Z0-9]{{2,6}}(?:\[J\])?"
SUBJECT_RE = re.compile(rf"\b({DEPT})\.([A-Z0-9]{{2,6}})(\[J\]|J\b)?")

# A range such as "6.S193-6.S198".
RANGE_RE = re.compile(rf"^({SUBJECT_PATTERN})\s*[-–]\s*({SUBJECT_PATTERN})$")

GIR_NAMES = {
    "Calculus I (GIR)",
    "Calculus II (GIR)",
    "Physics I (GIR)",
    "Physics II (GIR)",
    "Chemistry (GIR)",
    "Biology (GIR)",
}


def canonical(subject: str) -> str:
    """Return the comparison key for a subject number.

    ``6.5400[J]``, ``6.5400J`` and ``6.5400`` all canonicalise to ``6.5400``.
    Whitespace and a trailing period are tolerated because the flattened
    catalog text sometimes carries them.
    """
    s = subject.strip().rstrip(".").replace(" ", "")
    s = s.replace("[J]", "").rstrip("J") if s.endswith(("[J]", "J")) else s
    return s.upper()


def is_joint(subject: str) -> bool:
    """True when the catalog marked this subject as jointly listed."""
    s = subject.strip()
    return s.endswith("[J]") or bool(re.search(r"\d[A-Z]?J$", s))


def department(subject: str) -> str | None:
    """The department prefix, e.g. ``6`` for ``6.1000``."""
    m = re.match(rf"^({DEPT})\.", subject.strip())
    return m.group(1) if m else None


def parse_range(subject: str) -> tuple[str, str] | None:
    """Split ``6.S193-6.S198`` into its endpoints, else None."""
    m = RANGE_RE.match(subject.strip())
    return (m.group(1), m.group(2)) if m else None


def find_subjects(text: str) -> list[str]:
    """Every subject number appearing in a run of catalog text, in order."""
    out: list[str] = []
    for m in SUBJECT_RE.finditer(text):
        marker = "[J]" if m.group(3) else ""
        out.append(f"{m.group(1)}.{m.group(2)}{marker}")
    return out
