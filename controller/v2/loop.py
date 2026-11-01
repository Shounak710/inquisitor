from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from controller.v1.coder import apply_writes
from controller.v1.decisions import load_records, persist_human_decision
from controller.v1.finder import load_json_text, strip_fence
from controller.v1.types import Answer, Ask, Constraint, Fork, Kind, Mode, Option, Question
from controller.v2.prompt import TOOLS, prompt_for

TURN_CAP = 8


@dataclass(frozen=True)
class V2Result:
    summary: str
    questions_asked: tuple[str, ...]
    records_written: tuple[str, ...]
    files_written: tuple[str, ...]


def run_v2(
    goal: str,
    repo: Path,
    complete,
    ask: Ask,
    decisions_dir: Path | None = None,
    mode: Mode = Mode.DESIGN,
) -> V2Result:
    decisions = decisions_dir if decisions_dir is not None else repo / "docs" / "decisions"
    system = prompt_for(mode)
    messages: list[dict] = [{"role": "user", "content": goal}]
    asked: list[str] = []
    written: list[str] = []
    summary = ""
    files: tuple[str, ...] = ()
    for _ in range(TURN_CAP):
        raw = complete(_request(system, messages))
        content, calls, writes = _parse_turn(raw)
        messages.append({"role": "assistant", "content": content, "tool_calls": calls})
        if not calls:
            summary = content
            files = apply_writes(repo, writes) if writes else ()
            break
        for call in calls:
            text, record_id = _execute(decisions, ask, call, asked, mode)
            if record_id:
                written.append(record_id)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": text})
    else:
        summary = summary or "Stopped after the tool-call cap."
    return V2Result(
        summary=summary,
        questions_asked=tuple(asked),
        records_written=tuple(written),
        files_written=files,
    )


def _request(system: str, messages: list[dict]) -> str:
    return json.dumps({"system": system, "tools": list(TOOLS), "messages": messages})


def _parse_turn(text: str) -> tuple[str, list[dict], tuple[tuple[str, str], ...]]:
    stripped = strip_fence(text)
    if not stripped.startswith("{"):
        return stripped, [], ()
    payload = load_json_text(stripped, "Model reply")
    if not isinstance(payload, dict):
        raise ValueError("Model reply must be an object")
    calls = []
    for index, raw in enumerate(payload.get("tool_calls") or []):
        if not isinstance(raw, dict) or "name" not in raw:
            raise ValueError("Each tool call needs a name")
        arguments = raw.get("arguments") or {}
        if isinstance(arguments, str):
            arguments = json.loads(arguments) if arguments.strip() else {}
        if not isinstance(arguments, dict):
            raise ValueError(f"Tool call {raw.get('name')!r} arguments must be an object")
        calls.append({"id": str(raw.get("id") or f"call-{index + 1}"), "name": str(raw["name"]), "arguments": arguments})
    writes = () if calls else _writes(payload.get("writes"))
    return str(payload.get("content") or ""), calls, writes


def _writes(value: object) -> tuple[tuple[str, str], ...]:
    if not value:
        return ()
    if not isinstance(value, list):
        raise ValueError("writes must be a list")
    writes: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or "path" not in item or "content" not in item:
            raise ValueError("Each write must have path and content")
        writes.append((str(item["path"]), str(item["content"])))
    return tuple(writes)


def _execute(
    directory: Path,
    ask: Ask,
    call: dict,
    asked: list[str],
    mode: Mode,
) -> tuple[str, str | None]:
    name = call["name"]
    arguments = call["arguments"]
    if name == "lookup_decisions":
        return json.dumps(_lookup(directory, str(arguments.get("query") or ""))), None
    if name == "ask_human":
        if mode is Mode.LLM:
            return json.dumps({"error": "This mode takes no human input. Decide this yourself."}), None
        return _ask(directory, ask, arguments, asked, mode)
    return json.dumps({"error": f"Unknown tool {name}"}), None


def _lookup(directory: Path, query: str) -> dict:
    needle = query.lower()
    decisions = []
    for record in load_records(directory):
        if record.status != "accepted":
            continue
        haystack = " ".join((record.id, record.topic, record.decision)).lower()
        if needle and needle not in haystack:
            continue
        decisions.append(
            {
                "id": record.id,
                "topic": record.topic,
                "kind": record.kind.value,
                "decision": record.decision,
                "chosen": record.chosen,
                "code": list(record.code),
                "ruled_out": list(record.ruled_out),
            }
        )
    return {"decisions": decisions}


def _ask(
    directory: Path,
    ask: Ask,
    arguments: dict,
    asked: list[str],
    mode: Mode,
) -> tuple[str, str | None]:
    question_text = str(arguments.get("question") or "").strip()
    topic = str(arguments.get("topic") or "").strip()
    if not question_text or not topic:
        return json.dumps({"error": "ask_human requires question and topic"}), None
    default = Kind.IMPLEMENTATION if mode is Mode.DETAILED else Kind.PRODUCT
    try:
        kind = Kind(str(arguments.get("kind") or default.value))
    except ValueError:
        kind = default
    if mode is Mode.DESIGN and kind not in {Kind.PRODUCT, Kind.ARCHITECTURE}:
        return json.dumps({"error": "This mode takes design-level input only."}), None
    if mode is Mode.DETAILED and kind is not Kind.IMPLEMENTATION:
        return json.dumps({"error": "This mode takes function-level input only."}), None
    options = _options(arguments.get("options"))
    recommended = arguments.get("recommended")
    recommended_id = str(recommended) if recommended and any(option.id == recommended for option in options) else None
    fork = Fork(
        id=topic,
        topic=topic,
        question=question_text,
        kind=kind,
        options=tuple(options),
        recommended=recommended_id,
    )
    answers = ask(
        [
            Question(
                fork_id=fork.id,
                prompt=fork.question,
                options=fork.options,
                recommended=fork.recommended,
            )
        ]
    )
    if not answers:
        return json.dumps({"error": "No answer returned"}), None
    answer = answers[0]
    asked.append(topic)
    constraint = _constraint(fork, answer)
    records, record_id = persist_human_decision(directory, load_records(directory), fork, constraint)
    del records
    return json.dumps({"answer": constraint.text, "record_id": record_id}), record_id


def _options(value: object) -> list[Option]:
    if not value:
        return []
    if not isinstance(value, list):
        raise ValueError("ask_human options must be a list")
    options = []
    for item in value:
        if isinstance(item, str):
            options.append(Option(item, item))
            continue
        if not isinstance(item, dict) or "id" not in item:
            raise ValueError("Each option needs an id")
        options.append(Option(str(item["id"]), str(item.get("label") or item["id"])))
    return options


def _constraint(fork: Fork, answer: Answer) -> Constraint:
    chosen = next((option for option in fork.options if option.id == answer.option_id), None)
    if chosen is not None:
        text = chosen.label if not answer.text else f"{chosen.label}. {answer.text}"
        return Constraint(
            fork_id=fork.id,
            topic=fork.topic,
            kind=fork.kind,
            text=text,
            source="human",
            files=chosen.files,
            option_id=chosen.id,
        )
    return Constraint(
        fork_id=fork.id,
        topic=fork.topic,
        kind=fork.kind,
        text=(answer.text or "").strip(),
        source="human",
    )
