from __future__ import annotations

from pathlib import Path

from pyhusk.config import SKIP_DIRS

UNITS = ["B", "KB", "MB", "GB", "TB"]


def human_size(count: int) -> str:
    """Byte count as a short human string."""
    size = float(count)
    for unit in UNITS:
        if size < 1024 or unit == UNITS[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} {UNITS[-1]}"


def count_python_files(repo_root: Path) -> int:
    """Python files that belong to the repository, not to its tooling.

    A bare rglob counts the target's .venv, which turns "6 of 10 files" into
    "6 of 817" and makes the pruning look far more dramatic than it is.
    """
    total = 0
    for path in repo_root.rglob("*.py"):
        parts = path.relative_to(repo_root).parts
        if any(part in SKIP_DIRS or part.startswith(".") for part in parts):
            continue
        total += 1
    return total
