import subprocess
from typer.testing import CliRunner

from pyhusk.affected import affected_services, affected_tests
from pyhusk.cli import app
from pyhusk.config import load_config
from pyhusk.git import changed_files_since, head_commit, last_commit_for_files
from pyhusk.pipeline import resolve

runner = CliRunner()


def _init_git_repo(path):
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=path, check=True)


def test_git_head_commit_and_last_commit(demo_repo):
    _init_git_repo(demo_repo)
    head = head_commit(demo_repo)
    assert head is not None
    assert len(head) >= 7

    last = last_commit_for_files(demo_repo, [demo_repo / "services/a/main.py"])
    assert last is not None
    assert last[0] == head
    assert last[1] == "Initial commit"


def test_affected_services_detects_changed_slice(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    _init_git_repo(repo)
    config = load_config(repo)
    resolutions = {
        name: resolve(repo, name, svc) for name, svc in config.services.items()
    }

    # Edit reporting.py (only service b uses it)
    reporting = repo / "common/reporting.py"
    reporting.write_text(reporting.read_text() + "\n# change\n")

    changed = changed_files_since(repo, "HEAD")
    assert reporting in changed

    affected = affected_services(repo, resolutions, changed)
    assert affected == ["b"]


def test_affected_tests_finds_impacted_tests(demo_repo):
    tests_dir = demo_repo / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_file = tests_dir / "test_sample.py"
    test_file.write_text("import common.models\ndef test_m(): pass\n")

    changed = {demo_repo / "common/models.py"}
    affected = affected_tests(demo_repo, changed)
    assert test_file in affected


def test_cli_affected_and_log(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    _init_git_repo(repo)

    log_res = runner.invoke(app, ["log", "a", "--repo", str(repo)])
    assert log_res.exit_code == 0
    assert "Initial commit" in log_res.output

    aff_res = runner.invoke(app, ["affected", "--repo", str(repo), "--since", "HEAD"])
    assert aff_res.exit_code == 0
    assert "Affected services" in aff_res.output
