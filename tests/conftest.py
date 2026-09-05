import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    destination = tmp_path / name
    shutil.copytree(FIXTURES / name, destination)
    return destination


@pytest.fixture
def demo_repo(tmp_path: Path) -> Path:
    """A copy of the two-service demo monorepo, safe to mutate."""
    return _copy_fixture("demo", tmp_path)


@pytest.fixture
def routetypes_repo(tmp_path: Path) -> Path:
    """A copy of the route-shapes app, safe to mutate."""
    return _copy_fixture("routetypes", tmp_path)


@pytest.fixture(scope="session")
def fastapi_venv(tmp_path_factory) -> Path:
    """A virtualenv with fastapi and httpx, reused across the session.

    The probe runs inside the *target* repo's interpreter, so probe tests need a
    real venv rather than pyhusk's own. Built once because creating it costs
    seconds, not milliseconds.
    """
    venv = tmp_path_factory.mktemp("venv") / ".venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "fastapi", "httpx", "uvicorn"],
        check=True,
    )
    return venv


@pytest.fixture
def venv_in(fastapi_venv: Path):
    """Link the session venv into a repo copy, so probes can run against it."""

    def link(repo: Path) -> Path:
        target = repo / ".venv"
        if not target.exists():
            target.symlink_to(fastapi_venv, target_is_directory=True)
        return repo

    return link
