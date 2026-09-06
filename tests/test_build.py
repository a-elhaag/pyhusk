import pytest
from typer.testing import CliRunner

from conftest import needs_docker
from pyhusk.cli import app
from pyhusk.report import human_size

runner = CliRunner()


@pytest.fixture
def repo(demo_repo, venv_in, monkeypatch):
    from pyhusk.staleness import BaseRef

    monkeypatch.setattr(
        "pyhusk.pipeline.resolve_base",
        lambda ref, **_: BaseRef(reference=ref, digest="sha256:test", verified=True),
    )
    return venv_in(demo_repo)


@pytest.fixture
def docker_repo(demo_repo, venv_in):
    """A repo with a real, resolvable base image digest.

    The Docker-integration tests actually build images, and a fake digest fails
    with an "invalid reference format" error before the build logic is ever
    exercised. Only these tests need this; the pure-Python tests above are
    faster with a mocked digest.
    """
    return venv_in(demo_repo)


def test_human_size_is_readable():
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KB"
    assert human_size(120 * 1024 * 1024) == "120.0 MB"


def test_show_dockerfile_writes_the_context_without_building(repo):
    result = runner.invoke(app, ["build", "a", "--repo", str(repo), "--show-dockerfile"])
    assert result.exit_code == 0, result.output
    context = repo / ".build" / "a"
    assert (context / "Dockerfile").is_file()
    assert (context / "requirements.txt").is_file()
    assert (context / "services/a/main.py").is_file()
    assert not (context / "services/b").exists()


def test_show_dockerfile_context_excludes_the_other_service_entirely(repo):
    runner.invoke(app, ["build", "a", "--repo", str(repo), "--show-dockerfile"])
    copied = {p.name for p in (repo / ".build/a").rglob("*.py")}
    assert "main.py" in copied
    assert "reporting.py" not in copied   # b's dependency
    assert "unused.py" not in copied      # nobody's


def test_show_dockerfile_prunes_dependencies_too(repo):
    runner.invoke(app, ["build", "b", "--repo", str(repo), "--show-dockerfile"])
    b_requirements = (repo / ".build/b/requirements.txt").read_text()
    runner.invoke(app, ["build", "a", "--repo", str(repo), "--show-dockerfile"])
    a_requirements = (repo / ".build/a/requirements.txt").read_text()
    assert "httpx" in b_requirements
    assert "httpx" not in a_requirements


def test_include_forces_a_path_into_the_context(repo):
    plugin = repo / "plugins" / "late.py"
    plugin.parent.mkdir()
    plugin.write_text("VALUE = 1\n")
    runner.invoke(
        app,
        ["build", "a", "--repo", str(repo), "--show-dockerfile", "--include", "plugins/late.py"],
    )
    assert (repo / ".build/a/plugins/late.py").is_file()


def test_unknown_service_name_exits_nonzero(repo):
    result = runner.invoke(app, ["build", "nope", "--repo", str(repo), "--show-dockerfile"])
    assert result.exit_code != 0
    assert "nope" in result.output


def test_warnings_are_printed(repo):
    (repo / "services/a/security.py").write_text(
        "def current_user() -> str:\n"
        "    import ghost_package\n"
        "    return ghost_package.who()\n"
    )
    result = runner.invoke(app, ["build", "a", "--repo", str(repo), "--show-dockerfile"])
    assert "ghost_package" in result.output


@pytest.mark.docker
@needs_docker
def test_end_to_end_build_produces_a_verified_image(docker_repo):
    result = runner.invoke(app, ["build", "a", "--repo", str(docker_repo)])
    assert result.exit_code == 0, result.output
    from pyhusk.docker import image_exists, run_docker

    assert image_exists("a:latest")
    listing = run_docker(["run", "--rm", "--entrypoint", "sh", "a:latest", "-c", "ls /app/services"])
    assert "a" in listing.stdout
    assert "b" not in listing.stdout


@pytest.mark.docker
@needs_docker
def test_second_build_is_skipped_as_unchanged(docker_repo):
    runner.invoke(app, ["build", "a", "--repo", str(docker_repo)])
    result = runner.invoke(app, ["build", "a", "--repo", str(docker_repo)])
    assert "unchanged" in result.output


@pytest.mark.docker
@needs_docker
def test_editing_a_shared_module_restales_only_its_dependents(docker_repo):
    runner.invoke(app, ["build", "--repo", str(docker_repo)])
    (docker_repo / "common/reporting.py").write_text(
        "import httpx\n\n\nasync def fetch_report(url: str) -> str:\n    return 'edited'\n"
    )
    result = runner.invoke(app, ["plan", "--repo", str(docker_repo)])
    lines = {line.split("\t")[0]: line.split("\t")[1] for line in result.output.strip().splitlines()}
    assert lines["b"] == "stale"
    assert lines["a"] == "unchanged"


def test_count_python_files_ignores_the_venv_and_build_dirs(demo_repo):
    from pyhusk.report import count_python_files

    real = count_python_files(demo_repo)
    (demo_repo / ".venv" / "lib").mkdir(parents=True)
    (demo_repo / ".venv" / "lib" / "site.py").write_text("")
    (demo_repo / ".build" / "a").mkdir(parents=True, exist_ok=True)
    (demo_repo / ".build" / "a" / "copy.py").write_text("")
    assert count_python_files(demo_repo) == real
    assert real == 10


@pytest.mark.docker
@needs_docker
def test_failed_verification_does_not_poison_staleness(docker_repo):
    # A module-scope dynamic import: the probe survives it, the static walk
    # cannot see it, the image lacks the file, the container dies on startup.
    (docker_repo / "services/a/main.py").write_text(
        "import importlib\n"
        "from fastapi import FastAPI\n"
        "importlib.import_module('common.unused')\n"
        "app = FastAPI()\n"
    )
    first = runner.invoke(app, ["build", "a", "--repo", str(docker_repo)])
    assert first.exit_code != 0
    assert "verification failed" in first.output

    # Without the untag, this second run would see a matching label and report
    # "unchanged", and the broken image would never be rebuilt.
    second = runner.invoke(app, ["build", "a", "--repo", str(docker_repo)])
    assert "unchanged" not in second.output
    assert "building" in second.output
