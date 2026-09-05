from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pyhusk.docker import run_docker

SLICE_LABEL = "org.pyhusk.slice"


@dataclass(frozen=True)
class BaseRef:
    reference: str
    digest: str
    verified: bool

    @property
    def pinned(self) -> str:
        """The reference to write into a FROM line."""
        if self.verified and "@" not in self.reference:
            return f"{self.reference}@{self.digest}"
        return self.reference


@functools.lru_cache(maxsize=None)
def resolve_base(reference: str) -> BaseRef:
    """Resolve a base image tag to its content digest.

    Base tags are mutable. python:3.12-slim moves on every patch release,
    including security patches, so without the digest an unchanged Dockerfile
    hashes the same and pyhusk reports a service as fresh while its image sits on
    a superseded base.

    Memoized per reference, so a ten-service repo on one base makes one query.
    """
    remote = run_docker(
        ["buildx", "imagetools", "inspect", reference, "--format", "{{.Manifest.Digest}}"],
        timeout=60,
    )
    if remote.returncode == 0 and remote.stdout.strip():
        return BaseRef(reference=reference, digest=remote.stdout.strip(), verified=True)

    local = run_docker(
        ["image", "inspect", reference, "--format", "{{index .RepoDigests 0}}"], timeout=30
    )
    if local.returncode == 0 and "@" in local.stdout:
        return BaseRef(
            reference=reference, digest=local.stdout.strip().split("@", 1)[1], verified=True
        )

    # No registry and no local copy. Fall back to the old tag-only behaviour, but
    # say so rather than pretending the base is pinned.
    return BaseRef(reference=reference, digest=reference, verified=False)


def base_hash(base: BaseRef, requirements_text: str) -> str:
    """Identity of a shared base image: its source image plus what it installs.

    Both inputs matter. Hashing requirements alone collides two services that
    install the same packages onto different interpreters.
    """
    digest = hashlib.sha256()
    digest.update(base.digest.encode())
    digest.update(b"\0")
    digest.update(requirements_text.encode())
    return digest.hexdigest()[:16]


def slice_hash(
    repo_root: Path,
    files: Iterable[Path],
    requirements_text: str,
    dockerfile_text: str,
    base: BaseRef,
) -> str:
    """Content identity of everything that goes into a service image."""
    root = repo_root.resolve()
    digest = hashlib.sha256()
    for path in sorted(Path(f).resolve() for f in files):
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    digest.update(requirements_text.encode())
    digest.update(dockerfile_text.encode())
    digest.update(base.digest.encode())
    return digest.hexdigest()


def read_slice_label(tag: str) -> str | None:
    """Read the slice hash stamped on a built image, locally then from a registry."""
    fmt = f'{{{{index .Config.Labels "{SLICE_LABEL}"}}}}'
    local = run_docker(["image", "inspect", tag, "--format", fmt])
    if local.returncode == 0:
        return local.stdout.strip() or None

    # The local image is gone, which is the normal state on a fresh CI runner.
    # This is why the hash lives on the image rather than in .build/.
    remote = run_docker(
        ["buildx", "imagetools", "inspect", tag, "--format", "{{json .Image}}"], timeout=60
    )
    if remote.returncode != 0:
        return None
    try:
        payload = json.loads(remote.stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        labels = (payload.get("config") or {}).get("Labels") or {}
        return labels.get(SLICE_LABEL)
    return None
