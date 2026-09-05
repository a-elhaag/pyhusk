from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pyhusk.docker import run_docker

SLICE_LABEL = "org.pyhusk.slice"

# How long a cached base digest is trusted before the registry is asked again.
# Every plan and build used to query the registry per base image, which burns
# Docker Hub's anonymous quota (HTTP 429) in a busy dev loop or CI. One query
# per hour per base is plenty: base tags move on the order of days.
DIGEST_TTL_SECONDS = 3600

_MEMO: dict[str, "BaseRef"] = {}


@dataclass(frozen=True)
class BaseRef:
    reference: str
    digest: str
    verified: bool
    # Where the digest came from: "registry", "local", "cache", or "tag".
    source: str = "registry"

    @property
    def pinned(self) -> str:
        """The reference to write into a FROM line."""
        if self.verified and "@" not in self.reference:
            return f"{self.reference}@{self.digest}"
        return self.reference


def _docker_stdout(args: list[str], timeout: int) -> str | None:
    """stdout of a docker command, or None on failure or timeout."""
    try:
        completed = run_docker(args, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _read_cache(cache: Path | None) -> dict[str, dict[str, object]]:
    if cache is None or not cache.exists():
        return {}
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(cache: Path | None, reference: str, digest: str) -> None:
    if cache is None:
        return
    data = _read_cache(cache)
    data[reference] = {"digest": digest, "at": time.time()}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass  # a cache that cannot be written is only a slower cache


def resolve_base(reference: str, cache: Path | None = None) -> BaseRef:
    """Resolve a base image tag to its content digest.

    Base tags are mutable. python:3.12-slim moves on every patch release,
    including security patches, so without the digest an unchanged Dockerfile
    hashes the same and pyhusk reports a service as fresh while its image sits on
    a superseded base.

    Resolution order, and why:

    1. A cache entry younger than DIGEST_TTL_SECONDS. Skips the registry
       entirely, which is what keeps a dev loop under Docker Hub's rate limit.
    2. The registry manifest, via buildx. The authoritative answer.
    3. The classic local image store. Rarely helps in practice, because BuildKit
       keeps pulled bases in its own cache rather than the image store, but it is
       cheap and correct when a user has pulled the tag by hand.
    4. Any cache entry, however old. A registry blip must not restale every
       service: a stale digest is still a real digest, and the hash stays put.
    5. The tag string itself, flagged unverified. Last resort, and loud.

    Memoized per reference for the life of the process, so a ten-service repo
    on one base resolves once.
    """
    if reference in _MEMO:
        return _MEMO[reference]

    def done(digest: str, verified: bool, source: str) -> BaseRef:
        result = BaseRef(reference=reference, digest=digest, verified=verified, source=source)
        _MEMO[reference] = result
        return result

    cached = _read_cache(cache).get(reference)
    if isinstance(cached, dict) and isinstance(cached.get("digest"), str):
        age = time.time() - float(cached.get("at") or 0)
        if 0 <= age < DIGEST_TTL_SECONDS:
            return done(cached["digest"], True, "cache")

    remote = _docker_stdout(
        ["buildx", "imagetools", "inspect", reference, "--format", "{{.Manifest.Digest}}"], 60
    )
    if remote:
        _write_cache(cache, reference, remote)
        return done(remote, True, "registry")

    local = _docker_stdout(
        ["image", "inspect", reference, "--format", "{{index .RepoDigests 0}}"], 30
    )
    if local and "@" in local:
        digest = local.split("@", 1)[1]
        _write_cache(cache, reference, digest)
        return done(digest, True, "local")

    if isinstance(cached, dict) and isinstance(cached.get("digest"), str):
        return done(cached["digest"], True, "stale-cache")

    return done(reference, False, "tag")


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
    remote = _docker_stdout(
        ["buildx", "imagetools", "inspect", tag, "--format", "{{json .Image}}"], 60
    )
    if remote is None:
        return None
    try:
        payload = json.loads(remote)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        labels = (payload.get("config") or {}).get("Labels") or {}
        return labels.get(SLICE_LABEL)
    return None
