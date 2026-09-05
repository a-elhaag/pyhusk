import json

import pytest
from typer.testing import CliRunner

from pyhusk.cli import app

runner = CliRunner()


@pytest.fixture
def repo(demo_repo, venv_in, monkeypatch):
    from pyhusk.staleness import BaseRef

    monkeypatch.setattr(
        "pyhusk.pipeline.resolve_base",
        lambda ref: BaseRef(reference=ref, digest="sha256:test", verified=True),
    )
    # No daemon assumed in unit tests, so nothing is ever built and everything is stale.
    monkeypatch.setattr("pyhusk.pipeline.read_slice_label", lambda tag: None)
    return venv_in(demo_repo)


def test_plan_lists_stale_services(repo):
    result = runner.invoke(app, ["plan", "--repo", str(repo)])
    assert result.exit_code == 0, result.output
    assert "a" in result.output
    assert "b" in result.output


def test_plan_json_has_the_documented_shape(repo):
    result = runner.invoke(app, ["plan", "--repo", str(repo), "--json"])
    payload = json.loads(result.output)
    assert set(payload) == {"bases", "services"}
    names = {entry["name"] for entry in payload["services"]}
    assert names == {"a", "b"}
    for entry in payload["services"]:
        assert set(entry) == {"name", "tag", "base", "hash", "stale"}
        assert entry["stale"] is True
        assert len(entry["hash"]) == 64


def test_plan_json_lists_each_base_once(repo):
    payload = json.loads(runner.invoke(app, ["plan", "--repo", str(repo), "--json"]).output)
    tags = [base["tag"] for base in payload["bases"]]
    assert len(tags) == len(set(tags))


def test_plan_json_is_the_only_thing_on_stdout(repo):
    # A CI matrix pipes this straight into a job definition, so a stray warning
    # on stdout would break the pipeline rather than merely look untidy.
    (repo / "services/a/security.py").write_text(
        "def current_user() -> str:\n"
        "    import ghost_package\n"
        "    return ghost_package.who()\n"
    )
    result = runner.invoke(app, ["plan", "--repo", str(repo), "--json"], catch_exceptions=False)
    json.loads(result.stdout)


def test_plan_reports_a_fresh_service_as_not_stale(repo, monkeypatch):
    from pyhusk.config import load_config
    from pyhusk.pipeline import resolve

    # Pretend service a was already built from exactly its current content.
    built = resolve(repo, "a", load_config(repo).services["a"]).slice_hash
    monkeypatch.setattr(
        "pyhusk.pipeline.read_slice_label",
        lambda tag: built if tag == "a:latest" else None,
    )
    payload = json.loads(runner.invoke(app, ["plan", "--repo", str(repo), "--json"]).output)
    stale = {entry["name"]: entry["stale"] for entry in payload["services"]}
    assert stale["a"] is False
    assert stale["b"] is True
