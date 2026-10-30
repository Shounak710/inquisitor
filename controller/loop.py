from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from controller.decisions import (
    constraint_from_record,
    load_records,
    persist_human_decision,
    relevant_records,
    settle_from_records,
)
from controller.policy import chosen_options, design_batch, implementation_batch, should_ask
from controller.retrieve import retrieve
from controller.types import (
    Answer,
    Ask,
    Coder,
    Constraint,
    Finder,
    Fork,
    Hit,
    Mode,
    Question,
    Record,
    RunResult,
)

BLOCK_CAP = 3


def run_task(
    goal: str,
    mode: Mode,
    repo: Path,
    finder: Finder,
    coder: Coder,
    ask: Ask,
    decisions_dir: Path | None = None,
    retrieve_fn: Callable[[Path, str], list[Hit]] = retrieve,
) -> RunResult:
    decisions = decisions_dir if decisions_dir is not None else repo / "docs" / "decisions"
    records = load_records(decisions)
    hits = retrieve_fn(repo, goal)
    constraints = [constraint_from_record(record) for record in relevant_records(records, goal, hits)]
    asked: list[str] = []
    written: list[str] = []

    if mode is not Mode.LLM:
        forks = settle_from_records(finder.find(goal, hits, records, mode), records)
        answers = _ask_all(ask, design_batch(forks, mode))
        asked.extend(answer.fork_id for answer in answers)
        constraints, records, new_ids = _bind(decisions, records, forks, answers, constraints)
        written.extend(new_ids)
        if mode is Mode.DETAILED:
            placement = implementation_batch(forks, mode, _choices(forks, answers, records))
            placement_answers = _ask_all(ask, placement)
            asked.extend(answer.fork_id for answer in placement_answers)
            constraints, records, new_ids = _bind(
                decisions, records, forks, placement_answers, constraints
            )
            written.extend(new_ids)

    hits = _prune(hits, constraints)
    assumptions: tuple[str, ...] = ()
    summary = ""
    seen: set[str] = set()
    notes: list[str] = []
    unresolved: Fork | None = None
    for round_index in range(BLOCK_CAP + 1):
        result = coder.implement(goal, constraints, hits, mode)
        summary = result.summary
        assumptions = result.assumptions
        blocked = result.blocked
        if blocked is None:
            unresolved = None
            break
        if blocked.id in seen or round_index >= BLOCK_CAP:
            unresolved = blocked
            break
        seen.add(blocked.id)
        if _open_to_ask(blocked, constraints, mode):
            answers = _ask_all(ask, [blocked])
            asked.extend(answer.fork_id for answer in answers)
            constraints, records, new_ids = _bind(decisions, records, [blocked], answers, constraints)
            written.extend(new_ids)
            hits = _prune(hits, constraints)
            continue
        note = f"Decide without asking: {blocked.question}"
        notes.append(note)
        constraints = [
            *constraints,
            Constraint(
                fork_id=blocked.id,
                topic=blocked.topic,
                kind=blocked.kind,
                text=note,
                source="controller",
            ),
        ]

    return RunResult(
        mode=mode,
        summary=summary,
        constraints=tuple(constraints),
        assumptions=tuple(notes) + assumptions,
        questions_asked=tuple(asked),
        records_written=tuple(written),
        unresolved=unresolved,
    )


def _choices(
    forks: list[Fork],
    answers: list[Answer],
    records: list[Record],
) -> dict[str, str | None]:
    chosen = chosen_options(answers)
    by_id = {record.id: record for record in records if record.status == "accepted"}
    for fork in forks:
        if fork.id in chosen or not fork.settled_by:
            continue
        record = by_id.get(fork.settled_by)
        if record is not None and record.chosen:
            chosen[fork.id] = record.chosen
    return chosen


def _open_to_ask(fork: Fork, constraints: list[Constraint], mode: Mode) -> bool:
    if fork.revises:
        fork = replace(fork, settled_by=None)
    elif any(item.topic == fork.topic and item.source in {"record", "human"} for item in constraints):
        return False
    return should_ask(fork, mode)


def _ask_all(ask: Ask, forks: list[Fork]) -> list[Answer]:
    if not forks:
        return []
    questions = [
        Question(
            fork_id=fork.id,
            prompt=fork.question,
            options=fork.options,
            recommended=fork.recommended,
        )
        for fork in forks
    ]
    answers = ask(questions)
    by_id = {answer.fork_id: answer for answer in answers}
    missing = [fork.id for fork in forks if fork.id not in by_id]
    if missing:
        raise ValueError(f"Missing answers for {', '.join(missing)}")
    return [by_id[fork.id] for fork in forks]


def _bind(directory, records, forks, answers, constraints):
    by_id = {fork.id: fork for fork in forks}
    written: list[str] = []
    updated = list(constraints)
    for answer in answers:
        fork = by_id[answer.fork_id]
        constraint = _constraint_from_answer(fork, answer)
        updated = [item for item in updated if item.topic != constraint.topic]
        updated.append(constraint)
        records, record_id = persist_human_decision(directory, records, fork, constraint)
        if record_id:
            written.append(record_id)
    return updated, records, written


def _constraint_from_answer(fork: Fork, answer: Answer) -> Constraint:
    chosen = next((option for option in fork.options if option.id == answer.option_id), None)
    if chosen is not None:
        text = chosen.label if not answer.text else f"{chosen.label}. {answer.text}"
        ruled_out = tuple(
            path
            for option in fork.options
            if option.id != chosen.id
            for path in option.files
        )
        return Constraint(
            fork_id=fork.id,
            topic=fork.topic,
            kind=fork.kind,
            text=text,
            source="human",
            files=chosen.files,
            ruled_out=ruled_out,
            option_id=chosen.id,
        )
    return Constraint(
        fork_id=fork.id,
        topic=fork.topic,
        kind=fork.kind,
        text=(answer.text or "").strip(),
        source="human",
        option_id=None,
    )


def _prune(hits: list[Hit], constraints: list[Constraint]) -> list[Hit]:
    ruled_out = {path for constraint in constraints for path in constraint.ruled_out}
    return [hit for hit in hits if hit.path not in ruled_out]
