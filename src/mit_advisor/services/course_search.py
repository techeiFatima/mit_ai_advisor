"""Keyword and structured search over the course catalog.

Deliberately not embeddings.  At 423 records (a few thousand for all of MIT) a
scored token match is faster than a vector round-trip, has no model dependency,
and — the reason that matters here — is explainable: every hit can say which
term matched where.  Semantic retrieval belongs in a later phase, over the same
record store, for the questions keyword search genuinely cannot answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..ingestion.catalog.normalize import canonical

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Field weights: a title hit means much more than a description hit.
W_TITLE, W_DESC, W_NUMBER = 8.0, 1.0, 20.0

_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "course", "courses",
    "for", "from", "how", "i", "in", "into", "is", "it", "me", "mit", "of", "on",
    "or", "should", "some", "take", "that", "the", "to", "want", "what", "which",
    "with", "class", "classes", "subject", "subjects",
}


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP]


@dataclass
class SearchHit:
    course: dict
    score: float
    matched: list[str]


class CourseIndex:
    """An in-memory index over parsed course records."""

    def __init__(self, courses: list[dict]) -> None:
        self.courses = courses
        self.by_number: dict[str, dict] = {}
        for c in courses:
            self.by_number[canonical(c["subject_id"])] = c
            # Joint subjects are reachable by either department's number.
            for alias in c.get("cross_listings", []):
                self.by_number.setdefault(canonical(alias), c)
        self._tokens: dict[str, tuple[set[str], set[str]]] = {}
        for c in courses:
            self._tokens[c["subject_id"]] = (
                set(tokens(c.get("title") or "")),
                set(tokens(c.get("description") or "")),
            )

    def get(self, number: str) -> dict | None:
        return self.by_number.get(canonical(number))

    def search(self, query: str, *, level: str | None = None,
               term: str | None = None, max_units: int | None = None,
               min_units: int | None = None, attribute: str | None = None,
               limit: int = 20) -> list[SearchHit]:
        q = tokens(query)
        q_numbers = {canonical(m) for m in re.findall(r"[\dA-Z]{1,4}\.[A-Z0-9]{2,6}",
                                                      (query or "").upper())}
        hits: list[SearchHit] = []
        for c in self.courses:
            if level and c.get("level") != level:
                continue
            if term and term not in (c.get("terms_offered") or []):
                continue
            total = (c.get("units") or {}).get("total")
            if max_units is not None and (total is None or total > max_units):
                continue
            if min_units is not None and (total is None or total < min_units):
                continue
            if attribute and attribute not in (c.get("attributes") or []):
                continue

            title_toks, desc_toks = self._tokens[c["subject_id"]]
            score, matched = 0.0, []
            if canonical(c["subject_id"]) in q_numbers:
                score += W_NUMBER
                matched.append(c["subject_id"])
            for t in q:
                if t in title_toks:
                    score += W_TITLE
                    matched.append(t)
                elif t in desc_toks:
                    score += W_DESC
                    matched.append(t)
            if not q and not q_numbers:
                score = 1.0            # no query: filters alone, stable order
            if score > 0:
                hits.append(SearchHit(c, score, sorted(set(matched))))

        hits.sort(key=lambda h: (-h.score, h.course["subject_id"]))
        return hits[:limit]
