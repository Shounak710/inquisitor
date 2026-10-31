from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from controller.coder import ModelCoder, SpecCoder
from controller.finder import KeywordFinder, ModelFinder
from controller.loop import run_task
from controller.types import Answer, Mode, Question


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Decide when to ask a human before a coding model runs."
    )
    parser.add_argument("goal")
    parser.add_argument("--mode", choices=[mode.value for mode in Mode], default=Mode.DESIGN.value)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--decisions", type=Path, default=None)
    parser.add_argument(
        "--complete",
        help="Program that reads a prompt on stdin and writes the model reply on stdout.",
    )
    args = parser.parse_args(argv)

    if args.complete:
        complete = _command_complete(args.complete)
        finder = ModelFinder(complete)
        coder = ModelCoder(complete, args.repo)
    else:
        print("Finder: keyword rules. Pass --complete to call a model.", file=sys.stderr)
        finder = KeywordFinder()
        coder = SpecCoder()
    result = run_task(
        goal=args.goal,
        mode=Mode(args.mode),
        repo=args.repo,
        finder=finder,
        coder=coder,
        ask=cli_ask,
        decisions_dir=args.decisions,
    )
    print(result.summary)
    if result.assumptions:
        print("\nAssumptions:")
        for assumption in result.assumptions:
            print(f"- {assumption}")
    if result.records_written:
        print("\nRecorded:")
        for record_id in result.records_written:
            print(f"- {record_id}")
    if result.unresolved is not None:
        print(f"\nUnresolved: {result.unresolved.question}", file=sys.stderr)
        return 2
    return 0


def _command_complete(command: str):
    argv = shlex.split(command)

    def complete(prompt: str) -> str:
        proc = subprocess.run(argv, input=prompt, text=True, capture_output=True, check=False)
        if proc.returncode != 0:
            detail = proc.stderr.strip() or f"exited {proc.returncode}"
            raise RuntimeError(detail)
        return proc.stdout

    return complete


def cli_ask(questions: list[Question]) -> list[Answer]:
    answers = []
    for question in questions:
        print(f"\n{question.prompt}")
        for index, option in enumerate(question.options, 1):
            mark = " (recommended)" if option.id == question.recommended else ""
            print(f"  {index}. {option.label}{mark}")
        if question.options and question.recommended:
            print("  Press enter to take the recommendation, or type the option number or your own answer.")
        elif question.options:
            print("  Type the option number, or your own answer.")
        else:
            print("  Type your answer.")
        raw = input("> ").strip()
        answers.append(_parse_reply(question, raw))
    return answers


def _parse_reply(question: Question, raw: str) -> Answer:
    if raw.isdigit():
        index = int(raw) - 1
        if 0 <= index < len(question.options):
            return Answer(question.fork_id, option_id=question.options[index].id)
    if raw == "" or raw.lower() in {"you pick", "you decide"}:
        if question.recommended:
            return Answer(question.fork_id, option_id=question.recommended)
    return Answer(question.fork_id, text=raw)


if __name__ == "__main__":
    raise SystemExit(main())
