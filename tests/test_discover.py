import sys

import pytest

from pyhusk.config import ServiceConfig
from pyhusk.discover import probe, venv_python
from pyhusk.errors import PyhuskError


def test_venv_python_is_platform_correct(tmp_path):
    resolved = venv_python(tmp_path)
    if sys.platform == "win32":
        assert resolved == tmp_path / ".venv" / "Scripts" / "python.exe"
    else:
        assert resolved == tmp_path / ".venv" / "bin" / "python"


def test_missing_venv_names_the_expected_path(tmp_path):
    (tmp_path / "main.py").write_text("app = 1\n")
    service = ServiceConfig(entry=tmp_path / "main.py")
    with pytest.raises(PyhuskError) as excinfo:
        probe(tmp_path, service)
    assert ".venv" in str(excinfo.value)


def test_probe_returns_repo_local_files_only(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    service = ServiceConfig(entry=repo / "services/a/main.py")
    result = probe(repo, service)
    names = {path.name for path in result.files}
    assert "main.py" in names
    assert "security.py" in names
    assert all(".venv" not in path.parts for path in result.files)
    assert all(path.is_absolute() for path in result.files)


def test_probe_returns_routes_and_openapi_url(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    service = ServiceConfig(entry=repo / "services/a/main.py")
    result = probe(repo, service)
    assert result.openapi_url == "/openapi.json"
    assert any(route.path == "/items/{item_id}" for route in result.routes)
    assert any("GET" in route.methods for route in result.routes)
    assert any(route.documented for route in result.routes)


def test_probe_failure_surfaces_the_subprocess_stderr(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    (repo / "services/a/main.py").write_text("import nope_not_here\napp = None\n")
    service = ServiceConfig(entry=repo / "services/a/main.py")
    with pytest.raises(PyhuskError) as excinfo:
        probe(repo, service)
    assert "nope_not_here" in str(excinfo.value)
