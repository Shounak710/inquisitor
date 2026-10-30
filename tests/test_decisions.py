import tempfile
import unittest
from datetime import date
from pathlib import Path

from controller.decisions import (
    load_records,
    parse_record,
    persist_human_decision,
    render_record,
    settle_from_records,
)
from controller.types import Constraint, Fork, Kind, Option


class DecisionTest(unittest.TestCase):
    def test_round_trip(self):
        from controller.types import Record

        record = Record(
            id="D001",
            title="Soft-delete users",
            status="accepted",
            date="2026-10-29",
            kind=Kind.ARCHITECTURE,
            topic="deletion",
            decision="Soft-delete. Keep the row and set deleted_at.",
            options=("Soft-delete.", "Hard-delete."),
            code=("src/users/delete.py",),
            ruled_out=("src/users/remove.py",),
            chosen="soft-delete",
        )
        parsed = parse_record(render_record(record))
        self.assertEqual(parsed.id, "D001")
        self.assertEqual(parsed.decision, record.decision)
        self.assertEqual(parsed.chosen, "soft-delete")
        self.assertEqual(parsed.code, ("src/users/delete.py",))
        self.assertEqual(parsed.ruled_out, ("src/users/remove.py",))

    def test_a_later_answer_supersedes_the_same_topic(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            fork = Fork(
                id="deletion",
                topic="deletion",
                question="How should deletion work?",
                kind=Kind.ARCHITECTURE,
                options=(
                    Option("soft-delete", "Soft-delete."),
                    Option("hard-delete", "Hard-delete."),
                ),
            )
            records, first = persist_human_decision(
                directory,
                [],
                fork,
                Constraint(
                    fork_id="deletion",
                    topic="deletion",
                    kind=Kind.ARCHITECTURE,
                    text="Soft-delete.",
                    source="human",
                    option_id="soft-delete",
                ),
                today=date(2026, 10, 29),
            )
            records, second = persist_human_decision(
                directory,
                records,
                fork,
                Constraint(
                    fork_id="deletion",
                    topic="deletion",
                    kind=Kind.ARCHITECTURE,
                    text="Hard-delete.",
                    source="human",
                    option_id="hard-delete",
                    ruled_out=("src/soft.py",),
                ),
                today=date(2026, 10, 29),
            )
            loaded = {record.id: record for record in load_records(directory)}
            self.assertEqual(first, "D001")
            self.assertEqual(second, "D002")
            self.assertEqual(loaded["D001"].status, "superseded")
            self.assertEqual(loaded["D001"].superseded_by, "D002")
            self.assertEqual(loaded["D002"].decision, "Hard-delete.")
            self.assertEqual(loaded["D002"].ruled_out, ("src/soft.py",))
            self.assertIn("D002", (directory / "index.md").read_text())

    def test_a_revision_stays_open_when_the_topic_is_already_accepted(self):
        from controller.types import Record

        record = Record(
            id="D001",
            title="Soft-delete users",
            status="accepted",
            date="2026-10-29",
            kind=Kind.ARCHITECTURE,
            topic="deletion",
            decision="Soft-delete.",
        )
        fork = Fork(
            id="deletion",
            topic="deletion",
            question="How should deletion work now?",
            kind=Kind.ARCHITECTURE,
            revises="D001",
            settled_by="D001",
        )
        settled = settle_from_records([fork], [record])
        self.assertIsNone(settled[0].settled_by)
        self.assertEqual(settled[0].revises, "D001")

    def test_placement_answers_are_not_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            fork = Fork(
                id="placement",
                topic="placement",
                question="Which file?",
                kind=Kind.IMPLEMENTATION,
            )
            records, written = persist_human_decision(
                directory,
                [],
                fork,
                Constraint(
                    fork_id="placement",
                    topic="placement",
                    kind=Kind.IMPLEMENTATION,
                    text="src/a.py",
                    source="human",
                ),
            )
            self.assertEqual(records, [])
            self.assertIsNone(written)
            self.assertEqual(list(directory.glob("D*.md")), [])


if __name__ == "__main__":
    unittest.main()
