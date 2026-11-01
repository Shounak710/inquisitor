import tempfile
import unittest
from pathlib import Path

from controller.v1.retrieve import CODE_SUFFIXES, retrieve


class RetrieveTest(unittest.TestCase):
    def test_major_languages_are_searched_and_config_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            for suffix in CODE_SUFFIXES:
                path = repo / "src" / f"sample{suffix}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("invoice total\n")
            (repo / "package.json").write_text('{"name": "invoice"}\n')
            (repo / "README.md").write_text("invoice notes\n")

            hits = retrieve(repo, "invoice", limit=len(CODE_SUFFIXES) + 5)
            found = {Path(hit.path).suffix.lower() for hit in hits}

            self.assertEqual(found, CODE_SUFFIXES)
            self.assertFalse(any(hit.path.endswith((".json", ".md")) for hit in hits))


if __name__ == "__main__":
    unittest.main()
