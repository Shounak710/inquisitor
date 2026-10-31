from __future__ import annotations

from pathlib import Path

from controller.finder import Complete, load_json_text, parse_fork, strip_fence
from controller.types import CoderResult, Constraint, Hit, Mode


class SpecCoder:
    """Prints the closed spec when no model command is passed."""

    def implement(
        self,
        goal: str,
        constraints: list[Constraint],
        hits: list[Hit],
        mode: Mode,
    ) -> CoderResult:
        constraint_lines = [f"- {item.text}" for item in constraints] or ["- none yet"]
        paths = list(dict.fromkeys(hit.path for hit in hits))
        file_lines = [f"- {path}" for path in paths] or ["- none yet"]
        summary = (
            "No model call yet. Closed spec:\n\n"
            f"Implement: {goal}\n\n"
            "Constraints:\n"
            + "\n".join(constraint_lines)
            + "\n\nFiles:\n"
            + "\n".join(file_lines)
        )
        if mode is Mode.LLM:
            assumptions = ("Design choices were left to the coder.",)
        else:
            assumptions = ()
        return CoderResult(summary=summary, assumptions=assumptions, files_used=tuple(paths))


class ModelCoder:
    def __init__(self, complete: Complete, repo: Path):
        self.complete = complete
        self.repo = repo

    def implement(
        self,
        goal: str,
        constraints: list[Constraint],
        hits: list[Hit],
        mode: Mode,
    ) -> CoderResult:
        result, writes = parse_coder_result(
            self.complete(build_coder_prompt(goal, constraints, hits, mode))
        )
        if result.blocked is not None or not writes:
            return result
        written = apply_writes(self.repo, writes)
        files_used = result.files_used or written
        return CoderResult(
            summary=result.summary,
            assumptions=result.assumptions,
            blocked=None,
            files_used=files_used,
        )


def build_coder_prompt(
    goal: str,
    constraints: list[Constraint],
    hits: list[Hit],
    mode: Mode,
) -> str:
    constraint_lines = "\n".join(_constraint_line(item) for item in constraints) or "- none"
    hit_lines = "\n".join(f"- {hit.path}:{hit.line} {hit.text}" for hit in hits) or "- none"
    return f"""Implement the task. Return JSON only:
{{"summary": "...", "assumptions": [], "blocked": null, "files_used": [], "writes": [{{"path": "rel/path", "content": "..."}}]}}
Set blocked to a fork when you cannot proceed without a human answer. A fork has id, topic, question, kind, options, recommended, prunes. Leave options empty when the human should answer in their own words.
When blocked is set, leave writes empty.
In llm mode, decide design questions yourself and list those choices under assumptions.
Do not write paths outside the repository.

Mode: {mode.value}

Goal:
{goal}

Constraints:
{constraint_lines}

Files:
{hit_lines}
"""


def parse_coder_result(text: str) -> tuple[CoderResult, tuple[tuple[str, str], ...]]:
    stripped = strip_fence(text)
    if not stripped.startswith("{"):
        return CoderResult(summary=stripped), ()
    payload = load_json_text(stripped, "Coder reply")
    if not isinstance(payload, dict):
        raise ValueError("Coder reply must be an object")
    blocked = payload.get("blocked")
    fork = None if blocked in (None, "") else parse_fork(blocked)
    assumptions = payload.get("assumptions") or []
    if isinstance(assumptions, str):
        assumptions = [assumptions]
    if not isinstance(assumptions, list):
        raise ValueError("Coder assumptions must be a list")
    files_used = payload.get("files_used") or []
    if not isinstance(files_used, list):
        raise ValueError("Coder files_used must be a list")
    writes = () if fork is not None else _parse_writes(payload.get("writes"))
    return (
        CoderResult(
            summary=str(payload.get("summary") or ""),
            assumptions=tuple(str(item) for item in assumptions),
            blocked=fork,
            files_used=tuple(str(path) for path in files_used),
        ),
        writes,
    )


def apply_writes(repo: Path, writes: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    root = repo.resolve()
    written: list[str] = []
    for relative, content in writes:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError(f"Refusing to write {relative!r}")
        target = (root / path).resolve()
        if root not in target.parents:
            raise ValueError(f"Refusing to write {relative!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        written.append(path.as_posix())
    return tuple(written)


def _constraint_line(item: Constraint) -> str:
    line = f"- {item.text}"
    if item.ruled_out:
        line += " Ruled out: " + ", ".join(item.ruled_out) + "."
    return line


def _parse_writes(value: object) -> tuple[tuple[str, str], ...]:
    if not value:
        return ()
    if not isinstance(value, list):
        raise ValueError("Coder writes must be a list")
    writes: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or "path" not in item or "content" not in item:
            raise ValueError("Each write must have path and content")
        writes.append((str(item["path"]), str(item["content"])))
    return tuple(writes)
