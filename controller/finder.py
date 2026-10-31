from __future__ import annotations

import json
from typing import Callable

from controller.types import Fork, Hit, Kind, Mode, Option, Record

# Keyword stand-in used when no model command is passed. It only emits forks
# whose answers rule out a design or a file.
_TOPICS: tuple[tuple[str, tuple[str, ...], Kind, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "deletion",
        ("delete", "deletion"),
        Kind.ARCHITECTURE,
        "How should deletion work?",
        (
            ("soft-delete", "Soft-delete. Keep the row and set deleted_at."),
            ("hard-delete", "Hard-delete. Remove the row."),
        ),
    ),
    (
        "auth",
        ("auth", "login", "session", "permission"),
        Kind.ARCHITECTURE,
        "Which auth approach should this use?",
        (
            ("session", "Session cookie, matching the existing session path."),
            ("token", "Bearer token, matching the existing token path."),
        ),
    ),
    (
        "schema",
        ("schema", "migration", "migrate"),
        Kind.ARCHITECTURE,
        "How should the data shape change?",
        (
            ("new-column", "Add a column to the existing table."),
            ("new-table", "Add a new table."),
        ),
    ),
    (
        "billing",
        ("billing", "charge", "invoice", "payment"),
        Kind.PRODUCT,
        "What should the billing behavior be?",
        (
            ("charge-now", "Charge when the action happens."),
            ("invoice-later", "Record an invoice and charge later."),
        ),
    ),
)

Complete = Callable[[str], str]


class KeywordFinder:
    def find(
        self,
        goal: str,
        hits: list[Hit],
        records: list[Record],
        mode: Mode,
    ) -> list[Fork]:
        del records, mode
        lowered = goal.lower()
        forks: list[Fork] = []
        for topic, words, kind, question, options in _TOPICS:
            if any(word in lowered for word in words):
                forks.append(
                    Fork(
                        id=topic,
                        topic=topic,
                        question=question,
                        kind=kind,
                        options=tuple(
                            Option(option_id, label, files_for_option(option_id, hits))
                            for option_id, label in options
                        ),
                        recommended=options[0][0],
                    )
                )
        paths = list(dict.fromkeys(hit.path for hit in hits))
        if 2 <= len(paths) <= 3:
            forks.append(
                Fork(
                    id="placement",
                    topic="placement",
                    question="Which existing file should this change follow?",
                    kind=Kind.IMPLEMENTATION,
                    options=tuple(Option(path, path, (path,)) for path in paths),
                    recommended=paths[0],
                )
            )
        return forks


class ModelFinder:
    def __init__(self, complete: Complete):
        self.complete = complete

    def find(
        self,
        goal: str,
        hits: list[Hit],
        records: list[Record],
        mode: Mode,
    ) -> list[Fork]:
        return parse_forks(self.complete(build_finder_prompt(goal, hits, records, mode)))


def files_for_option(option_id: str, hits: list[Hit]) -> tuple[str, ...]:
    """Attach a hit to an option when a token in the option id names that file only."""
    tokens = [part for part in option_id.lower().split("-") if len(part) >= 4]
    for token in tokens:
        matched = [
            hit.path for hit in hits if token in f"{hit.path} {hit.text}".lower()
        ]
        unique = tuple(dict.fromkeys(matched))
        if unique and len(unique) < len(hits):
            return unique
    return ()


def build_finder_prompt(goal: str, hits: list[Hit], records: list[Record], mode: Mode) -> str:
    hit_lines = "\n".join(f"- {hit.path}:{hit.line} {hit.text}" for hit in hits) or "- none"
    record_lines = "\n".join(_record_line(record) for record in records if record.status == "accepted") or "- none"
    return f"""List the forks for this coding task. Return JSON only, with the shape {{"forks": [...]}}.
Each fork has id, topic, question, kind (product, architecture, or implementation), options (id, label, files), recommended, depends_on, requires_option, prunes, settled_by, revises.
prunes is true only when the answer drops files or rules out a design.
Include options only when the choices are a small finite set. Leave options empty when the human should write the constraint in their own words.
Set settled_by to a decision id when an accepted decision already answers the fork.
Set revises to a decision id when this fork should replace that decision, and leave settled_by empty on a revision.
Mode: {mode.value}. Design mode only includes product and architecture forks. Detailed mode may also include placement forks, and those name depends_on and requires_option when they depend on a design answer.
Do not write code.

Goal:
{goal}

Search hits:
{hit_lines}

Accepted decisions:
{record_lines}
"""


def parse_forks(text: str) -> list[Fork]:
    payload = load_json_text(text, "Finder reply")
    raw_forks = payload.get("forks") if isinstance(payload, dict) else payload
    if not isinstance(raw_forks, list):
        raise ValueError("Finder reply must contain a list of forks")
    return [parse_fork(item) for item in raw_forks]


def parse_fork(item: object) -> Fork:
    if not isinstance(item, dict):
        raise ValueError("Each fork must be an object")
    if "id" not in item:
        raise ValueError("Fork is missing id")
    try:
        kind = Kind(str(item["kind"]))
    except (KeyError, ValueError) as error:
        raise ValueError(f"Fork {item.get('id')!r} has an unknown kind") from error
    raw_options = item.get("options") or []
    if not isinstance(raw_options, list):
        raise ValueError(f"Fork {item.get('id')!r} options must be a list")
    return Fork(
        id=str(item["id"]),
        topic=str(item.get("topic") or item["id"]),
        question=str(item.get("question") or ""),
        kind=kind,
        options=tuple(_parse_option(option) for option in raw_options),
        recommended=_optional_str(item.get("recommended")),
        depends_on=_optional_str(item.get("depends_on")),
        requires_option=_optional_str(item.get("requires_option")),
        prunes=bool(item.get("prunes", True)),
        settled_by=_optional_str(item.get("settled_by")),
        revises=_optional_str(item.get("revises")),
    )


def _parse_option(item: object) -> Option:
    if not isinstance(item, dict) or "id" not in item:
        raise ValueError("Each option must be an object with an id")
    files = item.get("files") or []
    if isinstance(files, str):
        files = [files]
    if not isinstance(files, list):
        raise ValueError(f"Option {item.get('id')!r} files must be a list")
    return Option(str(item["id"]), str(item.get("label") or item["id"]), tuple(str(path) for path in files))


def _record_line(record: Record) -> str:
    line = f"- {record.id} [{record.status}] {record.topic}: {record.decision}"
    if record.chosen:
        line += f" Chosen: {record.chosen}."
    if record.ruled_out:
        line += " Ruled out: " + ", ".join(record.ruled_out) + "."
    return line


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_json_text(text: str, label: str) -> object:
    stripped = strip_fence(text)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not JSON") from error


def strip_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
