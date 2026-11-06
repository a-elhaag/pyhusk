from typer.testing import CliRunner

from pyhusk.cli import app

runner = CliRunner()


def test_why_traces_local_dependency(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    result = runner.invoke(app, ["why", "b", "common/reporting.py", "--repo", str(repo)])
    assert result.exit_code == 0
    assert "reaches common/reporting.py" in result.output
    assert "reporting.py" in result.output


def test_why_traces_third_party_package(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    result = runner.invoke(app, ["why", "b", "httpx", "--repo", str(repo)])
    assert result.exit_code == 0
    assert "reaches httpx" in result.output
    assert "httpx" in result.output


def test_why_reports_unreached_target(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    result = runner.invoke(app, ["why", "a", "common/reporting.py", "--repo", str(repo)])
    assert result.exit_code != 0
    assert "not reached" in result.output


def test_unused_detects_unreferenced_python_file(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    result = runner.invoke(app, ["unused", "--repo", str(repo)])
    assert result.exit_code == 0
    assert "unused.py" in result.output
    assert "common/unused.py" in result.output
