from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from pyhusk.config import ServiceConfig
from pyhusk.discover import RouteInfo
from pyhusk.docker import run_docker

# Starlette adds these alongside a declared GET; OpenAPI never lists them.
IMPLICIT_METHODS = {"HEAD", "OPTIONS"}


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    tier: str
    detail: str


def choose_tier(openapi_url: str | None, healthcheck: str | None) -> str:
    """Pick the strongest verification the service allows.

    Disabling the OpenAPI schema is normal production hardening, so a service
    that does it must still be verifiable, just less thoroughly.
    """
    if openapi_url:
        return "schema"
    if healthcheck:
        return "healthcheck"
    return "boot"


def compare_routes(expected: list[RouteInfo], schema: dict) -> list[str]:
    """Route descriptions the probe found that the running container does not serve."""
    published = schema.get("paths") or {}
    missing: list[str] = []
    for route in expected:
        if not route.documented:
            continue
        operations = published.get(route.path)
        wanted = [m for m in route.methods if m not in IMPLICIT_METHODS]
        if operations is None:
            missing.extend(f"{method} {route.path}" for method in wanted)
            continue
        missing.extend(
            f"{method} {route.path}" for method in wanted if method.lower() not in operations
        )
    return sorted(missing)


def _poll(url: str, deadline: float) -> tuple[bool, str, bytes]:
    last = "no response"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if 200 <= response.status < 400:
                    return True, "", response.read()
                last = f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = str(exc)
        time.sleep(0.4)
    return False, last, b""


def _host_port(container: str, container_port: int) -> str | None:
    published = run_docker(["port", container, f"{container_port}/tcp"])
    if published.returncode != 0 or not published.stdout.strip():
        return None
    # Output looks like "127.0.0.1:54321"; take the last field of the first line.
    return published.stdout.strip().splitlines()[0].rsplit(":", 1)[-1]


def _logs(container: str) -> str:
    completed = run_docker(["logs", "--tail", "50", container])
    return (completed.stdout + completed.stderr).strip() or "(no container output)"


def verify(
    tag: str,
    service: ServiceConfig,
    routes: list[RouteInfo],
    openapi_url: str | None,
    timeout: float = 60.0,
) -> VerifyResult:
    """Start the built image and confirm it serves what the probe found.

    This is what turns the tool's central risk, a missing file producing an image
    that dies on startup, into a build failure rather than a deploy failure.
    """
    tier = choose_tier(openapi_url, service.healthcheck)
    started = run_docker(
        ["run", "-d", "-p", f"127.0.0.1:0:{service.port}", tag], timeout=120
    )
    if started.returncode != 0:
        return VerifyResult(False, tier, f"could not start container:\n{started.stderr.strip()}")
    container = started.stdout.strip()

    try:
        deadline = time.monotonic() + timeout

        if tier == "boot":
            time.sleep(min(5.0, timeout))
            state = run_docker(["inspect", container, "--format", "{{.State.Running}}"])
            if state.stdout.strip() != "true":
                return VerifyResult(False, tier, _logs(container))
            return VerifyResult(
                True,
                tier,
                "container stayed up; routes were not checked because the OpenAPI "
                "schema is disabled and no healthcheck path is configured",
            )

        port = _host_port(container, service.port)
        if port is None:
            return VerifyResult(
                False, tier, f"container published no port for {service.port}\n{_logs(container)}"
            )

        path = openapi_url if tier == "schema" else service.healthcheck
        ok, why, body = _poll(f"http://127.0.0.1:{port}{path}", deadline)
        if not ok:
            return VerifyResult(False, tier, f"{path} never responded ({why})\n{_logs(container)}")

        if tier == "healthcheck":
            return VerifyResult(True, tier, f"{path} responded; routes were not compared")

        try:
            schema = json.loads(body)
        except json.JSONDecodeError:
            return VerifyResult(False, tier, f"{path} did not return JSON")

        missing = compare_routes(routes, schema)
        if missing:
            return VerifyResult(
                False,
                tier,
                "the container does not serve routes the probe found: " + ", ".join(missing),
            )
        return VerifyResult(True, tier, f"served all {len(routes)} discovered route(s)")
    finally:
        run_docker(["rm", "-f", container])
