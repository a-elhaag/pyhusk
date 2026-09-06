import pytest

from pyhusk.config import ServiceConfig
from pyhusk.discover import RouteInfo
from conftest import needs_docker
from pyhusk.verify import choose_tier, compare_routes, verify


def test_schema_tier_when_openapi_is_enabled():
    assert choose_tier("/openapi.json", None) == "schema"
    assert choose_tier("/openapi.json", "/healthz") == "schema"


def test_healthcheck_tier_when_openapi_is_disabled_but_a_path_is_configured():
    assert choose_tier(None, "/healthz") == "healthcheck"


def test_boot_tier_when_nothing_can_be_polled():
    assert choose_tier(None, None) == "boot"


def test_compare_routes_accepts_a_matching_schema():
    expected = [RouteInfo(path="/items/{item_id}", methods=["GET"], documented=True)]
    assert compare_routes(expected, {"paths": {"/items/{item_id}": {"get": {}}}}) == []


def test_compare_routes_reports_a_missing_path():
    expected = [RouteInfo(path="/items/{item_id}", methods=["GET"], documented=True)]
    assert compare_routes(expected, {"paths": {}}) == ["GET /items/{item_id}"]


def test_compare_routes_reports_a_missing_method():
    expected = [RouteInfo(path="/items", methods=["GET", "POST"], documented=True)]
    assert compare_routes(expected, {"paths": {"/items": {"get": {}}}}) == ["POST /items"]


def test_compare_routes_ignores_undocumented_routes():
    # A plain Starlette route added with add_route never appears in the OpenAPI
    # schema, so requiring it there would fail every correct build.
    expected = [
        RouteInfo(path="/plain", methods=["GET"], documented=False),
        RouteInfo(path="/documented", methods=["GET"], documented=True),
    ]
    assert compare_routes(expected, {"paths": {"/documented": {"get": {}}}}) == []


def test_compare_routes_ignores_implicit_head():
    # Starlette adds HEAD alongside GET; OpenAPI does not list it.
    expected = [RouteInfo(path="/items", methods=["GET", "HEAD"], documented=True)]
    assert compare_routes(expected, {"paths": {"/items": {"get": {}}}}) == []


@pytest.mark.docker
@needs_docker
def test_verify_fails_a_container_that_cannot_start(tmp_path):
    from pyhusk.docker import run_docker

    context = tmp_path / "ctx"
    context.mkdir()
    (context / "Dockerfile").write_text(
        'FROM alpine:3.20\nCMD ["sh", "-c", "echo boom >&2; exit 1"]\n'
    )
    built = run_docker(["build", "-t", "pyhusk-test-broken:latest", str(context)], timeout=300)
    assert built.returncode == 0, built.stderr
    service = ServiceConfig(entry=tmp_path / "main.py", port=8000)
    result = verify("pyhusk-test-broken:latest", service, [], None, timeout=15)
    assert result.ok is False
    assert "boom" in result.detail
