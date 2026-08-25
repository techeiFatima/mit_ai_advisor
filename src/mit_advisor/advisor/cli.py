"""Conversational advisor: Claude with the tool surface in tools/registry.py.

A manual tool-use loop rather than the SDK's tool runner - the point of this
module is that the orchestration is visible and steppable, since the whole
architecture rests on Claude calling tools instead of recalling facts.

    export ANTHROPIC_API_KEY=...        # or: ant auth login
    python -m mit_advisor.advisor.cli
    python -m mit_advisor.advisor.cli --ask "Can I take 6.3900 if I've done 6.100A?"
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from ..services.course_search import CourseIndex
from .prompts import SYSTEM_PROMPT
from .tools.registry import TOOL_DEFINITIONS, ToolRegistry

MODEL = "claude-opus-5"
DATA = pathlib.Path(__file__).resolve().parents[3] / "data" / "processed" / "courses.jsonl"


def load_index(path: pathlib.Path = DATA) -> CourseIndex:
    if not path.exists():
        raise SystemExit(f"No parsed catalog at {path}. Run: python scripts/parse_catalog.py")
    with path.open(encoding="utf-8") as fh:
        return CourseIndex([json.loads(line) for line in fh if line.strip()])


def run_turn(client, registry, messages: list[dict], *, verbose: bool = True) -> str:
    """One user turn: loop until Claude stops asking for tools."""
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            thinking={"type": "adaptive"},
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if verbose:
                print(f"  · {block.name}({json.dumps(block.input)[:110]})",
                      file=sys.stderr)
            out = registry.call(block.name, dict(block.input))
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(out, ensure_ascii=False, default=str),
                "is_error": out.get("kind") == "error",
            })
        # All tool results for one assistant turn go back in a single message.
        messages.append({"role": "user", "content": results})


def main() -> int:
    ap = argparse.ArgumentParser(description="MIT academic advisor (Claude + tools)")
    ap.add_argument("--ask", help="Ask one question and exit.")
    ap.add_argument("--quiet", action="store_true", help="Hide tool-call trace.")
    args = ap.parse_args()

    try:
        import anthropic
    except ImportError:
        raise SystemExit("pip install 'anthropic' (or: pip install -e '.[advisor]')")

    registry = ToolRegistry(load_index())
    client = anthropic.Anthropic()
    messages: list[dict] = []

    def ask(question: str) -> None:
        messages.append({"role": "user", "content": question})
        try:
            print(run_turn(client, registry, messages, verbose=not args.quiet))
        except anthropic.AuthenticationError:
            raise SystemExit("No valid credentials. Set ANTHROPIC_API_KEY or run 'ant auth login'.")
        except anthropic.RateLimitError:
            print("Rate limited - try again shortly.", file=sys.stderr)
        except anthropic.APIConnectionError:
            print("Network error reaching the Claude API.", file=sys.stderr)

    if args.ask:
        ask(args.ask)
        return 0

    print("MIT advisor. Catalog: Course 6 subjects only; no degree requirements "
          "loaded.\nCtrl-C or 'quit' to exit.\n")
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if q.lower() in {"quit", "exit"}:
            return 0
        if q:
            ask(q)
            print()


if __name__ == "__main__":
    raise SystemExit(main())
