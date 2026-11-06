import yaml
from typer.testing import CliRunner

from pyhusk.cli import app

runner = CliRunner()


def test_lint_passes_on_clean_demo(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    result = runner.invoke(app, ["lint", "--repo", str(repo), "--no-ruff"])
    assert result.exit_code == 0
    assert "lint passed" in result.output


def test_lint_detects_cross_service_violation(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    (repo / "services/a/main.py").write_text(
        "from fastapi import FastAPI\n"
        "from services.b import main as b_main\n"
        "app = FastAPI()\n"
    )
    result = runner.invoke(app, ["lint", "a", "--repo", str(repo), "--no-ruff"])
    assert result.exit_code != 0
    assert "cross-service import" in result.output
    assert "services.b" in result.output or "services/b" in result.output


def test_lint_detects_forbid_imports(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    cfg = yaml.safe_load((repo / "pyhusk.yaml").read_text())
    cfg["services"]["b"]["forbid_imports"] = ["httpx"]
    (repo / "pyhusk.yaml").write_text(yaml.safe_dump(cfg))

    result = runner.invoke(app, ["lint", "b", "--repo", str(repo), "--no-ruff"])
    assert result.exit_code != 0
    assert "forbidden package/module 'httpx'" in result.output


def test_lint_detects_circular_imports(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    (repo / "common/models.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class Item(BaseModel):\n"
        "    id: int\n"
        "    name: str\n\n"
        "def helper():\n"
        "    import common.reporting\n"
    )
    (repo / "common/reporting.py").write_text(
        "import httpx\n"
        "from common.models import Item\n"
        "async def fetch_report(url: str): pass\n"
    )

    result = runner.invoke(app, ["lint", "b", "--repo", str(repo), "--strict", "--no-ruff"])
    assert result.exit_code != 0
    assert "circular import" in result.output
