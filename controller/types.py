from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol


class Mode(str, Enum):
    LLM = "llm"
    DESIGN = "design"
    DETAILED = "detailed"


class Kind(str, Enum):
    PRODUCT = "product"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class Fork:
    id: str
    topic: str
    question: str
    kind: Kind
    options: tuple[Option, ...] = ()
    recommended: str | None = None
    depends_on: str | None = None
    requires_option: str | None = None
    # True when an answer drops files from the coder prompt or rules out a design.
    prunes: bool = True
    settled_by: str | None = None
    revises: str | None = None


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class Answer:
    fork_id: str
    option_id: str | None = None
    text: str | None = None


@dataclass(frozen=True)
class Constraint:
    fork_id: str
    topic: str
    kind: Kind
    text: str
    source: str
    files: tuple[str, ...] = ()
    ruled_out: tuple[str, ...] = ()
    option_id: str | None = None


@dataclass
class Record:
    id: str
    title: str
    status: str
    date: str
    kind: Kind
    topic: str
    decision: str
    options: tuple[str, ...] = ()
    code: tuple[str, ...] = ()
    ruled_out: tuple[str, ...] = ()
    chosen: str | None = None
    superseded_by: str | None = None


@dataclass(frozen=True)
class Question:
    fork_id: str
    prompt: str
    options: tuple[Option, ...]
    recommended: str | None = None


@dataclass(frozen=True)
class CoderResult:
    summary: str
    assumptions: tuple[str, ...] = ()
    blocked: Fork | None = None
    files_used: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunResult:
    mode: Mode
    summary: str
    constraints: tuple[Constraint, ...]
    assumptions: tuple[str, ...]
    questions_asked: tuple[str, ...]
    records_written: tuple[str, ...]
    unresolved: Fork | None = None


class Finder(Protocol):
    def find(
        self,
        goal: str,
        hits: list[Hit],
        records: list[Record],
        mode: Mode,
    ) -> list[Fork]: ...


class Coder(Protocol):
    def implement(
        self,
        goal: str,
        constraints: list[Constraint],
        hits: list[Hit],
        mode: Mode,
    ) -> CoderResult: ...


Ask = Callable[[list[Question]], list[Answer]]
