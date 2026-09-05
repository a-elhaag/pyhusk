from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated

import typer
import yaml

from pyhusk.config import (
    CONFIG_NAME,
    PyhuskConfig,
    ServiceConfig,
    autodetect_services,
    load_config,
)
from pyhusk.deps import RequirementsResult, all_requirements
from pyhusk.docker import image_exists, image_size, require_docker, run_docker
from pyhusk.dockerize import assemble_context, render_base_dockerfile, render_dockerfile
from pyhusk.errors import PyhuskError
from pyhusk.pipeline import Resolution, is_stale, resolve
from pyhusk.report import human_size
from pyhusk.staleness import SLICE_LABEL
from pyhusk.verify import verify

app = typer.Typer(
    add_completion=False,
    help="Minimal Docker images for FastAPI monorepos.",
    no_args_is_help=True,
)

RepoOption = Annotated[
    Path,
    typer.Option("--repo", help="Repository root. Defaults to the current directory."),
]


def _fail(message: str) -> None:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _ensure_gitignored(repo: Path) -> None:
    """Add .build/ to .gitignore exactly once."""
    gitignore = repo / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(".build/\n", encoding="utf-8")
        typer.echo("created .gitignore with .build/")
        return
    existing = gitignore.read_text(encoding="utf-8")
    if any(line.strip() in {".build", ".build/"} for line in existing.splitlines()):
        return
    separator = "" if existing.endswith("\n") or not existing else "\n"
    gitignore.write_text(f"{existing}{separator}.build/\n", encoding="utf-8")
    typer.echo("added .build/ to .gitignore")


@app.command()
def init(repo: RepoOption = Path(".")) -> None:
    """Write pyhusk.yaml from detected services and ignore the build directory."""
    repo = repo.resolve()
    config_path = repo / CONFIG_NAME

    if config_path.exists():
        typer.echo(f"{CONFIG_NAME} already exists, leaving it untouched.")
    else:
        try:
            detected = autodetect_services(repo)
        except PyhuskError as exc:
            _fail(str(exc))
        if not detected:
            _fail(
                "No main.py containing a FastAPI() call was found. Create your services "
                f"first, or write {CONFIG_NAME} by hand."
            )
        document = {
            "services": {
                name: {
                    "entry": str(service.entry.relative_to(repo)),
                    "app": service.app,
                }
                for name, service in sorted(detected.items())
            }
        }
        config_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        typer.echo(
            f"wrote {CONFIG_NAME} with {len(detected)} service(s): "
            f"{', '.join(sorted(detected))}"
        )

    _ensure_gitignored(repo)


@app.command("list")
def list_services(repo: RepoOption = Path(".")) -> None:
    """List the services pyhusk can see."""
    repo = repo.resolve()
    try:
        config = load_config(repo)
    except PyhuskError as exc:
        _fail(str(exc))
    for name, service in sorted(config.services.items()):
        relative = service.entry.relative_to(repo)
        suffix = "()" if service.factory else ""
        typer.echo(f"{name}\t{relative}\t{service.app}{suffix}")


IncludeOption = Annotated[
    list[Path] | None,
    typer.Option("--include", help="Force a path into the slice. Repeatable."),
]


def _selected(config: PyhuskConfig, names: list[str] | None) -> dict[str, ServiceConfig]:
    if not names:
        return dict(config.services)
    unknown = [name for name in names if name not in config.services]
    if unknown:
        _fail(
            f"unknown service(s): {', '.join(unknown)}. "
            f"Known: {', '.join(sorted(config.services))}"
        )
    return {name: config.services[name] for name in names}


def _resolve_all(
    repo: Path,
    services: dict[str, ServiceConfig],
    includes: list[Path],
    shared_base: bool,
) -> dict[str, Resolution]:
    resolutions: dict[str, Resolution] = {}
    for name, service in sorted(services.items()):
        try:
            resolutions[name] = resolve(repo, name, service, includes, shared_base)
        except PyhuskError as exc:
            _fail(f"{name}: {exc}")
    return resolutions


def _print_warnings(resolutions: dict[str, Resolution]) -> None:
    for name, resolution in sorted(resolutions.items()):
        for warning in resolution.warnings:
            typer.secho(f"warning: {name}: {warning}", fg=typer.colors.YELLOW, err=True)


