"""Deterministic evaluation of prerequisite expression trees.

This is the module that must never guess.  Every answer is one of three
values, and the third one is what keeps the system honest:

    SATISFIED    the tree evaluates true against the student's record
    NOT_SATISFIED the tree evaluates false
    UNKNOWN      the tree contains something we could not read

An unreadable requirement never reports SATISFIED.  UNKNOWN propagates through
AND and OR using three-valued (Kleene) logic, so a genuine ``OR`` with one
readable satisfied branch is still SATISFIED even if the other branch is
opaque — but an AND with an opaque branch is UNKNOWN, not satisfied.

Every evaluation returns the reasoning tree alongside the verdict, which is the
audit trail the product promises: not just "yes", but which branch said yes.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..ingestion.catalog.normalize import canonical

SATISFIED = "SATISFIED"
NOT_SATISFIED = "NOT_SATISFIED"
UNKNOWN = "UNKNOWN"


@dataclass
class Evaluation:
    status: str
    detail: dict            # mirror of the AST annotated with per-node status
    missing: list[str]      # subjects that would flip a NOT_SATISFIED branch
    unknown_reasons: list[str]

    @property
    def satisfied(self) -> bool:
        return self.status == SATISFIED


def _and(values: list[str]) -> str:
    if any(v == NOT_SATISFIED for v in values):
        return NOT_SATISFIED
    if any(v == UNKNOWN for v in values):
        return UNKNOWN
    return SATISFIED


def _or(values: list[str]) -> str:
    if any(v == SATISFIED for v in values):
        return SATISFIED
    if any(v == UNKNOWN for v in values):
        return UNKNOWN
    return NOT_SATISFIED


def evaluate(node: dict | None, *, completed: set[str],
             in_progress: set[str] | None = None,
             permissions: set[str] | None = None,
             gir_credit: set[str] | None = None,
             treat_in_progress_as_done: bool = False) -> Evaluation:
    """Evaluate a prerequisite tree against a student's record."""
    in_progress = in_progress or set()
    permissions = permissions or set()
    gir_credit = gir_credit or set()
    missing: list[str] = []
    unknown: list[str] = []

    def walk(n: dict | None) -> tuple[str, dict]:
        if n is None:
            # No prerequisite recorded at all: nothing to satisfy.
            return SATISFIED, {"op": "NONE", "status": SATISFIED}
        op = n["op"]

        if op == "NONE":
            return SATISFIED, {"op": op, "status": SATISFIED}

        if op == "COURSE":
            key = n.get("canonical") or canonical(n["id"])
            if key in completed or (treat_in_progress_as_done and key in in_progress):
                st = SATISFIED
            else:
                st = NOT_SATISFIED
                missing.append(n["id"])
            return st, {"op": op, "id": n["id"], "status": st}

        if op == "GIR":
            name = n["id"]
            if name in gir_credit:
                st = SATISFIED
            else:
                # We have no authoritative GIR-completion source, so a GIR we
                # were not explicitly told about is UNKNOWN, never satisfied.
                st = UNKNOWN
                unknown.append(f"GIR not recorded: {name}")
            return st, {"op": op, "id": name, "status": st}

        if op == "PERMISSION":
            who = n.get("who", "instructor")
            st = SATISFIED if who in permissions else UNKNOWN
            if st == UNKNOWN:
                unknown.append(f"requires permission of {who}")
            return st, {"op": op, "who": who, "status": st}

        if op == "COREQ":
            # A corequisite may be taken concurrently, so in-progress counts.
            inner_status, inner_detail = walk(n["operand"])
            if inner_status != SATISFIED:
                st2, d2 = _walk_allowing_concurrent(n["operand"])
                if st2 == SATISFIED:
                    return SATISFIED, {"op": op, "status": SATISFIED, "operand": d2}
            return inner_status, {"op": op, "status": inner_status,
                                  "operand": inner_detail}

        if op == "OPAQUE":
            unknown.append(f"unparsed requirement: {n['text'][:80]}")
            return UNKNOWN, {"op": op, "text": n["text"], "status": UNKNOWN}

        if op in ("AND", "OR"):
            results = [walk(c) for c in n.get("operands", [])]
            statuses = [r[0] for r in results]
            st = _and(statuses) if op == "AND" else _or(statuses)
            return st, {"op": op, "status": st,
                        "operands": [r[1] for r in results]}

        unknown.append(f"unrecognised node: {op}")
        return UNKNOWN, {"op": op, "status": UNKNOWN}

    def _walk_allowing_concurrent(n: dict) -> tuple[str, dict]:
        sub = evaluate(n, completed=completed | in_progress,
                       in_progress=in_progress, permissions=permissions,
                       gir_credit=gir_credit, treat_in_progress_as_done=True)
        return sub.status, sub.detail

    status, detail = walk(node)
    # A satisfied OR branch makes sibling "missing" entries irrelevant.
    if status == SATISFIED:
        missing = []
    return Evaluation(status, detail, sorted(set(missing)), sorted(set(unknown)))


def explain(detail: dict, indent: int = 0) -> str:
    """Render an evaluation tree as indented text (used by the CLI and tools)."""
    pad = "  " * indent
    op = detail["op"]
    st = detail.get("status", "?")
    mark = {"SATISFIED": "OK  ", "NOT_SATISFIED": "MISS", "UNKNOWN": "????"}.get(st, "    ")
    if op in ("AND", "OR"):
        head = f"{pad}[{mark}] {op}"
        return "\n".join([head] + [explain(c, indent + 1)
                                   for c in detail.get("operands", [])])
    if op == "COREQ":
        return f"{pad}[{mark}] COREQ\n" + explain(detail["operand"], indent + 1)
    label = detail.get("id") or detail.get("who") or detail.get("text", "")
    return f"{pad}[{mark}] {op} {label}".rstrip()
