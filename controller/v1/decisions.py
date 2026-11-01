from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from pathlib import Path

from controller.v1.types import Constraint, Fork, Hit, Kind, Record

_HEADING = re.compile(r"^# (D\d+)\s+(.+)$")
_FIELD = re.compile(r"^([A-Za-z-]+):\s*(.*)$")


def load_records(directory: Path) -> list[Record]:
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("D*.md")):
        records.append(parse_record(path.read_text()))
    return records


def relevant_records(records: list[Record], goal: str, hits: list[Hit]) -> list[Record]:
    goal_text = goal.lower()
    hit_paths = {hit.path for hit in hits}
    relevant = []
    for record in records:
        if record.status != "accepted":
            continue
        topic = record.topic.lower()
        if topic and topic in goal_text:
            relevant.append(record)
            continue
        if any(path in hit_paths or path in goal for path in record.code):
            relevant.append(record)
    return relevant


def settle_from_records(forks: list[Fork], records: list[Record]) -> list[Fork]:
    accepted = {record.topic: record for record in records if record.status == "accepted"}
    settled = []
    for fork in forks:
        # A revision has to stay askable. settled_by would suppress the question.
        if fork.revises:
            settled.append(replace(fork, settled_by=None))
            continue
        record = accepted.get(fork.topic)
        if record is None:
            settled.append(fork)
            continue
        settled.append(replace(fork, settled_by=record.id))
    return settled


def constraint_from_record(record: Record) -> Constraint:
    return Constraint(
        fork_id=record.id,
        topic=record.topic,
        kind=record.kind,
        text=record.decision,
        source="record",
        files=record.code,
        ruled_out=record.ruled_out,
        option_id=record.chosen,
    )


def persist_human_decision(
    directory: Path,
    records: list[Record],
    fork: Fork,
    constraint: Constraint,
    today: date | None = None,
) -> tuple[list[Record], str | None]:
    if constraint.source != "human" or fork.kind not in {Kind.PRODUCT, Kind.ARCHITECTURE}:
        return records, None
    if not constraint.text.strip():
        return records, None

    directory.mkdir(parents=True, exist_ok=True)
    new_id = _next_id(records)
    for existing in records:
        same_topic = existing.status == "accepted" and existing.topic == fork.topic
        revises = fork.revises == existing.id and existing.status == "accepted"
        if same_topic or revises:
            existing.status = "superseded"
            existing.superseded_by = new_id
            _write_record(directory, existing)

    record = Record(
        id=new_id,
        title=_title(constraint.text),
        status="accepted",
        date=(today or date.today()).isoformat(),
        kind=fork.kind,
        topic=fork.topic,
        decision=constraint.text,
        options=tuple(option.label for option in fork.options),
        code=constraint.files,
        ruled_out=constraint.ruled_out,
        chosen=constraint.option_id,
    )
    _write_record(directory, record)
    records.append(record)
    _write_index(directory, records)
    return records, new_id


def parse_record(text: str) -> Record:
    lines = text.splitlines()
    if not lines:
        raise ValueError("Decision record is empty")
    heading = _HEADING.match(lines[0].strip())
    if heading is None:
        raise ValueError(f"Decision record must start with '# D000 title', got {lines[0]!r}")

    fields: dict[str, str] = {}
    section: str | None = None
    decision: list[str] = []
    options: list[str] = []
    code: list[str] = []
    ruled_out: list[str] = []
    for line in lines[1:]:
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if section is None:
            field = _FIELD.match(line.strip())
            if field:
                fields[field.group(1).lower()] = field.group(2).strip()
            continue
        if section == "decision":
            decision.append(line)
        elif section == "options" and line.startswith("- "):
            options.append(line[2:].strip())
        elif section == "code" and line.startswith("- "):
            code.append(line[2:].strip())
        elif section == "ruled out" and line.startswith("- "):
            ruled_out.append(line[2:].strip())

    kind_text = fields.get("kind", "")
    try:
        kind = Kind(kind_text)
    except ValueError as error:
        raise ValueError(f"Unknown decision kind {kind_text!r}") from error

    return Record(
        id=heading.group(1),
        title=heading.group(2).strip(),
        status=fields.get("status", "accepted"),
        date=fields.get("date", ""),
        kind=kind,
        topic=fields.get("topic", ""),
        decision="\n".join(decision).strip(),
        options=tuple(options),
        code=tuple(code),
        ruled_out=tuple(ruled_out),
        chosen=fields.get("chosen") or None,
        superseded_by=fields.get("superseded-by") or None,
    )


def render_record(record: Record) -> str:
    lines = [
        f"# {record.id} {record.title}",
        f"Status: {record.status}",
        f"Date: {record.date}",
        f"Kind: {record.kind.value}",
        f"Topic: {record.topic}",
    ]
    if record.chosen:
        lines.append(f"Chosen: {record.chosen}")
    if record.superseded_by:
        lines.append(f"Superseded-by: {record.superseded_by}")
    lines.extend(["", "## Decision", record.decision, "", "## Options"])
    lines.extend(f"- {option}" for option in record.options)
    if record.code:
        lines.extend(["", "## Code"])
        lines.extend(f"- {path}" for path in record.code)
    if record.ruled_out:
        lines.extend(["", "## Ruled out"])
        lines.extend(f"- {path}" for path in record.ruled_out)
    lines.append("")
    return "\n".join(lines)


def _write_record(directory: Path, record: Record) -> None:
    (directory / f"{record.id}.md").write_text(render_record(record))


def _write_index(directory: Path, records: list[Record]) -> None:
    lines = ["# Decisions", ""]
    for record in records:
        lines.append(
            f"- [{record.id} {record.title}]({record.id}.md) — {record.status} — {record.kind.value}"
        )
    lines.append("")
    (directory / "index.md").write_text("\n".join(lines))


def _next_id(records: list[Record]) -> str:
    numbers = [int(record.id[1:]) for record in records if re.fullmatch(r"D\d+", record.id)]
    return f"D{max(numbers, default=0) + 1:03d}"


def _title(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= 72:
        return one_line
    return one_line[:69] + "..."