def _build_bases(repo: Path, resolutions: dict[str, Resolution]) -> None:
    """Build every shared base image the given resolutions need, once each.

    Separate from service builds because `pyhusk plan --json` exists to fan out a
    CI matrix, and two runners building the same base tag concurrently race. A
    file lock cannot help across machines that share no filesystem, so CI runs
    this as one job that the matrix depends on.
    """
    wanted: dict[str, RequirementsResult] = {}
    sources: dict[str, str] = {}
    for resolution in resolutions.values():
        if resolution.base_tag is None:
            continue
        wanted[resolution.base_tag] = resolution.requirements
        sources[resolution.base_tag] = resolution.base.pinned

    for tag, requirements in sorted(wanted.items()):
        if image_exists(tag):
            typer.echo(f"base {tag} already present")
            continue
        context = repo / ".build" / "_bases" / tag.split(":", 1)[1]
        if context.exists():
            shutil.rmtree(context)
        context.mkdir(parents=True)
        (context / "requirements.txt").write_text(requirements.text, encoding="utf-8")
        (context / "Dockerfile").write_text(
            render_base_dockerfile(sources[tag]), encoding="utf-8"
        )
        typer.echo(f"building base {tag} ({len(requirements.pins)} packages)")
        if run_docker(["build", "-t", tag, str(context)], capture_output=False).returncode != 0:
            _fail(f"building base {tag} failed")


@app.command("build-bases")
def build_bases(
    service: Annotated[
        list[str] | None, typer.Argument(help="Limit to these services.")
    ] = None,
    repo: RepoOption = Path("."),
) -> None:
    """Build the shared base images the current plan requires."""
    repo = repo.resolve()
    try:
        require_docker()
        config = load_config(repo)
    except PyhuskError as exc:
        _fail(str(exc))
    _build_bases(repo, _resolve_all(repo, _selected(config, service), [], True))


def _compare_against_naive(repo: Path, resolution: Resolution) -> None:
    """Build a whole-repo image the naive way and report the difference.

    Doubles build time, so it is off by default. It exists so the size claim can
    be checked rather than asserted.
    """
    context = repo / ".build" / "_naive" / resolution.name
    if context.exists():
        shutil.rmtree(context)
    context.mkdir(parents=True)

    for source in repo.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(repo)
        if relative.parts and relative.parts[0] in {".build", ".venv", ".git"}:
            continue
        destination = context / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    (context / "requirements.txt").write_text(all_requirements(repo).text, encoding="utf-8")
    (context / "Dockerfile").write_text(
        render_dockerfile(repo, resolution.service, resolution.base.pinned, True),
        encoding="utf-8",
    )

    tag = f"{resolution.name}-naive:latest"
    typer.echo(f"{resolution.name}: building naive baseline for comparison")
    if run_docker(["build", "-t", tag, str(context)], capture_output=False).returncode != 0:
        typer.secho(
            f"warning: {resolution.name}: baseline build failed, no comparison",
            fg=typer.colors.YELLOW,
            err=True,
        )
        return

    pruned, naive = image_size(resolution.tag), image_size(tag)
    if not naive:
        return
    saved = naive - pruned
    typer.echo(
        f"{resolution.name}: pruned {human_size(pruned)} vs naive {human_size(naive)}  "
        f"saved {human_size(saved)} ({saved / naive:.0%})"
    )


