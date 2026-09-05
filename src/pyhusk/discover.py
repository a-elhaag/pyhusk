from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pyhusk.config import ServiceConfig
from pyhusk.errors import PyhuskError

PROBE_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class RouteInfo:
    path: str
    methods: list[str]
    documented: bool = False


@dataclass(frozen=True)
class ProbeResult:
    files: list[Path]
    routes: list[RouteInfo]
    openapi_url: str | None


def venv_python(repo_root: Path) -> Path:
    """Path to the target repository's interpreter, per platform."""
    if sys.platform == "win32":
        return repo_root / ".venv" / "Scripts" / "python.exe"
    return repo_root / ".venv" / "bin" / "python"


def probe(repo_root: Path, service: ServiceConfig) -> ProbeResult:
    """Import the service's app in a subprocess and report what it reaches.

    Out-of-process for two reasons: the target repo's imports never touch
    pyhusk's own interpreter, and an import-time crash becomes a readable error
    instead of taking pyhusk down with it.
    """
    python = venv_python(repo_root)
    if not python.exists():
        raise PyhuskError(
            f"No interpreter at {python}. pyhusk runs the probe inside the target "
            f"repository's virtualenv. Create it with `uv sync` in {repo_root}."
        )

    probe_script = Path(__file__).with_name("_probe.py")
    entry = service.entry.resolve().relative_to(repo_root.resolve())
    argv = [str(python), str(probe_script), "--entry", str(entry), "--app", service.app]
    if service.factory:
        argv.append("--factory")

    try:
        completed = subprocess.run(
            argv,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PyhuskError(
            f"Probing {entry} timed out after {PROBE_TIMEOUT_SECONDS}s. Importing the "
            f"entry module should not block; check for work at module scope."
        ) from exc

    if completed.returncode != 0:
        raise PyhuskError(
            f"Probing {entry} failed:\n{completed.stderr.strip() or '(no stderr)'}"
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PyhuskError(
            f"Probing {entry} produced unparseable output. Something printed to stdout "
            f"during import, which corrupts the probe result.\n"
            f"stdout was:\n{completed.stdout[:2000]}"
        ) from exc

    root = repo_root.resolve()
    venv_dir = (repo_root / ".venv").resolve()
    local: list[Path] = []
    for raw in payload["files"]:
        candidate = Path(raw)
        if candidate.is_relative_to(venv_dir):
            continue  # third-party; the dependency stage covers it
        if not candidate.is_relative_to(root):
            continue  # stdlib or an editable install outside the tree
        local.append(candidate)

    return ProbeResult(
        files=sorted(set(local)),
        routes=[
            RouteInfo(
                path=route["path"],
                methods=list(route["methods"]),
                documented=bool(route.get("documented", False)),
            )
            for route in payload["routes"]
        ],
        openapi_url=payload["openapi_url"],
    )
