import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from controller.v1.cli import main
from controller.v1.coder import ModelCoder, apply_writes, parse_coder_result
from controller.v1.finder import KeywordFinder, ModelFinder, build_finder_prompt, parse_forks
from controller.v1.types import Hit, Mode


class FinderModelTest(unittest.TestCase):
    def test_keyword_options_take_the_hit_they_name(self):
        hits = [
            Hit("src/soft.py", 1, "deleted_at"),
            Hit("src/hard.py", 1, "delete row"),
        ]
        forks = KeywordFinder().find("add account deletion", hits, [], Mode.DESIGN)
        deletion = next(fork for fork in forks if fork.id == "deletion")
        files = {option.id: option.files for option in deletion.options}
        self.assertEqual(files["soft-delete"], ("src/soft.py",))
        self.assertEqual(files["hard-delete"], ("src/hard.py",))

    def test_prompt_names_revises(self):
        prompt = build_finder_prompt("add deletion", [], [], Mode.DESIGN)
        self.assertIn("revises", prompt)
        self.assertIn("leave settled_by empty", prompt)

    def test_model_finder_parses_a_fenced_reply(self):
        reply = """```json
{"forks": [{"id": "deletion", "topic": "deletion", "question": "How?", "kind": "architecture", "revises": "D001", "options": [{"id": "soft-delete", "label": "Soft", "files": ["src/soft.py"]}]}]}
```"""

        def complete(prompt):
            self.assertIn("add deletion", prompt)
            return reply

        forks = ModelFinder(complete).find("add deletion", [], [], Mode.DESIGN)
        self.assertEqual(forks[0].revises, "D001")
        self.assertIsNone(forks[0].settled_by)
        self.assertEqual(forks[0].options[0].files, ("src/soft.py",))

    def test_parse_forks_rejects_a_bare_paragraph(self):
        with self.assertRaises(ValueError):
            parse_forks("not json")


class CoderModelTest(unittest.TestCase):
    def test_prose_is_the_summary(self):
        result, writes = parse_coder_result("Added the helper.")
        self.assertEqual(result.summary, "Added the helper.")
        self.assertIsNone(result.blocked)
        self.assertEqual(writes, ())

    def test_a_blocked_reply_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            payload = {
                "summary": "stuck",
                "blocked": {
                    "id": "deletion",
                    "topic": "deletion",
                    "question": "How?",
                    "kind": "architecture",
                },
                "writes": [{"path": "src/out.py", "content": "nope"}],
            }
            coder = ModelCoder(lambda prompt: json.dumps(payload), repo)
            result = coder.implement("add deletion", [], [], Mode.DESIGN)
            self.assertEqual(result.blocked.id, "deletion")
            self.assertFalse((repo / "src" / "out.py").exists())

    def test_writes_land_inside_the_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            payload = {
                "summary": "done",
                "writes": [{"path": "src/out.py", "content": "print(1)\n"}],
            }
            coder = ModelCoder(lambda prompt: json.dumps(payload), repo)
            result = coder.implement("add a helper", [], [], Mode.LLM)
            self.assertEqual((repo / "src" / "out.py").read_text(), "print(1)\n")
            self.assertEqual(result.files_used, ("src/out.py",))

    def test_writes_cannot_escape_the_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                apply_writes(Path(tmp), (("../outside.py", "nope"),))


class CliModelTest(unittest.TestCase):
    def test_complete_flag_runs_finder_and_coder(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            script = repo / "complete.py"
            script.write_text(
                "import json, sys\n"
                "text = sys.stdin.read()\n"
                "if 'List the forks' in text:\n"
                "    sys.stdout.write(json.dumps({'forks': []}))\n"
                "else:\n"
                "    sys.stdout.write(json.dumps({\n"
                "        'summary': 'model done',\n"
                "        'assumptions': [],\n"
                "        'writes': [{'path': 'src/out.py', 'content': 'print(1)\\n'}],\n"
                "    }))\n"
            )
            with redirect_stdout(StringIO()):
                code = main(
                    [
                        "add a helper",
                        "--mode",
                        "design",
                        "--repo",
                        str(repo),
                        "--decisions",
                        str(repo / "docs" / "decisions"),
                        "--complete",
                        f"{sys.executable} {script}",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual((repo / "src" / "out.py").read_text(), "print(1)\n")


if __name__ == "__main__":
    unittest.main()
