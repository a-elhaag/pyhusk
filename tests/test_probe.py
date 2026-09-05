import json
import subprocess
import sys
from pathlib import Path

PROBE = Path("src/pyhusk/_probe.py").resolve()


def run_probe(repo: Path, venv: Path, entry: str, app: str, factory: bool = False):
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    argv = [str(python), str(PROBE), "--entry", entry, "--app", app]
    if factory:
        argv.append("--factory")
    return subprocess.run(argv, cwd=repo, capture_output=True, text=True)


def test_probe_reports_handler_and_dependency_files(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    result = run_probe(repo, repo / ".venv", "services/a/main.py", "app")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    files = {Path(p).name for p in payload["files"]}
    assert "main.py" in files
    # Reached only through Depends(), never imported literally in a route body.
    assert "security.py" in files


def test_probe_reports_routes_and_openapi_url(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    payload = json.loads(run_probe(repo, repo / ".venv", "services/a/main.py", "app").stdout)
    paths = {route["path"] for route in payload["routes"]}
    assert "/items/{item_id}" in paths
    assert payload["openapi_url"] == "/openapi.json"


def test_probe_survives_every_route_shape(routetypes_repo, venv_in):
    repo = venv_in(routetypes_repo)
    result = run_probe(repo, repo / ".venv", "app.py", "app")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    files = {Path(p).name for p in payload["files"]}
    assert "handlers.py" in files       # plain Starlette route and mounted route
    assert "providers.py" in files      # nested Depends chain
    assert "unreferenced.py" not in files
    paths = {route["path"] for route in payload["routes"]}
    assert "/decorated" in paths
    assert "/plain" in paths
    assert "/sub/inner" in paths        # mount prefix applied


def test_probe_marks_only_schema_routes_as_documented(routetypes_repo, venv_in):
    repo = venv_in(routetypes_repo)
    payload = json.loads(run_probe(repo, repo / ".venv", "app.py", "app").stdout)
    documented = {r["path"] for r in payload["routes"] if r["documented"]}
    assert "/decorated" in documented
    assert "/plain" not in documented


def test_probe_supports_the_factory_pattern(routetypes_repo, venv_in):
    repo = venv_in(routetypes_repo)
    result = run_probe(repo, repo / ".venv", "app.py", "build", factory=True)
    assert result.returncode == 0, result.stderr
    assert "/decorated" in {r["path"] for r in json.loads(result.stdout)["routes"]}


def test_probe_rejects_a_non_callable_under_factory(routetypes_repo, venv_in):
    repo = venv_in(routetypes_repo)
    (repo / "app.py").write_text("app = object()\n")
    result = run_probe(repo, repo / ".venv", "app.py", "app", factory=True)
    assert result.returncode != 0
    assert "not callable" in result.stderr.lower()


def test_probe_reports_a_missing_attribute_clearly(routetypes_repo, venv_in):
    repo = venv_in(routetypes_repo)
    result = run_probe(repo, repo / ".venv", "app.py", "nonexistent")
    assert result.returncode != 0
    assert "nonexistent" in result.stderr


def test_probe_propagates_an_import_error(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    (repo / "services/a/main.py").write_text("import a_module_that_does_not_exist\napp = None\n")
    result = run_probe(repo, repo / ".venv", "services/a/main.py", "app")
    assert result.returncode != 0
    assert "a_module_that_does_not_exist" in result.stderr
