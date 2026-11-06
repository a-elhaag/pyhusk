import yaml
from typer.testing import CliRunner

from pyhusk.cli import app
from pyhusk.config import expand_includes, load_config
from pyhusk.dockerize import render_dockerfile
from pyhusk.pipeline import resolve

runner = CliRunner()


def test_expand_includes_directory_and_glob(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001.sql").write_text("SELECT 1;")
    (migrations / "0002.sql").write_text("SELECT 2;")

    expanded = expand_includes(tmp_path, ["migrations/"])
    assert len(expanded) == 2
    assert (migrations / "0001.sql") in expanded
    assert (migrations / "0002.sql") in expanded

    globbed = expand_includes(tmp_path, ["migrations/*.sql"])
    assert len(globbed) == 2


def test_service_config_include_in_slice(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    sql_file = repo / "queries" / "report.sql"
    sql_file.parent.mkdir()
    sql_file.write_text("SELECT 1;")

    cfg = yaml.safe_load((repo / "pyhusk.yaml").read_text())
    cfg["services"]["b"]["include"] = ["queries/report.sql"]
    (repo / "pyhusk.yaml").write_text(yaml.safe_dump(cfg))

    config = load_config(repo)
    res = resolve(repo, "b", config.services["b"])
    assert sql_file in res.files


def test_worker_kind_and_custom_command(tmp_path):
    entry = tmp_path / "worker" / "run.py"
    entry.parent.mkdir()
    entry.write_text("print('worker running')\n")

    cfg_data = {
        "services": {
            "worker": {
                "entry": "worker/run.py",
                "kind": "worker",
                "command": ["python", "-m", "worker.run"],
                "env": {"WORKER_CONCURRENCY": "4"},
            }
        }
    }
    (tmp_path / "pyhusk.yaml").write_text(yaml.safe_dump(cfg_data))
    config = load_config(tmp_path)
    svc = config.services["worker"]
    assert svc.kind == "worker"
    assert svc.command == ["python", "-m", "worker.run"]
    assert svc.env["WORKER_CONCURRENCY"] == "4"

    dockerfile = render_dockerfile(tmp_path, svc, "python:3.12-slim", True)
    assert 'CMD ["python", "-m", "worker.run"]' in dockerfile
