from __future__ import annotations

import ast
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

STDLIB = set(sys.stdlib_module_names)


@dataclass(frozen=True)
class Unresolved:
    module: str
    file: Path
    lineno: int


@dataclass
class SliceResult:
    files: set[Path] = field(default_factory=set)
    third_party: set[str] = field(default_factory=set)
    unresolved: list[Unresolved] = field(default_factory=list)
    unparseable: list[Path] = field(default_factory=list)


def _module_file(repo_root: Path, dotted: str) -> Path | None:
    """Resolve a dotted module name to a file inside the repository."""
    parts = dotted.split(".")
    base = repo_root.joinpath(*parts)
    package_init = base / "__init__.py"
    if package_init.is_file():
        return package_init
    module = base.with_suffix(".py")
    if module.is_file():
        return module
    return None


def _package_inits(repo_root: Path, dotted: str) -> list[Path]:
    """Every parent package __init__.py along a dotted path.

    Importing common.models executes common/__init__.py, so an image without it
    fails at startup even though nothing imports it by name.
    """
    parts = dotted.split(".")
    found = []
    for depth in range(1, len(parts)):
        init = repo_root.joinpath(*parts[:depth], "__init__.py")
        if init.is_file():
            found.append(init)
    return found


def _relative_target(repo_root: Path, source: Path, level: int, module: str | None) -> str | None:
    """Turn a relative import into an absolute dotted name, or None if it escapes."""
    package_dir = source.parent
    for _ in range(level - 1):
        package_dir = package_dir.parent
    try:
        relative = package_dir.relative_to(repo_root)
    except ValueError:
        return None
    parts = [part for part in relative.parts if part]
    if module:
        parts.extend(module.split("."))
    return ".".join(parts) if parts else None


def _record(repo_root: Path, dotted: str, result: SliceResult, queue: list[Path]) -> bool:
    """Add a resolved local module and its package inits. True if it was local."""
    target = _module_file(repo_root, dotted)
    if target is None:
        return False
    for path in [*_package_inits(repo_root, dotted), target]:
        if path not in result.files:
            result.files.add(path)
            queue.append(path)
    return True


def _handle_import(
    node: ast.Import, repo_root: Path, result: SliceResult, queue: list[Path]
) -> None:
    for alias in node.names:
        if _record(repo_root, alias.name, result, queue):
            continue
        top = alias.name.split(".")[0]
        if top not in STDLIB:
            result.third_party.add(top)


def _handle_import_from(
    node: ast.ImportFrom, repo_root: Path, source: Path, result: SliceResult, queue: list[Path]
) -> None:
    if node.level:
        dotted = _relative_target(repo_root, source, node.level, node.module)
        if dotted is None:
            result.unresolved.append(
                Unresolved(
                    module="." * node.level + (node.module or ""),
                    file=source,
                    lineno=node.lineno,
                )
            )
            return
    else:
        dotted = node.module or ""
        if not dotted:
            return

    local = _record(repo_root, dotted, result, queue)

    # `from package import submodule` imports a module, not an attribute, so each
    # name has to be tried as a submodule too.
    for alias in node.names:
        if alias.name == "*":
            continue
        _record(repo_root, f"{dotted}.{alias.name}", result, queue)

    if local:
        return
    if node.level:
        result.unresolved.append(
            Unresolved(
                module="." * node.level + (node.module or ""),
                file=source,
                lineno=node.lineno,
            )
        )
        return
    top = dotted.split(".")[0]
    if top not in STDLIB:
        result.third_party.add(top)


def build_slice(
    repo_root: Path,
    seeds: Iterable[Path],
    includes: Iterable[Path] = (),
) -> SliceResult:
    """Expand seed files to the full local slice by walking imports to a fixed point.

    Includes are walked like any other file rather than merely copied, so
    force-including a dynamically loaded plugin also pulls in what that plugin
    imports.
    """
    repo_root = repo_root.resolve()
    result = SliceResult()
    queue: list[Path] = []

    for seed in [*seeds, *includes]:
        resolved = seed.resolve()
        if resolved not in result.files:
            result.files.add(resolved)
            queue.append(resolved)

    while queue:
        source = queue.pop()
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (SyntaxError, UnicodeDecodeError, OSError):
            result.unparseable.append(source)
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                _handle_import(node, repo_root, result, queue)
            elif isinstance(node, ast.ImportFrom):
                _handle_import_from(node, repo_root, source, result, queue)

    return result
