from pyhusk.config import ServiceConfig
from pyhusk.dockerize import (
    assemble_context,
    override_for,
    render_base_dockerfile,
    render_dockerfile,
)


def service_a(repo):
    return ServiceConfig(entry=repo / "services/a/main.py")


def test_dockerfile_targets_the_right_uvicorn_module(demo_repo):
    text = render_dockerfile(demo_repo, service_a(demo_repo), "python:3.12-slim", True)
    assert "services.a.main:app" in text
    assert "--host" in text and "0.0.0.0" in text
    assert "8000" in text


def test_dockerfile_installs_requirements_before_copying_code(demo_repo):
    text = render_dockerfile(demo_repo, service_a(demo_repo), "python:3.12-slim", True)
    assert text.index("requirements.txt") < text.index("COPY . .")


def test_dockerfile_from_a_shared_base_skips_the_install(demo_repo):
    text = render_dockerfile(demo_repo, service_a(demo_repo), "pyhusk-base:abc123", False)
    assert text.startswith("FROM pyhusk-base:abc123")
    assert "pip install" not in text


def test_factory_services_get_the_uvicorn_factory_flag(demo_repo):
    service = ServiceConfig(entry=demo_repo / "services/a/main.py", app="build", factory=True)
    text = render_dockerfile(demo_repo, service, "python:3.12-slim", True)
    assert "services.a.main:build" in text
    assert "--factory" in text


def test_custom_port_reaches_both_expose_and_cmd(demo_repo):
    service = ServiceConfig(entry=demo_repo / "services/a/main.py", port=9001)
    text = render_dockerfile(demo_repo, service, "python:3.12-slim", True)
    assert "EXPOSE 9001" in text
    assert "9001" in text.strip().splitlines()[-1]


def test_override_is_detected_next_to_the_entry_file(demo_repo):
    assert override_for(service_a(demo_repo)) is None
    override = demo_repo / "services/a/Dockerfile.override"
    override.write_text("FROM scratch\n")
    assert override_for(service_a(demo_repo)) == override


def test_context_contains_only_the_slice(demo_repo):
    files = {demo_repo / "services/a/main.py", demo_repo / "common/models.py"}
    context = assemble_context(
        demo_repo, "a", service_a(demo_repo), files, "fastapi==0.115.0\n", "FROM scratch\n"
    )
    assert (context / "services/a/main.py").is_file()
    assert (context / "common/models.py").is_file()
    assert not (context / "services/b").exists()
    assert not (context / "common/unused.py").exists()
    assert (context / "requirements.txt").read_text() == "fastapi==0.115.0\n"
    assert (context / "Dockerfile").read_text() == "FROM scratch\n"


def test_context_is_rebuilt_from_scratch_each_time(demo_repo):
    files = {demo_repo / "services/a/main.py"}
    context = assemble_context(demo_repo, "a", service_a(demo_repo), files, "", "FROM scratch\n")
    stale = context / "common" / "leftover.py"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale\n")
    assemble_context(demo_repo, "a", service_a(demo_repo), files, "", "FROM scratch\n")
    assert not stale.exists()


def test_context_excludes_its_own_dockerfile_from_the_image(demo_repo):
    files = {demo_repo / "services/a/main.py"}
    context = assemble_context(demo_repo, "a", service_a(demo_repo), files, "", "FROM scratch\n")
    assert "Dockerfile" in (context / ".dockerignore").read_text()


def test_base_dockerfile_installs_and_nothing_else(demo_repo):
    text = render_base_dockerfile("python:3.12-slim")
    assert text.startswith("FROM python:3.12-slim")
    assert "pip install" in text
    assert "CMD" not in text
