import tempfile
import unittest
from pathlib import Path

from controller.loop import run_task
from controller.types import (
    Answer,
    CoderResult,
    Constraint,
    Fork,
    Hit,
    Kind,
    Mode,
    Option,
    Question,
    Record,
)


def arch(fork_id: str = "deletion") -> Fork:
    return Fork(
        id=fork_id,
        topic=fork_id,
        question=f"How should {fork_id} work?",
        kind=Kind.ARCHITECTURE,
        options=(
            Option("soft-delete", "Soft-delete.", ("src/soft.py",)),
            Option("hard-delete", "Hard-delete.", ("src/hard.py",)),
        ),
        recommended="soft-delete",
    )


class ScriptedFinder:
    def __init__(self, forks: list[Fork]):
        self.forks = forks
        self.calls = 0

    def find(self, goal, hits, records, mode):
        del goal, hits, records, mode
        self.calls += 1
        return list(self.forks)


class RecordingCoder:
    def __init__(self, blocked: Fork | None = None):
        self.blocked = blocked
        self.calls = 0
        self.constraints: list[list[Constraint]] = []
        self.hit_paths: list[list[str]] = []

    def implement(self, goal, constraints, hits, mode):
        del goal, mode
        self.calls += 1
        self.constraints.append(list(constraints))
        self.hit_paths.append([hit.path for hit in hits])
        blocked = self.blocked if self.calls == 1 else None
        return CoderResult(summary="implemented", blocked=blocked)


def answer_recommended(questions: list[Question]) -> list[Answer]:
    return [Answer(question.fork_id, option_id=question.recommended) for question in questions]


def _decision(**kwargs) -> Record:
    fields = dict(
        id="D001",
        title="Soft-delete users",
        status="accepted",
        date="2026-10-29",
        kind=Kind.ARCHITECTURE,
        topic="deletion",
        decision="Soft-delete. Keep the row and set deleted_at.",
        chosen="soft-delete",
    )
    fields.update(kwargs)
    return Record(**fields)


class RepeatingCoder:
    def __init__(self):
        self.calls = 0

    def implement(self, goal, constraints, hits, mode):
        del goal, constraints, hits, mode
        self.calls += 1
        return CoderResult(
            summary="stuck",
            blocked=Fork(
                id=f"block-{self.calls}",
                topic=f"topic-{self.calls}",
                question=f"Question {self.calls}?",
                kind=Kind.ARCHITECTURE,
                options=(Option("a", "A"),),
                recommended="a",
            ),
        )


class LoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.decisions = self.repo / "docs" / "decisions"
        self.hits = [
            Hit("src/soft.py", 1, "deleted_at"),
            Hit("src/hard.py", 1, "delete row"),
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def execute(self, mode, forks, ask=answer_recommended, coder=None):
        return run_task(
            goal="add account deletion",
            mode=mode,
            repo=self.repo,
            finder=ScriptedFinder(forks),
            coder=coder or RecordingCoder(),
            ask=ask,
            decisions_dir=self.decisions,
            retrieve_fn=lambda repo, goal: list(self.hits),
        )

    def test_design_mode_asks_once_and_records_the_answer(self):
        placement = Fork(
            id="placement",
            topic="placement",
            question="Which file?",
            kind=Kind.IMPLEMENTATION,
            options=(Option("src/soft.py", "src/soft.py", ("src/soft.py",)),),
            recommended="src/soft.py",
        )
        result = self.execute(Mode.DESIGN, [arch(), placement])
        self.assertEqual(result.questions_asked, ("deletion",))
        self.assertEqual(result.records_written, ("D001",))
        recorded = (self.decisions / "D001.md").read_text()
        self.assertIn("Soft-delete.", recorded)
        self.assertIn("src/hard.py", recorded)
        self.assertEqual(result.constraints[0].ruled_out, ("src/hard.py",))

    def test_design_answer_removes_the_other_file_from_the_coder(self):
        coder = RecordingCoder()
        self.execute(Mode.DESIGN, [arch()], coder=coder)
        self.assertEqual(coder.hit_paths[-1], ["src/soft.py"])

    def test_detailed_mode_drops_a_placement_question_the_design_answer_invalidates(self):
        placement = Fork(
            id="where-hard",
            topic="placement",
            question="Where does the hard delete go?",
            kind=Kind.IMPLEMENTATION,
            options=(Option("src/hard.py", "src/hard.py", ("src/hard.py",)),),
            recommended="src/hard.py",
            depends_on="deletion",
            requires_option="hard-delete",
        )
        result = self.execute(Mode.DETAILED, [arch(), placement])
        self.assertEqual(result.questions_asked, ("deletion",))
        self.assertEqual(list(self.decisions.glob("D*.md")), [self.decisions / "D001.md"])

    def test_detailed_mode_asks_placement_after_the_matching_design_answer(self):
        placement = Fork(
            id="where-soft",
            topic="placement",
            question="Where does the soft delete go?",
            kind=Kind.IMPLEMENTATION,
            options=(Option("src/soft.py", "src/soft.py", ("src/soft.py",)),),
            recommended="src/soft.py",
            depends_on="deletion",
            requires_option="soft-delete",
        )

        def pick_soft(questions):
            self.assertEqual([question.fork_id for question in questions], ["deletion"])
            return [Answer("deletion", option_id="soft-delete")]

        asked = []

        def ask(questions):
            asked.append([question.fork_id for question in questions])
            if questions[0].fork_id == "deletion":
                return pick_soft(questions)
            return answer_recommended(questions)

        result = self.execute(Mode.DETAILED, [arch(), placement], ask=ask)
        self.assertEqual(asked, [["deletion"], ["where-soft"]])
        self.assertEqual(result.records_written, ("D001",))

    def test_llm_mode_skips_the_finder_and_still_applies_records(self):
        self.decisions.mkdir(parents=True)
        (self.decisions / "D001.md").write_text(
            "\n".join(
                [
                    "# D001 Soft-delete users",
                    "Status: accepted",
                    "Date: 2026-10-29",
                    "Kind: architecture",
                    "Topic: deletion",
                    "",
                    "## Decision",
                    "Soft-delete. Keep the row and set deleted_at.",
                    "",
                    "## Options",
                    "- Soft-delete.",
                    "",
                ]
            )
        )
        finder = ScriptedFinder([arch()])
        coder = RecordingCoder()
        result = run_task(
            goal="add account deletion",
            mode=Mode.LLM,
            repo=self.repo,
            finder=finder,
            coder=coder,
            ask=answer_recommended,
            decisions_dir=self.decisions,
            retrieve_fn=lambda repo, goal: list(self.hits),
        )
        self.assertEqual(finder.calls, 0)
        self.assertEqual(result.questions_asked, ())
        self.assertEqual(coder.constraints[-1][0].text, "Soft-delete. Keep the row and set deleted_at.")

    def test_an_accepted_decision_suppresses_the_same_topic(self):
        record = Record(
            id="D004",
            title="Soft-delete users",
            status="accepted",
            date="2026-10-29",
            kind=Kind.ARCHITECTURE,
            topic="deletion",
            decision="Soft-delete. Keep the row and set deleted_at.",
        )
        self.decisions.mkdir(parents=True)
        from controller.decisions import render_record

        (self.decisions / "D004.md").write_text(render_record(record))
        result = self.execute(Mode.DESIGN, [arch()])
        self.assertEqual(result.questions_asked, ())
        self.assertEqual(result.constraints[0].source, "record")

    def test_coder_stop_asks_a_new_fork_above_the_mode_bar(self):
        coder = RecordingCoder(blocked=arch("billing"))
        result = self.execute(Mode.DESIGN, [], coder=coder)
        self.assertEqual(result.questions_asked, ("billing",))
        self.assertEqual(coder.calls, 2)
        self.assertEqual(result.records_written, ("D001",))
        self.assertIsNone(result.unresolved)

    def test_a_recorded_decision_drops_the_ruled_out_file(self):
        self.save(_decision(ruled_out=("src/hard.py",), code=("src/soft.py",)))
        coder = RecordingCoder()
        result = self.execute(Mode.DESIGN, [arch()], coder=coder)
        self.assertEqual(result.questions_asked, ())
        self.assertEqual(coder.hit_paths[-1], ["src/soft.py"])

    def test_detailed_mode_uses_a_recorded_choice_for_placement(self):
        self.save(_decision(chosen="soft-delete"))
        placement = Fork(
            id="where-soft",
            topic="placement",
            question="Where does the soft delete go?",
            kind=Kind.IMPLEMENTATION,
            options=(Option("src/soft.py", "src/soft.py", ("src/soft.py",)),),
            recommended="src/soft.py",
            depends_on="deletion",
            requires_option="soft-delete",
        )
        result = self.execute(Mode.DETAILED, [arch(), placement])
        self.assertEqual(result.questions_asked, ("where-soft",))

    def test_a_revision_is_asked_and_supersedes_the_record(self):
        self.save(_decision())
        revised = Fork(
            id="deletion",
            topic="deletion",
            question="How should deletion work now?",
            kind=Kind.ARCHITECTURE,
            options=(
                Option("soft-delete", "Soft-delete.", ("src/soft.py",)),
                Option("hard-delete", "Hard-delete.", ("src/hard.py",)),
            ),
            recommended="hard-delete",
            revises="D001",
        )
        result = self.execute(Mode.DESIGN, [revised])
        self.assertEqual(result.questions_asked, ("deletion",))
        self.assertEqual(result.records_written, ("D002",))
        from controller.decisions import load_records

        loaded = {record.id: record for record in load_records(self.decisions)}
        self.assertEqual(loaded["D001"].status, "superseded")
        self.assertEqual(loaded["D001"].superseded_by, "D002")
        self.assertEqual(loaded["D002"].chosen, "hard-delete")

    def test_a_coder_revision_is_asked_even_when_the_topic_is_recorded(self):
        self.save(_decision())
        blocked = Fork(
            id="deletion-2",
            topic="deletion",
            question="Switch to hard delete?",
            kind=Kind.ARCHITECTURE,
            options=(Option("hard-delete", "Hard-delete.", ("src/hard.py",)),),
            recommended="hard-delete",
            revises="D001",
            settled_by="D001",
        )
        result = self.execute(Mode.DESIGN, [], coder=RecordingCoder(blocked=blocked))
        self.assertEqual(result.questions_asked, ("deletion-2",))
        self.assertEqual(result.records_written, ("D002",))

    def test_an_open_question_records_the_human_words(self):
        fork = Fork(
            id="empty-state",
            topic="empty-state",
            question="What should the empty state say?",
            kind=Kind.PRODUCT,
        )

        def write_thoughts(questions):
            self.assertEqual(questions[0].options, ())
            return [Answer("empty-state", text="Keep it to one sentence.")]

        result = self.execute(Mode.DESIGN, [fork], ask=write_thoughts)
        self.assertEqual(result.questions_asked, ("empty-state",))
        self.assertEqual(result.records_written, ("D001",))
        self.assertIn("Keep it to one sentence.", (self.decisions / "D001.md").read_text())
        self.assertIsNone(result.constraints[0].option_id)

    def test_a_block_below_the_mode_bar_goes_back_to_the_coder(self):
        blocked = Fork(
            id="placement",
            topic="placement",
            question="Which file?",
            kind=Kind.IMPLEMENTATION,
        )
        coder = RecordingCoder(blocked=blocked)
        result = self.execute(Mode.DESIGN, [], coder=coder)
        self.assertEqual(result.questions_asked, ())
        self.assertEqual(coder.calls, 2)
        self.assertEqual(coder.constraints[1][0].text, "Decide without asking: Which file?")
        self.assertEqual(result.assumptions, ("Decide without asking: Which file?",))
        self.assertIsNone(result.unresolved)

    def test_a_block_past_the_cap_stays_unresolved(self):
        coder = RepeatingCoder()
        result = self.execute(Mode.DESIGN, [], coder=coder)
        self.assertEqual(coder.calls, 4)
        self.assertEqual(len(result.questions_asked), 3)
        self.assertEqual(result.unresolved.id, "block-4")

    def save(self, record: Record):
        from controller.decisions import render_record

        self.decisions.mkdir(parents=True, exist_ok=True)
        (self.decisions / f"{record.id}.md").write_text(render_record(record))


if __name__ == "__main__":
    unittest.main()
