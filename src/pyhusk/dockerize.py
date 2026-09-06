from __future__ import annotations

import json
import shutil
from collections.abc import Iterable
from pathlib import Path

from pyhusk.config import ServiceConfig

BUILD_DIR = ".build"
OVERRIDE_NAME = "Dockerfile.override"

# Keeps the build recipe itself out of the image layer.
DOCKERIGNORE = "Dockerfile\n.dockerignore\n"


def override_for(service: ServiceConfig) -> Path | None:
    """A Dockerfile.override sitting next to the entry file, if the user wrote one."""
    candidate = service.entry.parent / OVERRIDE_NAME
    return candidate if candidate.is_file() else None


def _cmd(repo_root: Path, service: ServiceConfig) -> str:
    """Exec-form CMD running uvicorn against the service's app."""
    target = f"{service.module_path(repo_root)}:{service.app}"
    argv = ["uvicorn", target]
    if service.factory:
        argv.append("--factory")
    argv += ["--host", "0.0.0.0", "--port", str(service.port)]
    return f"CMD {json.dumps(argv)}"


def render_dockerfile(
    repo_root: Path,
    service: ServiceConfig,
    from_image: str,
    install_requirements: bool,
) -> str:
    """Generate a service Dockerfile.

    With install_requirements=False the image starts from a shared base that
    already has the dependencies, so the install step is dropped.
    """
    lines = [f"FROM {from_image}", "WORKDIR /app"]
    if install_requirements:
        lines += [
            "COPY requirements.txt .",
            "RUN pip install --no-cache-dir -r requirements.txt",
        ]
    lines += [
        "COPY . .",
        f"EXPOSE {service.port}",
        _cmd(repo_root, service),
    ]
    return "\n".join(lines) + "\n"


def render_base_dockerfile(base_image: str) -> str:
    """Generate a shared base image: interpreter plus installed dependencies."""
    return (
        f"FROM {base_image}\n"
        "WORKDIR /app\n"
        "COPY requirements.txt .\n"
        "RUN pip install --no-cache-dir -r requirements.txt\n"
    )


def assemble_context(
    repo_root: Path,
    name: str,
    service: ServiceConfig,
    files: Iterable[Path],
    requirements_text: str,
    dockerfile_text: str,
) -> Path:
    """Write .build/<name>/ containing the slice, requirements and Dockerfile.

    The directory is removed first. Leaving stale files behind would silently
    reintroduce code that is no longer in the slice, which is the exact failure
    the tool exists to prevent.
    """
    context = repo_root / BUILD_DIR / name
    if context.exists():
        shutil.rmtree(context)
    context.mkdir(parents=True)

    root = repo_root.resolve()
    for source in sorted(files):
        destination = context / source.resolve().relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    (context / "requirements.txt").write_text(requirements_text, encoding="utf-8")
    (context / "Dockerfile").write_text(dockerfile_text, encoding="utf-8")
    (context / ".dockerignore").write_text(DOCKERIGNORE, encoding="utf-8")
    return context
