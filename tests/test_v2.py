import json
import tempfile
import unittest
from pathlib import Path

from controller.v1.types import Answer, Kind, Mode, Record
from controller.v2.loop import run_v2
from controller.v2.prompt import SYSTEM_PROMPT, TOOLS, prompt_for


def answer_recommended(questions):
    return [Answer(question.fork_id, option_id=question.recommended) for question in questions]


class ScriptedModel:
    def __init__(self):
        self.requests = []

    def __call__(self, payload: str) -> str:
        request = json.loads(payload)
        self.requests.append(request)
        tools = [message for message in request["messages"] if message["role"] == "tool"]
        if not tools:
            return json.dumps(
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "1",
                            "name": "lookup_decisions",
                            "arguments": {"query": "reminder"},
                        }
                    ],
                }
            )
        body = json.loads(tools[-1]["content"])
        if "decisions" in body and not body["decisions"]:
            return json.dumps(
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "2",
                            "name": "ask_human",
                            "arguments": {
                                "question": "When should the reminder go out?",
                                "topic": "reminder-time",
                                "kind": "product",
                                "options": [
                                    {"id": "evening-before", "label": "The evening before."},
                                    {"id": "morning-of", "label": "The morning of."},
                                ],
                                "recommended": "evening-before",
                            },
                        }
                    ],
                }
            )
        return json.dumps(
            {
                "content": "Added the reminder.",
                "tool_calls": [],
                "writes": [{"path": "orders/remind.py", "content": "print(1)\n"}],
            }
        )


