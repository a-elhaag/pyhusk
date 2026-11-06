from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer
import yaml

from pyhusk.affected import affected_services, affected_tests
from pyhusk.benchmark import format_markdown_table, run_service_benchmark
from pyhusk.config import (
    CONFIG_NAME,
    SKIP_DIRS,
    PyhuskConfig,
    ServiceConfig,
    autodetect_services,
    expand_includes,
    load_config,
)
from pyhusk.deps import RequirementsResult, all_requirements
from pyhusk.discover import venv_python
from pyhusk.docker import image_exists, image_size, require_docker, run_docker
from pyhusk.dockerize import assemble_context, render_base_dockerfile, render_dockerfile
from pyhusk.errors import PyhuskError
from pyhusk.git import (
    changed_files_since,
    commit_history_for_files,
    head_commit,
    last_commit_for_files,
)
from pyhusk.graph import trace_why
from pyhusk.lint import LintIssue, lint_service
from pyhusk.pipeline import Resolution, is_stale, resolve
from pyhusk.report import count_python_files, human_size
from pyhusk.staleness import COMMIT_LABEL, SLICE_LABEL
from pyhusk.verify import verify

app = typer.Typer(
    add_completion=False,
    help="Minimal Docker images, architecture linting, and CI intelligence for Python monorepos.",
    no_args_is_help=True,
)

RepoOption = Annotated[
    Path,
    typer.Option("--repo", help="Repository root. Defaults to the current directory."),
]


def _fail(message: str) -> None:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


SKILL_CONTENT = """---
name: pyhusk
description: Minimal Docker image building, architecture linting, import tracing, and selective CI testing for FastAPI monorepos. Use whenever analyzing, building, linting, testing, or checking dependencies in a pyhusk-managed monorepo.
---

# pyhusk

Tool for FastAPI monorepos: builds minimal, pruned Docker images, lints architecture boundaries, traces import lineage, and runs selective CI tests based on git diffs.

## Quick Reference

| Command | Purpose |
|---|---|
| `pyhusk lint [services...]` | Verify boundaries, circular imports, and `forbid_imports`. |
| `pyhusk plan [--json]` | Identify stale services requiring Docker builds. |
| `pyhusk why <service> <target>` | Trace shortest BFS import chain from entry to file or package. |
| `pyhusk affected [--since REF]` | Show services and test files touched since git ref. |
| `pyhusk test [--since REF]` | Run `pytest` only on test files affected by changes. |
| `pyhusk unused` | Find unreferenced Python files across the monorepo. |
| `pyhusk build [services...]` | Build pruned Docker images and verify via OpenAPI/healthcheck. |
| `pyhusk log <service>` | Display git commit history affecting a service's slice. |
"""


def _install_skill(repo: Path) -> None:
    """Install agent skill into .agents/skills/pyhusk and .claude/skills/pyhusk."""
    agents_dir = repo / ".agents" / "skills" / "pyhusk"
    claude_dir = repo / ".claude" / "skills" / "pyhusk"
    agents_dir.mkdir(parents=True, exist_ok=True)
    claude_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "SKILL.md").write_text(SKILL_CONTENT, encoding="utf-8")
    (claude_dir / "SKILL.md").write_text(SKILL_CONTENT, encoding="utf-8")
    typer.echo("installed agent skill into .agents/skills/pyhusk/ and .claude/skills/pyhusk/")


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
def init(
    repo: RepoOption = Path("."),
    no_skill: Annotated[bool, typer.Option("--no-skill", help="Skip agent skill installation.")] = False,
) -> None:
    """Write pyhusk.yaml from detected services, ignore build dir, and install agent skill."""
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
    if not no_skill:
        _install_skill(repo)


