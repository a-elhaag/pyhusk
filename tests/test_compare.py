from pyhusk.deps import all_requirements, resolve_requirements


def test_all_requirements_contains_every_locked_package(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    everything = all_requirements(repo)
    names = {pin.split("==")[0] for pin in everything.pins}
    assert {"fastapi", "httpx", "uvicorn", "certifi", "pydantic-core"} <= names


def test_all_requirements_is_a_superset_of_a_service_slice(demo_repo, venv_in):
    repo = venv_in(demo_repo)
    pruned = {pin.split("==")[0] for pin in resolve_requirements(repo, {"fastapi"}).pins}
    everything = {pin.split("==")[0] for pin in all_requirements(repo).pins}
    assert pruned < everything
