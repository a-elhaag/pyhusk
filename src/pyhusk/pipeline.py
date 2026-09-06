from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pyhusk.config import ServiceConfig
from pyhusk.deps import RequirementsResult, resolve_requirements
from pyhusk.discover import RouteInfo, probe
from pyhusk.dockerize import override_for, render_dockerfile
from pyhusk.graph import build_slice
from pyhusk.staleness import BaseRef, base_hash, read_slice_label, resolve_base, slice_hash

BASE_IMAGE_PREFIX = "pyhusk-base"


@dataclass
class Resolution:
    name: str
    service: ServiceConfig
    files: set[Path]
    routes: list[RouteInfo]
    openapi_url: str | None
    requirements: RequirementsResult
    base: BaseRef
    base_tag: str | None
    dockerfile_text: str
    slice_hash: str
    warnings: list[str] = field(default_factory=list)

    @property
    def tag(self) -> str:
        return f"{self.name}:latest"

    @property
    def remote_tag(self) -> str | None:
        if self.service.registry is None:
            return None
        return f"{self.service.registry}/{self.name}:latest"


def resolve(
    repo_root: Path,
    name: str,
    service: ServiceConfig,
    includes: Iterable[Path] = (),
    shared_base: bool = True,
) -> Resolution:
    """Run every stage that precedes building, in dependency order.

    Ordering matters and is easy to get wrong, which is why it lives here rather
    than in a command body: the slice must exist before requirements can be
    resolved, requirements before the base identity, and the base identity before
    the Dockerfile, because the Dockerfile text feeds the slice hash.
    """
    warnings: list[str] = []
    root = repo_root.resolve()

    probed = probe(repo_root, service)
    sliced = build_slice(repo_root, probed.files, includes)

    for item in sliced.unresolved:
        warnings.append(
            f"unresolved import {item.module!r} at "
            f"{item.file.relative_to(root)}:{item.lineno}"
        )
    for path in sliced.unparseable:
        warnings.append(
            f"could not parse {path.relative_to(root)}; it is included in the "
            f"image, but its own imports were not followed"
        )

    requirements = resolve_requirements(repo_root, sliced.third_party)
    for missing in requirements.unmapped:
        warnings.append(
            f"import {missing!r} matched no installed distribution; if the image fails "
            f"to start, add it to the target repository's dependencies"
        )

    base = resolve_base(service.base_image, cache=repo_root / ".build" / "_digests.json")
    if base.source == "stale-cache":
        warnings.append(
            f"registry unreachable; using the last known digest for {service.base_image}. "
            f"An upstream update will not be noticed until the registry answers again"
        )
    elif not base.verified:
        warnings.append(
            f"could not resolve a digest for {service.base_image}; base image freshness "
            f"is unverified, so an upstream update will not trigger a rebuild"
        )

    override = override_for(service)
    if override is not None:
        dockerfile_text = override.read_text(encoding="utf-8")
        base_tag = None
    elif shared_base:
        base_tag = f"{BASE_IMAGE_PREFIX}:{base_hash(base, requirements.text)}"
        dockerfile_text = render_dockerfile(repo_root, service, base_tag, False)
    else:
        base_tag = None
        dockerfile_text = render_dockerfile(repo_root, service, base.pinned, True)

    return Resolution(
        name=name,
        service=service,
        files=sliced.files,
        routes=probed.routes,
        openapi_url=probed.openapi_url,
        requirements=requirements,
        base=base,
        base_tag=base_tag,
        dockerfile_text=dockerfile_text,
        slice_hash=slice_hash(
            repo_root, sliced.files, requirements.text, dockerfile_text, base
        ),
        warnings=warnings,
    )


def is_stale(resolution: Resolution) -> bool:
    """True when the built image is missing or built from different content."""
    label = read_slice_label(resolution.tag)
    if label is None and resolution.remote_tag:
        label = read_slice_label(resolution.remote_tag)
    return label != resolution.slice_hash
