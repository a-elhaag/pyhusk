from __future__ import annotations

import json
import re
import subprocess
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pyhusk.discover import venv_python
from pyhusk.errors import PyhuskError

# Application code never imports its ASGI server; the server imports the app. A
# purely import-derived requirements file therefore omits the one package the
# generated CMD needs, and every image fails to start.
SERVER_DISTRIBUTION = "uvicorn"

_NORMALIZE = re.compile(r"[-_.]+")


def normalize(name: str) -> str:
    """PEP 503 name normalization, so pydantic_core and pydantic-core match."""
    return _NORMALIZE.sub("-", name).lower()


@dataclass(frozen=True)
class RequirementsResult:
    text: str
    pins: list[str]
    unmapped: list[str]


def _packages_distributions(repo_root: Path) -> dict[str, list[str]]:
    """Map import name to distribution names, read from the target's own venv.

    Run inside the target interpreter rather than pyhusk's, because the answer
    depends on what is actually installed there.
    """
    python = venv_python(repo_root)
    if not python.exists():
        raise PyhuskError(
            f"No interpreter at {python}. Dependency mapping reads the target "
            f"repository's installed packages. Create it with `uv sync`."
        )
    script = (
        "import importlib.metadata, json, sys;"
        "json.dump(importlib.metadata.packages_distributions(), sys.stdout)"
    )
    completed = subprocess.run(
        [str(python), "-c", script], capture_output=True, text=True, timeout=60
    )
    if completed.returncode != 0:
        raise PyhuskError(f"Could not read installed packages:\n{completed.stderr.strip()}")
    return json.loads(completed.stdout)


def _load_lock(repo_root: Path) -> dict[str, tuple[str, list[str]]]:
    """Parse uv.lock into {normalized name: (version, [normalized dep names])}."""
    lock_path = repo_root / "uv.lock"
    if not lock_path.exists():
        raise PyhuskError(
            f"No uv.lock at {lock_path}. pyhusk pins dependencies from the lock file; "
            f"run `uv lock` in the target repository."
        )
    try:
        data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise PyhuskError(f"{lock_path} is not valid TOML: {exc}") from exc

    packages: dict[str, tuple[str, list[str]]] = {}
    for package in data.get("package", []):
        name = package.get("name")
        version = package.get("version")
        if not name or not version:
            continue
        dependencies = [
            normalize(dep["name"])
            for dep in package.get("dependencies", [])
            if isinstance(dep, dict) and "name" in dep
        ]
        packages[normalize(name)] = (version, dependencies)
    return packages


def resolve_requirements(repo_root: Path, third_party: Iterable[str]) -> RequirementsResult:
    """Turn third-party import names into a pinned, transitively closed requirements file."""
    mapping = {normalize(k): v for k, v in _packages_distributions(repo_root).items()}
    lock = _load_lock(repo_root)

    roots: set[str] = set()
    unmapped: list[str] = []
    for import_name in sorted(set(third_party)):
        distributions = mapping.get(normalize(import_name))
        if not distributions:
            unmapped.append(import_name)
            continue
        roots.update(normalize(dist) for dist in distributions)

    server = normalize(SERVER_DISTRIBUTION)
    if server in lock:
        roots.add(server)
    else:
        unmapped.append(
            f"{SERVER_DISTRIBUTION} (needed to run the app, but absent from uv.lock)"
        )

    # Transitive closure over the lock graph.
    resolved: set[str] = set()
    queue = sorted(roots)
    while queue:
        name = queue.pop()
        if name in resolved or name not in lock:
            continue
        resolved.add(name)
        queue.extend(lock[name][1])

    pins = sorted(f"{name}=={lock[name][0]}" for name in resolved)
    return RequirementsResult(
        text="".join(f"{pin}\n" for pin in pins),
        pins=pins,
        unmapped=unmapped,
    )


def all_requirements(repo_root: Path) -> RequirementsResult:
    """Every package in uv.lock, pinned. The baseline a naive Dockerfile installs."""
    lock = _load_lock(repo_root)
    pins = sorted(f"{name}=={version}" for name, (version, _) in lock.items())
    return RequirementsResult(
        text="".join(f"{pin}\n" for pin in pins), pins=pins, unmapped=[]
    )
