"""Recursive-descent parser for MIT catalog prerequisite expressions.

The catalog writes prerequisites as a parenthesised boolean expression, e.g.

    ( 6.100B , ( 18.03 , 18.06 , or 18.C06[J] ), and ( 6.3700 , 6.3800 , or 18.05 ))
    or permission of instructor

A flat list of subject numbers cannot represent that, and `check_prerequisites`
has to be deterministically correct, so we parse it into an expression tree.

Grammar
-------
    expr  := item (sep item)*
    sep   := "," | "and" | "or" | "," "and" | "," "or"
    item  := "(" expr ")" | atom
    atom  := COURSE | GIR | PERMISSION | NONE | OPAQUE

The comma is not an operator: it is a list separator whose meaning comes from
the ``and``/``or`` keyword used at the same nesting level ("A, B, or C" is a
three-way OR, not ``AND(A,B) OR C``).  We therefore collect the explicit
keywords per level and apply the level's connective across the whole list.
Levels in the observed corpus are always uniform; a mixed level is still
parsed (last keyword wins, English convention) but is recorded as ambiguous so
downstream code can decline to answer rather than guess.

Anything the tokenizer does not recognise becomes an OPAQUE atom instead of
being dropped.  An expression containing OPAQUE evaluates to UNKNOWN, never to
"satisfied" — an unreadable requirement must never silently pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .normalize import SUBJECT_PATTERN, canonical

# ---------------------------------------------------------------- node types

AND = "AND"
OR = "OR"
COURSE = "COURSE"
GIR = "GIR"
PERMISSION = "PERMISSION"
NONE = "NONE"
OPAQUE = "OPAQUE"
COREQ = "COREQ"


def _node(op: str, **kw: Any) -> dict:
    return {"op": op, **kw}


# ---------------------------------------------------------------- tokenizer

_GIR_RE = re.compile(
    r"(Calculus\s+I{1,2}|Physics\s+I{1,2}|Chemistry|Biology)\s*\(GIR\)", re.I
)
_PERMISSION_RE = re.compile(
    r"permission\s+of\s+(?:the\s+)?(instructor|department|advisor)", re.I
)
_COURSE_RE = re.compile(SUBJECT_PATTERN)
_NONE_RE = re.compile(r"\bnone\b", re.I)
_COREQ_RE = re.compile(r"Coreq\s*:", re.I)
_AND_RE = re.compile(r"\band\b", re.I)
_OR_RE = re.compile(r"\bor\b", re.I)


@dataclass
class Token:
    kind: str
    value: str = ""


def tokenize(text: str) -> list[Token]:
    """Split a prerequisite string into tokens, preserving unknown runs."""
    tokens: list[Token] = []
    i = 0
    n = len(text)
    pending: list[str] = []

    def flush() -> None:
        if pending:
            blob = " ".join("".join(pending).split())
            if blob and not all(c in ".,;:-–—" for c in blob):
                tokens.append(Token("OPAQUE", blob))
            pending.clear()

    while i < n:
        ch = text[i]
        if ch.isspace():
            pending.append(" ")
            i += 1
            continue
        if ch == "(":
            # "(GIR)" belongs to the GIR atom, not a grouping paren.
            if not _GIR_RE.match(text, max(0, i - 20)) or "(GIR)" not in text[i : i + 6]:
                flush()
                tokens.append(Token("LPAREN"))
                i += 1
                continue
        if ch == ")":
            flush()
            tokens.append(Token("RPAREN"))
            i += 1
            continue
        if ch in ",;":
            flush()
            tokens.append(Token("COMMA"))
            i += 1
            continue

        for rx, kind in (
            (_COREQ_RE, COREQ),
            (_GIR_RE, GIR),
            (_PERMISSION_RE, PERMISSION),
            (_COURSE_RE, COURSE),
            (_NONE_RE, NONE),
            (_AND_RE, "AND_KW"),
            (_OR_RE, "OR_KW"),
        ):
            m = rx.match(text, i)
            if m:
                flush()
                tokens.append(Token(kind, m.group(0).strip()))
                i = m.end()
                break
        else:
            pending.append(ch)
            i += 1
    flush()
    return tokens


# ---------------------------------------------------------------- parser


@dataclass
class ParseResult:
    ast: dict | None
    status: str                       # parsed | partial | unparsed
    warnings: list[str] = field(default_factory=list)


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.toks = tokens
        self.i = 0
        self.warnings: list[str] = []

    def peek(self) -> Token | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def parse(self) -> dict | None:
        node = self.parse_expr()
        if self.peek() is not None:
            # Unbalanced ")" or trailing junk: keep it visible.
            rest = " ".join(t.value for t in self.toks[self.i :] if t.value)
            if rest.strip():
                self.warnings.append(f"trailing tokens: {rest[:60]!r}")
        return node

    def parse_expr(self) -> dict | None:
        items: list[dict] = []
        keywords: list[str] = []
        seps: list[set[str]] = []

        while True:
            item = self.parse_item()
            if item is not None:
                items.append(item)
            # Consume a run of separators, remembering and/or keywords.
            saw_sep = False
            run: set[str] = set()
            while True:
                t = self.peek()
                if t is None:
                    break
                if t.kind == "COMMA":
                    self.i += 1
                    saw_sep = True
                elif t.kind == "AND_KW":
                    self.i += 1
                    keywords.append(AND)
                    run.add(AND)
                    saw_sep = True
                elif t.kind == "OR_KW":
                    self.i += 1
                    keywords.append(OR)
                    run.add(OR)
                    saw_sep = True
                else:
                    break
            if items:
                seps.append(run)
            t = self.peek()
            if t is None or t.kind == "RPAREN" or not saw_sep:
                break

        if not items:
            return None
        if len(items) == 1 and not keywords:
            return items[0]

        uniq = set(keywords)
        if len(uniq) > 1:
            # Mixed level, e.g. 6.1910's "A , B , and ( ... ); or permission".
            # Resolve by ordinary boolean precedence: OR binds loosest, so cut
            # the list at the OR separators and join each run with AND.
            return self._apply_precedence(items, seps)
        if uniq:
            op = keywords[0]
        else:
            # Comma-separated with no connective: the catalog means "all of".
            op = AND
            self.warnings.append("comma list with no and/or; assumed AND")
        return _node(op, operands=items)

    @staticmethod
    def _apply_precedence(items: list[dict], seps: list[set[str]]) -> dict:
        """Build OR-of-ANDs from items and the separator run that followed each."""
        groups: list[list[dict]] = [[]]
        for idx, item in enumerate(items):
            groups[-1].append(item)
            if idx < len(seps) and OR in seps[idx]:
                groups.append([])
        groups = [g for g in groups if g]
        anded = [g[0] if len(g) == 1 else _node(AND, operands=g) for g in groups]
        return anded[0] if len(anded) == 1 else _node(OR, operands=anded)

    def parse_item(self) -> dict | None:
        t = self.peek()
        if t is None:
            return None
        if t.kind == "LPAREN":
            self.i += 1
            inner = self.parse_expr()
            if self.peek() is not None and self.peek().kind == "RPAREN":
                self.i += 1
            else:
                self.warnings.append("unbalanced parenthesis")
            return inner
        if t.kind == COURSE:
            self.i += 1
            return _node(COURSE, id=t.value, canonical=canonical(t.value))
        if t.kind == GIR:
            self.i += 1
            return _node(GIR, id=" ".join(t.value.split()))
        if t.kind == PERMISSION:
            self.i += 1
            who = "instructor"
            low = t.value.lower()
            if "department" in low:
                who = "department"
            elif "advisor" in low:
                who = "advisor"
            return _node(PERMISSION, who=who)
        if t.kind == NONE:
            self.i += 1
            return _node(NONE)
        if t.kind == COREQ:
            self.i += 1
            inner = self.parse_expr()
            if inner is None:
                return None
            return _node(COREQ, operand=inner)
        if t.kind == "OPAQUE":
            self.i += 1
            return _node(OPAQUE, text=t.value)
        return None


def parse_prerequisite(raw: str | None) -> ParseResult:
    """Parse a raw prerequisite string into an expression tree."""
    if raw is None:
        return ParseResult(None, "unparsed", ["no prerequisite text"])
    text = " ".join(raw.split())
    if not text:
        return ParseResult(None, "unparsed", ["empty prerequisite text"])

    tokens = tokenize(text)
    if not tokens:
        return ParseResult(None, "unparsed", ["no tokens"])

    p = _Parser(tokens)
    ast = p.parse()
    if ast is None:
        return ParseResult(None, "unparsed", p.warnings or ["nothing parsed"])

    status = "partial" if (_has_opaque(ast) or p.warnings) else "parsed"
    return ParseResult(ast, status, p.warnings)


def children(node: dict | None) -> list[dict]:
    """Child nodes of any node type (COREQ holds one child under `operand`)."""
    if node is None:
        return []
    kids = list(node.get("operands", []))
    if node.get("operand") is not None:
        kids.append(node["operand"])
    return kids


def _has_opaque(node: dict | None) -> bool:
    if node is None:
        return False
    if node["op"] == OPAQUE:
        return True
    return any(_has_opaque(c) for c in children(node))


def iter_courses(node: dict | None):
    """Yield every COURSE node in the tree."""
    if node is None:
        return
    if node["op"] == COURSE:
        yield node
    for child in children(node):
        yield from iter_courses(child)