class V2Test(unittest.TestCase):
    def test_the_prompt_names_both_tools(self):
        names = {tool["name"] for tool in TOOLS}
        self.assertEqual(names, {"lookup_decisions", "ask_human"})
        self.assertIn("lookup_decisions", SYSTEM_PROMPT)
        self.assertIn("ask_human", SYSTEM_PROMPT)
        self.assertIn("No human input", SYSTEM_PROMPT)
        self.assertIn("Design history", SYSTEM_PROMPT)
        self.assertIn("Human input", SYSTEM_PROMPT)
        self.assertIn("design-level input only", prompt_for(Mode.DESIGN))
        self.assertIn("function-level input only", prompt_for(Mode.DETAILED))
        self.assertIn("Do not call ask_human", prompt_for(Mode.LLM))
        self.assertNotEqual(prompt_for(Mode.DESIGN), prompt_for(Mode.DETAILED))
        self.assertNotEqual(prompt_for(Mode.DESIGN), prompt_for(Mode.LLM))

    def test_empty_history_asks_the_human_and_records_the_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            model = ScriptedModel()
            result = run_v2(goal="send reminders", repo=repo, complete=model, ask=answer_recommended)
            self.assertEqual(result.questions_asked, ("reminder-time",))
            self.assertEqual(result.records_written, ("D001",))
            self.assertEqual(result.summary, "Added the reminder.")
            self.assertEqual((repo / "orders" / "remind.py").read_text(), "print(1)\n")
            record = (repo / "docs" / "decisions" / "D001.md").read_text()
            self.assertIn("The evening before.", record)
            self.assertIn("Topic: reminder-time", record)
            sent = model.requests[0]
            self.assertEqual(sent["system"], SYSTEM_PROMPT)
            self.assertEqual({tool["name"] for tool in sent["tools"]}, {"lookup_decisions", "ask_human"})

    def test_a_matching_decision_is_returned_and_the_model_can_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            decisions = repo / "docs" / "decisions"
            decisions.mkdir(parents=True)
            from controller.v1.decisions import render_record

            (decisions / "D001.md").write_text(
                render_record(
                    Record(
                        id="D001",
                        title="Remind the evening before",
                        status="accepted",
                        date="2026-10-31",
                        kind=Kind.PRODUCT,
                        topic="reminder-time",
                        decision="The evening before.",
                        chosen="evening-before",
                    )
                )
            )

            def complete(payload: str) -> str:
                request = json.loads(payload)
                tools = [message for message in request["messages"] if message["role"] == "tool"]
                if not tools:
                    return json.dumps(
                        {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "1",
                                    "name": "lookup_decisions",
                                    "arguments": {"query": "reminder"},
                                }
                            ],
                        }
                    )
                found = json.loads(tools[-1]["content"])["decisions"]
                self.assertEqual(found[0]["decision"], "The evening before.")
                return json.dumps({"content": "Used the recorded decision.", "tool_calls": []})

            result = run_v2(goal="send reminders", repo=repo, complete=complete, ask=answer_recommended)
            self.assertEqual(result.questions_asked, ())
            self.assertEqual(result.records_written, ())
            self.assertEqual(result.summary, "Used the recorded decision.")

    def test_a_task_with_no_design_decision_finishes_without_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            def complete(payload: str) -> str:
                del payload
                return json.dumps(
                    {
                        "content": "Renamed the helper.",
                        "tool_calls": [],
                        "writes": [{"path": "orders/remind.py", "content": "print(1)\n"}],
                    }
                )

            result = run_v2(goal="rename the helper", repo=repo, complete=complete, ask=answer_recommended)
            self.assertEqual(result.questions_asked, ())
            self.assertEqual(result.summary, "Renamed the helper.")
            self.assertEqual((repo / "orders" / "remind.py").read_text(), "print(1)\n")

    def test_an_empty_lookup_can_finish_when_no_human_input_is_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            steps = {"n": 0}

            def complete(payload: str) -> str:
                del payload
                steps["n"] += 1
                if steps["n"] == 1:
                    return json.dumps(
                        {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "1",
                                    "name": "lookup_decisions",
                                    "arguments": {"query": "rename"},
                                }
                            ],
                        }
                    )
                return json.dumps(
                    {
                        "content": "Renamed the helper.",
                        "tool_calls": [],
                        "writes": [{"path": "orders/remind.py", "content": "print(1)\n"}],
                    }
                )

            result = run_v2(goal="rename the helper", repo=repo, complete=complete, ask=answer_recommended)
            self.assertEqual(result.questions_asked, ())
            self.assertEqual(result.summary, "Renamed the helper.")
            self.assertEqual((repo / "orders" / "remind.py").read_text(), "print(1)\n")

    def test_each_mode_sends_its_prompt_and_limits_who_can_be_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            asked = {"n": 0}

            def ask(questions):
                asked["n"] += 1
                return [Answer(questions[0].fork_id, text="orders.send_reminder")]

            def model(kind: str):
                def complete(payload: str) -> str:
                    request = json.loads(payload)
                    tools = [message for message in request["messages"] if message["role"] == "tool"]
                    if not tools:
                        return json.dumps(
                            {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "1",
                                        "name": "ask_human",
                                        "arguments": {
                                            "question": "Which function should send it?",
                                            "topic": "reminder-function",
                                            "kind": kind,
                                        },
                                    }
                                ],
                            }
                        )
                    return json.dumps({"content": "Done.", "tool_calls": []})

                return complete

            design = run_v2(
                goal="send reminders",
                repo=repo,
                complete=model("implementation"),
                ask=ask,
                mode=Mode.DESIGN,
            )
            self.assertEqual(design.questions_asked, ())
            self.assertEqual(asked["n"], 0)

            function = run_v2(
                goal="send reminders",
                repo=repo,
                complete=model("implementation"),
                ask=ask,
                mode=Mode.DETAILED,
            )
            self.assertEqual(function.questions_asked, ("reminder-function",))
            self.assertEqual(function.records_written, ())
            self.assertEqual(asked["n"], 1)

            llm = run_v2(
                goal="send reminders",
                repo=repo,
                complete=model("product"),
                ask=ask,
                mode=Mode.LLM,
            )
            self.assertEqual(llm.questions_asked, ())
            self.assertEqual(asked["n"], 1)

            systems = {}

            def capturing(mode: Mode):
                def complete(payload: str) -> str:
                    systems[mode] = json.loads(payload)["system"]
                    return json.dumps({"content": "Done.", "tool_calls": []})

                return complete

            for mode in (Mode.DESIGN, Mode.DETAILED, Mode.LLM):
                run_v2(goal="rename the helper", repo=repo, complete=capturing(mode), ask=ask, mode=mode)
                self.assertEqual(systems[mode], prompt_for(mode))


if __name__ == "__main__":
    unittest.main()
