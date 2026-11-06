from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pyhusk.config import SKIP_DIRS, PyhuskConfig
from pyhusk.git import changed_files_since
from pyhusk.graph import build_slice
from pyhusk.pipeline import Resolution


def find_test_files(repo_root: Path) -> list[Path]:
    """Find all test files in the repository."""
    root = repo_root.resolve()
    test_files: list[Path] = []
    for candidate in sorted(root.rglob("*.py")):
        parts = candidate.relative_to(root).parts
        if any(p in SKIP_DIRS or p.startswith(".") for p in parts):
            continue
        if candidate.name.startswith("test_") or candidate.name.endswith("_test.py"):
            test_files.append(candidate)
    return test_files


def affected_services(
    repo_root: Path,
    resolutions: dict[str, Resolution],
    changed_files: Iterable[Path],
) -> list[str]:
    """Return names of services whose slice intersects changed_files."""
    changed = {f.resolve() for f in changed_files}
    root = repo_root.resolve()

    # Global config or lock change affects everything
    global_triggers = {
        (root / "pyhusk.yaml").resolve(),
        (root / "pyproject.toml").resolve(),
    }
    if changed.intersection(global_triggers):
        return sorted(resolutions.keys())

    affected: list[str] = []
    for name, res in sorted(resolutions.items()):
        service_files = {f.resolve() for f in res.files}
        if service_files.intersection(changed):
            affected.append(name)
    return affected


def affected_tests(
    repo_root: Path,
    changed_files: Iterable[Path],
) -> list[Path]:
    """Return test files whose local import slice intersects changed_files."""
    changed = {f.resolve() for f in changed_files}
    if not changed:
        return []

    root = repo_root.resolve()
    test_files = find_test_files(repo_root)
    affected: list[Path] = []

    for test_file in test_files:
        if test_file.resolve() in changed:
            affected.append(test_file)
            continue
        # Check imports of test file
        sliced = build_slice(repo_root, [test_file])
        sliced_files = {f.resolve() for f in sliced.files}
        if sliced_files.intersection(changed):
            affected.append(test_file)

    return sorted(affected)