@app.command("skill")
def install_skill_command(repo: RepoOption = Path(".")) -> None:
    """Install or update the pyhusk agent skill in the current workspace."""
    repo = repo.resolve()
    _install_skill(repo)


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
    typer.Option("--include", help="Force a path or directory into the slice. Repeatable."),
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
        f"{resolution.name}: pruned {human_size(pruned)} vs naive {human_size(naive)} "
        f"compressed  saved {human_size(saved)} ({saved / naive:.0%})"
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
    try:
        includes = expand_includes(repo, include or [])
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

    total_repo_files = count_python_files(repo)
    failures: list[str] = []
    for name, resolution in sorted(pending.items()):
        typer.echo(f"{name}: building")
        build_args = [
            "build",
            "-t",
            resolution.tag,
            "--label",
            f"{SLICE_LABEL}={resolution.slice_hash}",
        ]
        last = last_commit_for_files(repo, resolution.files)
        if last and last[0]:
            build_args.extend(["--label", f"{COMMIT_LABEL}={last[0]}"])
        build_args.append(str(repo / ".build" / name))

        built = run_docker(build_args, capture_output=False)
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
                run_docker(["rmi", "-f", resolution.tag])
                typer.secho(
                    f"{name}: removed {resolution.tag}; the next build will retry",
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
            f"{human_size(image_size(resolution.tag))} compressed"
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
    try:
        includes = expand_includes(repo, include or [])
        config = load_config(repo)
    except PyhuskError as exc:
        _fail(str(exc))

    resolutions = _resolve_all(repo, _selected(config, service), includes, not no_shared_base)
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


@app.command()
def why(
    service: Annotated[str, typer.Argument(help="Service name to trace.")],
    target: Annotated[str, typer.Argument(help="File path or package name to trace.")],
    repo: RepoOption = Path("."),
) -> None:
    """Show the shortest import path from a service entry to a file or package."""
    repo = repo.resolve()
    try:
        config = load_config(repo)
    except PyhuskError as exc:
        _fail(str(exc))
    if service not in config.services:
        _fail(f"unknown service {service!r}. Known: {', '.join(sorted(config.services))}")

    res = resolve(repo, service, config.services[service])
    if res.sliced is None:
        _fail("slice could not be resolved")

    chain = trace_why(repo, [res.service.entry], res.sliced.edges, target)
    if chain is None:
        _fail(f"{target!r} is not reached by service {service!r}")

    typer.echo(f"{service} reaches {target}:")
    for edge in chain:
        src = edge.source.relative_to(repo)
        tgt = edge.target.relative_to(repo) if isinstance(edge.target, Path) else edge.target
        typer.echo(f"  {src}:{edge.lineno} -> {tgt} ({edge.kind})")


@app.command()
def unused(
    repo: RepoOption = Path("."),
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Find Python files in the monorepo not used by any service."""
    repo = repo.resolve()
    try:
        config = load_config(repo)
    except PyhuskError as exc:
        _fail(str(exc))

    resolutions = _resolve_all(repo, config.services, [], False)
    used_files: set[Path] = set()
    for res in resolutions.values():
        used_files.update(res.files)

    all_py: list[Path] = []
    for p in repo.rglob("*.py"):
        parts = p.relative_to(repo).parts
        if any(part in SKIP_DIRS or part.startswith(".") for part in parts):
            continue
        all_py.append(p.resolve())

    unused_files = sorted(
        f for f in all_py if f not in used_files and not f.name.startswith("test_")
    )

    if as_json:
        typer.echo(
            json.dumps(
                {"unused_files": [str(f.relative_to(repo)) for f in unused_files]},
                indent=2,
            )
        )
        return

    if unused_files:
        typer.echo(f"Found {len(unused_files)} unreferenced Python file(s):")
        for f in unused_files:
            typer.echo(f"  {f.relative_to(repo)}")
    else:
        typer.echo("All local Python files are referenced by at least one service.")


@app.command()
def lint(
    service: Annotated[
        list[str] | None, typer.Argument(help="Services to lint. Default: all.")
    ] = None,
    repo: RepoOption = Path("."),
    strict: Annotated[bool, typer.Option("--strict", help="Treat warnings as errors.")] = False,
    no_ruff: Annotated[bool, typer.Option("--no-ruff", help="Skip ruff check.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Output results as JSON.")] = False,
) -> None:
    """Lint monorepo architecture, boundaries, circular imports, and code quality."""
    repo = repo.resolve()
    try:
        config = load_config(repo)
    except PyhuskError as exc:
        _fail(str(exc))

    resolutions = _resolve_all(repo, _selected(config, service), [], False)
    all_issues: list[LintIssue] = []

    for name, res in sorted(resolutions.items()):
        issues = lint_service(repo, name, res, config, strict=strict, run_ruff=not no_ruff)
        all_issues.extend(issues)

    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "service": iss.service,
                        "code": iss.code,
                        "severity": iss.severity,
                        "message": iss.message,
                        "detail": iss.detail,
                    }
                    for iss in all_issues
                ],
                indent=2,
            )
        )
        if any(i.severity == "error" for i in all_issues):
            raise typer.Exit(code=1)
        return

    if not all_issues:
        typer.secho("lint passed: no architectural or code quality issues found.", fg=typer.colors.GREEN)
        return

    for iss in all_issues:
        color = typer.colors.RED if iss.severity == "error" else typer.colors.YELLOW
        typer.secho(f"[{iss.severity.upper()}] {iss.service} ({iss.code}): {iss.message}", fg=color)
        if iss.detail:
            typer.echo(iss.detail)

    error_count = sum(1 for i in all_issues if i.severity == "error")
    warning_count = sum(1 for i in all_issues if i.severity == "warning")
    summary = f"{error_count} error(s), {warning_count} warning(s)"
    if error_count > 0:
        typer.secho(f"lint failed with {summary}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    else:
        typer.secho(f"lint passed with {summary}", fg=typer.colors.YELLOW)


@app.command()
def log(
    service: Annotated[str, typer.Argument(help="Service name to inspect.")],
    repo: RepoOption = Path("."),
    limit: Annotated[int, typer.Option("-n", "--limit", help="Number of commits.")] = 10,
) -> None:
    """Show git commit history for a service's slice."""
    repo = repo.resolve()
    try:
        config = load_config(repo)
    except PyhuskError as exc:
        _fail(str(exc))
    if service not in config.services:
        _fail(f"unknown service {service!r}. Known: {', '.join(sorted(config.services))}")

    res = resolve(repo, service, config.services[service])
    history = commit_history_for_files(repo, res.files, limit=limit)
    if not history:
        typer.echo(f"No git history found for service {service!r}.")
        return

    typer.echo(f"Recent commits touching slice for {service}:")
    for item in history:
        typer.echo(f"  {item['commit']}  {item['date']}  {item['author']}  {item['message']}")


@app.command()
def affected(
    repo: RepoOption = Path("."),
    since: Annotated[str, typer.Option("--since", help="Git ref to diff against.")] = "HEAD~1",
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Show services and test files affected by changes since a git ref."""
    repo = repo.resolve()
    try:
        config = load_config(repo)
    except PyhuskError as exc:
        _fail(str(exc))

    changed = changed_files_since(repo, since)
    resolutions = _resolve_all(repo, config.services, [], False)
    aff_services = affected_services(repo, resolutions, changed)
    aff_tests = affected_tests(repo, changed)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "since": since,
                    "changed_files": [str(f.relative_to(repo)) for f in sorted(changed)],
                    "affected_services": aff_services,
                    "affected_tests": [str(t.relative_to(repo)) for t in aff_tests],
                },
                indent=2,
            )
        )
        return

    typer.echo(f"Changes since {since} ({len(changed)} file(s)):")
    typer.echo(f"Affected services ({len(aff_services)}): " + (", ".join(aff_services) or "none"))
    typer.echo(f"Affected test files ({len(aff_tests)}):")
    for t in aff_tests:
        typer.echo(f"  {t.relative_to(repo)}")


@app.command()
def test(
    repo: RepoOption = Path("."),
    since: Annotated[str, typer.Option("--since", help="Git ref to diff against.")] = "HEAD~1",
    all_tests: Annotated[
        bool, typer.Option("--all", help="Run all tests if none affected.")
    ] = False,
) -> None:
    """Run pytest only on test files affected by changes since a git ref."""
    repo = repo.resolve()
    changed = changed_files_since(repo, since)
    aff_tests = affected_tests(repo, changed)

    python = venv_python(repo)

    if not aff_tests:
        if all_tests:
            typer.echo(f"No tests affected since {since}. Running all tests (--all)...")
            cmd = [str(python), "-m", "pytest"]
            res = subprocess.run(cmd, cwd=repo)
            raise typer.Exit(code=res.returncode)
        typer.echo(f"No tests affected since {since}.")
        return

    typer.echo(f"Running {len(aff_tests)} affected test file(s) since {since}:")
    for t in aff_tests:
        typer.echo(f"  {t.relative_to(repo)}")

    cmd = [str(python), "-m", "pytest", *[str(t) for t in aff_tests]]
    res = subprocess.run(cmd, cwd=repo)
    raise typer.Exit(code=res.returncode)


@app.command()
def benchmark(
    service: Annotated[
        list[str] | None, typer.Argument(help="Services to benchmark. Default: all.")
    ] = None,
    repo: RepoOption = Path("."),
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Do not use Docker cache for measurement.")
    ] = True,
    markdown: Annotated[
        bool, typer.Option("--markdown", help="Format output as a Markdown table.")
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Output results as JSON.")
    ] = False,
) -> None:
    """Benchmark build time and image size against a whole-repo baseline."""
    repo = repo.resolve()
    try:
        require_docker()
        config = load_config(repo)
    except PyhuskError as exc:
        _fail(str(exc))

    resolutions = _resolve_all(repo, _selected(config, service), [], False)
    _print_warnings(resolutions)

    benchmarks = []
    for name, resolution in sorted(resolutions.items()):
        typer.echo(f"benchmarking {name} (pruned vs naive whole-repo)...")
        try:
            b = run_service_benchmark(repo, resolution, no_cache=no_cache)
            benchmarks.append(b)
        except Exception as exc:
            _fail(str(exc))

    if as_json:
        typer.echo(json.dumps([b.to_dict() for b in benchmarks], indent=2))
        return

    if markdown:
        typer.echo(format_markdown_table(benchmarks))
        return

    typer.echo("\nBenchmark Results:")
    for b in benchmarks:
        typer.secho(f"\n{b.name}:", fg=typer.colors.CYAN, bold=True)
        typer.echo(
            f"  Build time:  {b.pruned_time_s:.1f}s (pruned) vs {b.naive_time_s:.1f}s (naive) "
            f"-> saved {b.time_saved_s:.1f}s ({b.time_saved_pct:.0%})"
        )
        typer.echo(
            f"  Image size:  {human_size(b.pruned_size_bytes)} vs {human_size(b.naive_size_bytes)} "
            f"-> saved {human_size(b.size_saved_bytes)} ({b.size_saved_pct:.0%})"
        )
        typer.echo(
            f"  Packages:    {b.pruned_packages} pins vs {b.naive_packages} pins in lockfile"
        )
        typer.echo(
            f"  Files:       {b.pruned_files} files vs {b.total_files} in repo"
        )
