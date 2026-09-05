import pytest

from pyhusk.deps import resolve_requirements
from pyhusk.errors import PyhuskError


def test_service_a_gets_fastapi_closure_without_httpx(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    result = resolve_requirements(repo, {"fastapi"})
    names = {pin.split("==")[0] for pin in result.pins}
    assert "fastapi" in names
    assert "pydantic" in names       # transitive
    assert "starlette" in names      # transitive
    assert "httpx" not in names      # service b's alone
    assert "certifi" not in names    # only reachable through httpx


def test_service_b_gets_httpx_closure(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    result = resolve_requirements(repo, {"fastapi", "httpx"})
    names = {pin.split("==")[0] for pin in result.pins}
    assert {"httpx", "httpcore", "certifi", "idna"} <= names


def test_server_is_injected_even_though_nothing_imports_it(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    result = resolve_requirements(repo, {"fastapi"})
    names = {pin.split("==")[0] for pin in result.pins}
    # Application code never imports uvicorn; the server imports the application.
    # Without injection the generated CMD would have no server to run.
    assert "uvicorn" in names


def test_pins_carry_versions_and_are_sorted(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    result = resolve_requirements(repo, {"fastapi"})
    assert all("==" in pin for pin in result.pins)
    assert result.pins == sorted(result.pins)
    assert result.text.endswith("\n")
    assert result.text.splitlines() == result.pins


def test_unmappable_import_is_reported_not_dropped(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    result = resolve_requirements(repo, {"fastapi", "totally_not_installed"})
    assert "totally_not_installed" in result.unmapped
    assert any(pin.startswith("fastapi==") for pin in result.pins)


def test_missing_lock_is_an_error(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    (repo / "uv.lock").unlink()
    with pytest.raises(PyhuskError) as excinfo:
        resolve_requirements(repo, {"fastapi"})
    assert "uv.lock" in str(excinfo.value)


def test_name_normalization_handles_underscores_and_dots(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    result = resolve_requirements(repo, {"fastapi"})
    names = {pin.split("==")[0] for pin in result.pins}
    assert "pydantic-core" in names
