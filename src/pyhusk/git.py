from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path


def git_available() -> bool:
    """True when git binary is on PATH."""
    return shutil.which("git") is not None


def run_git(args: list[str], repo_root: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Invoke git inside repo_root."""
    if not git_available():
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="git not installed")
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def head_commit(repo_root: Path, short: bool = True) -> str | None:
    """Return HEAD commit hash or None."""
    args = ["rev-parse", "--short", "HEAD"] if short else ["rev-parse", "HEAD"]
    res = run_git(args, repo_root)
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


def last_commit_for_files(repo_root: Path, files: Iterable[Path]) -> tuple[str, str] | None:
    """Return (short_sha, subject) of the most recent commit touching any of the files."""
    root = repo_root.resolve()
    rel_files: list[str] = []
    for f in files:
        try:
            rel_files.append(str(f.resolve().relative_to(root)))
        except ValueError:
            continue
    if not rel_files:
        sha = head_commit(repo_root, short=True)
        return (sha, "") if sha else None

    res = run_git(["log", "-n", "1", "--format=%h%x09%s", "--", *rel_files], repo_root)
    if res.returncode != 0 or not res.stdout.strip():
        return None
    parts = res.stdout.strip().split("\t", 1)
    return (parts[0], parts[1] if len(parts) > 1 else "")


def changed_files_since(repo_root: Path, since_ref: str = "HEAD~1") -> set[Path]:
    """Return files changed between since_ref and working tree (including untracked)."""
    root = repo_root.resolve()
    changed: set[Path] = set()

    # Committed differences
    diff_res = run_git(["diff", "--name-only", since_ref], repo_root)
    if diff_res.returncode == 0 and diff_res.stdout.strip():
        for line in diff_res.stdout.splitlines():
            path = (root / line.strip()).resolve()
            changed.add(path)

    # Untracked and uncommitted working tree changes
    status_res = run_git(["status", "--porcelain", "-uall"], repo_root)
    if status_res.returncode == 0 and status_res.stdout.strip():
        for line in status_res.stdout.splitlines():
            if len(line) >= 4:
                filename = line[3:].strip()
                if " -> " in filename:
                    filename = filename.split(" -> ")[1].strip()
                changed.add((root / filename).resolve())

    return changed


def commit_history_for_files(
    repo_root: Path, files: Iterable[Path], limit: int = 10
) -> list[dict[str, str]]:
    """Return recent commits touching any of the files."""
    root = repo_root.resolve()
    rel_files: list[str] = []
    for f in files:
        try:
            rel_files.append(str(f.resolve().relative_to(root)))
        except ValueError:
            continue
    if not rel_files:
        return []

    res = run_git(
        ["log", f"-n{limit}", "--format=%h%x09%an%x09%ad%x09%s", "--date=short", "--", *rel_files],
        repo_root,
    )
    if res.returncode != 0 or not res.stdout.strip():
        return []

    entries: list[dict[str, str]] = []
    for line in res.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) >= 4:
            entries.append(
                {
                    "commit": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "message": parts[3],
                }
            )
    return entries
