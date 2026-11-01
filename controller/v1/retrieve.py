from __future__ import annotations

import re
from pathlib import Path

from controller.v1.types import Hit

STOP = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "add",
    "make",
    "into",
    "from",
    "should",
    "how",
    "can",
    "its",
    "our",
}
# Source files the search will open. Config and docs stay out so package.json
# and README files do not crowd out the code.
CODE_SUFFIXES = {
    ".py", ".pyi",
    ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx", ".mts", ".cts",
    ".go", ".rs", ".zig",
    ".java", ".kt", ".kts", ".scala", ".groovy", ".clj", ".cljs", ".cljc",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx",
    ".cs", ".fs", ".fsx", ".vb",
    ".swift", ".m", ".mm", ".dart",
    ".rb", ".php", ".pl", ".pm", ".lua", ".r",
    ".sql",
    ".sh", ".bash", ".ps1",
    ".hs", ".ex", ".exs", ".erl", ".ml", ".mli",
    ".pas", ".f", ".f90", ".cob", ".cbl", ".adb", ".ads", ".asm", ".s",
    ".vue", ".svelte", ".html", ".htm", ".css", ".scss", ".less",
}
SKIP_DIRS = {".git", "docs", "__pycache__", ".venv", "node_modules", "venv"}


def keywords(goal: str) -> list[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", goal)
    return [word for word in words if word.lower() not in STOP][:6]


def retrieve(repo: Path, goal: str, limit: int = 8) -> list[Hit]:
    words = keywords(goal)
    if not words or not repo.is_dir():
        return []
    hits: list[Hit] = []
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in CODE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            lines = path.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        relative = str(path.relative_to(repo))
        for number, line in enumerate(lines, 1):
            lowered = line.lower()
            if any(word.lower() in lowered for word in words):
                hits.append(Hit(relative, number, line.strip()[:200]))
                break
        if len(hits) >= limit:
            break
    return hits
