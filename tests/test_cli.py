import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from controller.v1.cli import cli_ask
from controller.v1.types import Option, Question


class CliAskTest(unittest.TestCase):
    def test_a_finite_question_shows_its_options(self):
        question = Question(
            fork_id="deletion",
            prompt="How should deletion work?",
            options=(
                Option("soft-delete", "Soft-delete."),
                Option("hard-delete", "Hard-delete."),
            ),
            recommended="soft-delete",
        )
        with patch("builtins.input", return_value="2"):
            with redirect_stdout(StringIO()) as out:
                answers = cli_ask([question])
        text = out.getvalue()
        self.assertIn("1. Soft-delete. (recommended)", text)
        self.assertIn("2. Hard-delete.", text)
        self.assertIn("or your own answer", text)
        self.assertEqual(answers[0].option_id, "hard-delete")

    def test_an_open_question_asks_for_words(self):
        question = Question(
            fork_id="empty-state",
            prompt="What should the empty state say?",
            options=(),
        )
        with patch("builtins.input", return_value="Keep it to one sentence."):
            with redirect_stdout(StringIO()) as out:
                answers = cli_ask([question])
        text = out.getvalue()
        self.assertIn("What should the empty state say?", text)
        self.assertIn("Type your answer.", text)
        self.assertNotIn("(recommended)", text)
        self.assertNotIn("option number", text)
        self.assertEqual(answers[0].text, "Keep it to one sentence.")
        self.assertIsNone(answers[0].option_id)


if __name__ == "__main__":
    unittest.main()