@app.command()
def build(
    service: Annotated[
        list[str] | None, typer.Argument(help="Services to build. Default: all stale.")
    ] = None,
    repo: RepoOption = Path("."),
    include: IncludeOption = None,
    show_dockerfile: Annotated[
        bool, typer.Option("--show-dockerfile", help="Write the context and stop.")
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="Rebuild even when unchanged.")] = False,
    compare: Annotated[
        bool, typer.Option("--compare", help="Also build a whole-repo image and show the delta.")
    ] = False,
    no_verify: Annotated[
        bool, typer.Option("--no-verify", help="Skip container verification.")
    ] = False,
    no_shared_base: Annotated[
        bool, typer.Option("--no-shared-base", help="Produce self-contained images.")
    ] = False,
) -> None:
    """Build minimal images for the named services, or every stale service."""
    repo = repo.resolve()
    includes = [(repo / path).resolve() for path in (include or [])]
    for path in includes:
        if not path.exists():
            _fail(f"--include path does not exist: {path}")

    try:
        config = load_config(repo)
    except PyhuskError as exc:
        _fail(str(exc))

    resolutions = _resolve_all(repo, _selected(config, service), includes, not no_shared_base)
    _print_warnings(resolutions)

    for name, resolution in sorted(resolutions.items()):
        assemble_context(
            repo,
            name,
            resolution.service,
            resolution.files,
            resolution.requirements.text,
            resolution.dockerfile_text,
        )

    if show_dockerfile:
        for name in sorted(resolutions):
            typer.echo(f"{name}: wrote {(repo / '.build' / name).relative_to(repo)}/")
        return

    try:
        require_docker()
    except PyhuskError as exc:
        _fail(str(exc))

    pending = {
        name: resolution
        for name, resolution in resolutions.items()
        if force or is_stale(resolution)
    }
    for name in sorted(set(resolutions) - set(pending)):
        typer.echo(f"{name}: unchanged")
    if not pending:
        return

    _build_bases(repo, pending)

    total_repo_files = sum(1 for _ in repo.rglob("*.py"))
    failures: list[str] = []
    for name, resolution in sorted(pending.items()):
        typer.echo(f"{name}: building")
        built = run_docker(
            [
                "build",
                "-t",
                resolution.tag,
                "--label",
                f"{SLICE_LABEL}={resolution.slice_hash}",
                str(repo / ".build" / name),
            ],
            capture_output=False,
        )
        if built.returncode != 0:
            typer.secho(f"{name}: docker build failed", fg=typer.colors.RED, err=True)
            failures.append(name)
            continue

        if not no_verify:
            outcome = verify(
                resolution.tag, resolution.service, resolution.routes, resolution.openapi_url
            )
            if not outcome.ok:
                typer.secho(
                    f"{name}: verification failed ({outcome.tier})\n{outcome.detail}",
                    fg=typer.colors.RED,
                    err=True,
                )
                failures.append(name)
                continue
            if outcome.tier != "schema":
                typer.secho(
                    f"warning: {name}: degraded verification ({outcome.tier}) - {outcome.detail}",
                    fg=typer.colors.YELLOW,
                    err=True,
                )

        if resolution.remote_tag:
            run_docker(["tag", resolution.tag, resolution.remote_tag])

        typer.echo(
            f"{name}: built {resolution.tag}  "
            f"{len(resolution.files)}/{total_repo_files} files  "
            f"{len(resolution.requirements.pins)} packages  "
            f"{human_size(image_size(resolution.tag))}"
        )
        if compare:
            _compare_against_naive(repo, resolution)

    if failures:
        _fail(f"failed: {', '.join(sorted(failures))}")


@app.command()
def plan(
    service: Annotated[
        list[str] | None, typer.Argument(help="Limit to these services.")
    ] = None,
    repo: RepoOption = Path("."),
    as_json: Annotated[
        bool, typer.Option("--json", help="Machine-readable output for CI.")
    ] = False,
    include: IncludeOption = None,
    no_shared_base: Annotated[bool, typer.Option("--no-shared-base")] = False,
) -> None:
    """Report which services are stale, without building anything."""
    repo = repo.resolve()
    includes = [(repo / path).resolve() for path in (include or [])]
    try:
        config = load_config(repo)
    except PyhuskError as exc:
        _fail(str(exc))

    resolutions = _resolve_all(repo, _selected(config, service), includes, not no_shared_base)
    # Warnings go to stderr so `--json` stdout stays a clean document; a CI job
    # pipes this straight into a matrix definition.
    _print_warnings(resolutions)

    entries: list[dict[str, object]] = []
    bases: dict[str, int] = {}
    for name, resolution in sorted(resolutions.items()):
        stale = is_stale(resolution)
        entries.append(
            {
                "name": name,
                "tag": resolution.tag,
                "base": resolution.base_tag,
                "hash": resolution.slice_hash,
                "stale": stale,
            }
        )
        if resolution.base_tag and stale:
            bases[resolution.base_tag] = len(resolution.requirements.pins)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "bases": [
                        {"tag": tag, "packages": count} for tag, count in sorted(bases.items())
                    ],
                    "services": entries,
                }
            )
        )
        return

    for entry in entries:
        typer.echo(f"{entry['name']}\t{'stale' if entry['stale'] else 'unchanged'}")
