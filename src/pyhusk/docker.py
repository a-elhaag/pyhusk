from __future__ import annotations

import shutil
import subprocess

from pyhusk.errors import PyhuskError


def run_docker(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Invoke the docker CLI. Never shell=True."""
    if shutil.which("docker") is None:
        raise PyhuskError("docker is not on PATH. pyhusk shells out to the Docker CLI.")
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    return subprocess.run(["docker", *args], **kwargs)


def docker_available() -> bool:
    """True when a Docker daemon is reachable."""
    if shutil.which("docker") is None:
        return False
    try:
        return run_docker(["info", "--format", "{{.ServerVersion}}"], timeout=30).returncode == 0
    except (subprocess.TimeoutExpired, PyhuskError):
        return False


def require_docker() -> None:
    if not docker_available():
        raise PyhuskError(
            "Cannot reach a Docker daemon. Start Docker and try again, or use "
            "`pyhusk plan` and `--show-dockerfile`, which need no daemon."
        )


def image_exists(tag: str) -> bool:
    return run_docker(["image", "inspect", tag, "--format", "{{.Id}}"]).returncode == 0


def image_size(tag: str) -> int:
    """Image size in bytes, or 0 when the image is absent."""
    completed = run_docker(["image", "inspect", tag, "--format", "{{.Size}}"])
    if completed.returncode != 0:
        return 0
    try:
        return int(completed.stdout.strip())
    except ValueError:
        return 0
