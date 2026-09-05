import yaml
from typer.testing import CliRunner

from pyhusk.cli import app

runner = CliRunner()


def write_service(root, name):
    path = root / "services" / name / "main.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("from fastapi import FastAPI\napp = FastAPI()\n")


def test_init_writes_config_from_detected_services(tmp_path):
    write_service(tmp_path, "auth")
    write_service(tmp_path, "pay")
    result = runner.invoke(app, ["init", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output
    written = yaml.safe_load((tmp_path / "pyhusk.yaml").read_text())
    assert set(written["services"]) == {"auth", "pay"}
    assert written["services"]["auth"]["entry"] == "services/auth/main.py"
    assert written["services"]["auth"]["app"] == "app"


def test_init_adds_build_dir_to_gitignore(tmp_path):
    write_service(tmp_path, "auth")
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    runner.invoke(app, ["init", "--repo", str(tmp_path)])
    assert ".build/" in (tmp_path / ".gitignore").read_text()


def test_init_creates_gitignore_when_absent(tmp_path):
    write_service(tmp_path, "auth")
    runner.invoke(app, ["init", "--repo", str(tmp_path)])
    assert (tmp_path / ".gitignore").read_text().strip() == ".build/"


def test_init_is_idempotent(tmp_path):
    write_service(tmp_path, "auth")
    runner.invoke(app, ["init", "--repo", str(tmp_path)])
    (tmp_path / "pyhusk.yaml").write_text(
        "services:\n  hand-edited:\n    entry: services/auth/main.py\n"
    )
    result = runner.invoke(app, ["init", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "hand-edited" in (tmp_path / "pyhusk.yaml").read_text()
    assert (tmp_path / ".gitignore").read_text().count(".build/") == 1


def test_init_without_services_exits_nonzero(tmp_path):
    result = runner.invoke(app, ["init", "--repo", str(tmp_path)])
    assert result.exit_code != 0
    assert "FastAPI" in result.output


def test_list_shows_services_and_entries(tmp_path):
    write_service(tmp_path, "auth")
    result = runner.invoke(app, ["list", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert "auth" in result.output
    assert "services/auth/main.py" in result.output
