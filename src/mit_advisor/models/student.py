"""The student model.

Deliberately general: the advisor must work for a first-year exploring majors
and for a senior mid-transfer.  Nothing about any individual student is baked
into the code — a profile is data supplied at call time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..ingestion.catalog.normalize import canonical


@dataclass
class StudentProfile:
    year: int | None = None                    # 1-4, or None if unknown
    major: str | None = None                   # e.g. "6-4"; informational only
    minor: str | None = None
    concentration: str | None = None
    completed_courses: list[str] = field(default_factory=list)
    current_courses: list[str] = field(default_factory=list)
    interests: list[str] = field(default_factory=list)
    career_goals: list[str] = field(default_factory=list)
    academic_goals: list[str] = field(default_factory=list)
    max_units_per_term: int = 48
    permissions: list[str] = field(default_factory=list)   # e.g. ["instructor"]

    @property
    def completed_set(self) -> set[str]:
        return {canonical(c) for c in self.completed_courses}

    @property
    def current_set(self) -> set[str]:
        return {canonical(c) for c in self.current_courses}

    @classmethod
    def from_dict(cls, data: dict) -> "StudentProfile":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})
