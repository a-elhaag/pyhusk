from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from pyhusk.errors import PyhuskError

CONFIG_NAME = "pyhusk.yaml"

# Directories never scanned during auto-detection. Scanning .venv would find
# third-party example apps; scanning .build would find slices pyhusk itself wrote
# on a previous run and register them as new services.
SKIP_DIRS = {".venv", ".build", "node_modules", "__pycache__", "site-packages"}


class ServiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry: Path
    app: str = "app"
    base_image: str = "python:3.12-slim"
    port: int = 8000
    registry: str | None = None
    factory: bool = False
    healthcheck: str | None = None
    include: list[str] = []
    env: dict[str, str] = {}
    forbid_imports: list[str] = []
    kind: str = "fastapi"
    command: list[str] | None = None

    def module_path(self, repo_root: Path) -> str:
        """Dotted module path of the entry file, for the uvicorn target."""
        relative = self.entry.relative_to(repo_root).with_suffix("")
        return ".".join(relative.parts)


class PyhuskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    services: dict[str, ServiceConfig]
    isolate_services: bool = True


def _is_skipped(path: Path, repo_root: Path) -> bool:
    parts = path.relative_to(repo_root).parts
    return any(part in SKIP_DIRS or part.startswith(".") for part in parts)


def expand_includes(repo_root: Path, patterns: list[str | Path]) -> list[Path]:
    """Expand files, directories, and glob patterns within the repository."""
    root = repo_root.resolve()
    found: set[Path] = set()
    for item in patterns:
        item_str = str(item)
        if any(c in item_str for c in ("*", "?", "[")):
            for match in root.glob(item_str):
                res = match.resolve()
                if res.is_file() and res.is_relative_to(root) and not _is_skipped(res, root):
                    found.add(res)
        else:
            res = (root / item).resolve()
            if not res.exists():
                raise PyhuskError(f"Include path does not exist: {item}")
            try:
                res.relative_to(root)
            except ValueError:
                raise PyhuskError(f"Include path escapes repository root: {item}")
            if res.is_dir():
                for sub in sorted(res.rglob("*")):
                    if sub.is_file() and not _is_skipped(sub, root):
                        found.add(sub.resolve())
            elif res.is_file():
                found.add(res)
    return sorted(found)


def autodetect_services(repo_root: Path) -> dict[str, ServiceConfig]:
    """Find `main.py` files that instantiate FastAPI, named after their directory.

    Deliberately a text search rather than an AST parse: a file that fails to
    parse should be skipped quietly here, not crash detection. The build stage
    is where a broken service must fail loudly.
    """
    detected: dict[str, ServiceConfig] = {}
    for candidate in sorted(repo_root.rglob("main.py")):
        if _is_skipped(candidate, repo_root):
            continue
        try:
            source = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "FastAPI(" not in source:
            continue
        name = candidate.parent.name
        if name in detected:
            raise PyhuskError(
                f"Auto-detection found two services named {name!r}: "
                f"{detected[name].entry} and {candidate}. "
                f"Write a {CONFIG_NAME} to name them explicitly."
            )
        detected[name] = ServiceConfig(entry=candidate)
    return detected


def load_config(repo_root: Path) -> PyhuskConfig:
    """Load pyhusk.yaml, or auto-detect services when it is absent."""
    config_path = repo_root / CONFIG_NAME
    if not config_path.exists():
        detected = autodetect_services(repo_root)
        if not detected:
            raise PyhuskError(
                f"No {CONFIG_NAME} found under {repo_root} and auto-detection found "
                f"no main.py containing a FastAPI() call. Run `pyhusk init` or write "
                f"{CONFIG_NAME} by hand."
            )
        return PyhuskConfig(services=detected)

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PyhuskError(f"{config_path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise PyhuskError(f"{config_path} must contain a mapping with a 'services' key.")

    try:
        config = PyhuskConfig.model_validate(raw)
    except ValidationError as exc:
        raise PyhuskError(f"{config_path} is invalid:\n{exc}") from exc

    root = repo_root.resolve()
    for name, service in config.services.items():
        service.entry = (repo_root / service.entry).resolve()
        try:
            service.entry.relative_to(root)
        except ValueError:
            raise PyhuskError(
                f"Service {name!r} has entry {service.entry}, which is outside the "
                f"repository root {repo_root}."
            ) from None
        if not service.entry.is_file():
            raise PyhuskError(
                f"Service {name!r} points at {service.entry.relative_to(root)}, "
                f"which does not exist."
            )
    return config
