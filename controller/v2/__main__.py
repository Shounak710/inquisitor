from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from controller.v1.cli import cli_ask
from controller.v1.types import Mode
from controller.v2.loop import run_v2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Controller v2. design asks for design-level input, "
            "detailed asks for function-level input, llm asks for none."
        )
    )
    parser.add_argument("goal")
    parser.add_argument("--mode", choices=[mode.value for mode in Mode], default=Mode.DESIGN.value)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--decisions", type=Path, default=None)
    parser.add_argument(
        "--complete",
        required=True,
        help=(
            "Program that reads a JSON request (system, tools, messages) on stdin "
            "and writes a JSON reply (content, tool_calls, writes) on stdout."
        ),
    )
    args = parser.parse_args(argv)
    result = run_v2(
        goal=args.goal,
        repo=args.repo,
        complete=_command_complete(args.complete),
        ask=cli_ask,
        decisions_dir=args.decisions,
        mode=Mode(args.mode),
    )
    print(result.summary)
    if result.records_written:
        print("\nRecorded:")
        for record_id in result.records_written:
            print(f"- {record_id}")
    if result.files_written:
        print("\nWrote:")
        for path in result.files_written:
            print(f"- {path}")
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


if __name__ == "__main__":
    raise SystemExit(main())
