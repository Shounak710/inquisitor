from __future__ import annotations

from controller.types import Answer, Fork, Kind, Mode

DESIGN_KINDS = {Kind.PRODUCT, Kind.ARCHITECTURE}
DESIGN_CAP = 3
PLACEMENT_CAP = 3


def should_ask(fork: Fork, mode: Mode) -> bool:
    if mode is Mode.LLM:
        return False
    if fork.settled_by:
        return False
    if not fork.prunes:
        return False
    if mode is Mode.DESIGN:
        return fork.kind in DESIGN_KINDS
    return True


def design_batch(forks: list[Fork], mode: Mode) -> list[Fork]:
    if mode is Mode.LLM:
        return []
    batch = [fork for fork in forks if fork.kind in DESIGN_KINDS and should_ask(fork, mode)]
    return batch[:DESIGN_CAP]


def implementation_batch(
    forks: list[Fork],
    mode: Mode,
    chosen: dict[str, str | None],
) -> list[Fork]:
    if mode is not Mode.DETAILED:
        return []
    batch: list[Fork] = []
    for fork in forks:
        if fork.kind is not Kind.IMPLEMENTATION or not should_ask(fork, mode):
            continue
        if fork.depends_on:
            option_id = chosen.get(fork.depends_on)
            if option_id is None or option_id != fork.requires_option:
                continue
        batch.append(fork)
    return batch[:PLACEMENT_CAP]


def chosen_options(answers: list[Answer]) -> dict[str, str | None]:
    return {answer.fork_id: answer.option_id for answer in answers}
