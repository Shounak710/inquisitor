from __future__ import annotations

from controller.v1.types import Mode

_CLOSING = """
Leave ask_human options empty when the human should answer in their own words. Include options only when the choices are a small finite set.

On your final reply, set content to a short summary and writes to the files you changed. Each write is a path and the full file content, inside the repository.
"""

_DESIGN = """You implement the coding task in the user message. You decide which of these applies. This mode takes design-level input only.

No human input. The task has no product or architecture decision. Which function to edit, where it lives, and how a function is structured are yours. Implement it. Do not call ask_human for a function-level choice.

Design history. A significant decision is a product behavior or an architecture choice that may already be recorded. Call lookup_decisions. If an accepted decision covers it, follow that decision and do not ask.

Human input. A product or architecture decision is needed and lookup_decisions returned nothing that covers it. Call ask_human with kind product or architecture and use that response. Do not invent that decision yourself.
"""

_FUNCTION = """You implement the coding task in the user message. You decide which of these applies. This mode takes function-level input only.

No human input. Writing a function does not need a person. Implement it. Do not call ask_human.

Design history. If a product or architecture decision is already recorded, call lookup_decisions and follow it. Do not ask a design-level question. Decide an unsettled product or architecture choice yourself.

Function-level input. You need a person to decide which function to change, where that function lives, or how that function should behave, and lookup_decisions returned nothing that covers it. Call ask_human with kind implementation and use that response. Do not invent that function-level choice yourself.
"""

_NO_INPUT = """You implement the coding task in the user message. This mode takes no human input.

No human input. Do not call ask_human. Decide product, architecture, and function choices yourself.

Design history. You may call lookup_decisions. If an accepted decision covers a choice, follow it.
"""


def prompt_for(mode: Mode) -> str:
    if mode is Mode.LLM:
        body = _NO_INPUT
    elif mode is Mode.DETAILED:
        body = _FUNCTION
    else:
        body = _DESIGN
    return body + _CLOSING


SYSTEM_PROMPT = prompt_for(Mode.DESIGN)

TOOLS = (
    {
        "name": "lookup_decisions",
        "description": (
            "Read accepted design decisions when a choice may already be recorded. "
            "An empty decisions list means nothing matches."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Topic or words to match against accepted decisions.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "ask_human",
        "description": (
            "Ask the human for a decision this mode allows, after lookup_decisions "
            "returned nothing that covers it. Use their response."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "topic": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["product", "architecture", "implementation"],
                },
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                        },
                        "required": ["id", "label"],
                    },
                },
                "recommended": {"type": "string"},
            },
            "required": ["question", "topic"],
        },
    },
)
