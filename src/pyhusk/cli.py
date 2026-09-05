from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml

from pyhusk.config import CONFIG_NAME, autodetect_services, load_config
from pyhusk.errors import PyhuskError

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
