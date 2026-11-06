from __future__ import annotations

import ast
import collections
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


@dataclass(frozen=True)
class Edge:
    source: Path
    target: Path | str
    lineno: int
    kind: str  # "import", "parent_init", "third_party", "include"


@dataclass
class SliceResult:
    files: set[Path] = field(default_factory=set)
    third_party: set[str] = field(default_factory=set)
    unresolved: list[Unresolved] = field(default_factory=list)
    unparseable: list[Path] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    cycles: list[list[Path]] = field(default_factory=list)


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
    """Every parent package __init__.py along a dotted path."""
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


def _record(
    repo_root: Path,
    source: Path,
    dotted: str,
    lineno: int,
    result: SliceResult,
    queue: collections.deque[Path],
) -> bool:
    """Add a resolved local module and its package inits. True if it was local."""
    target = _module_file(repo_root, dotted)
    if target is None:
        return False
    for path in _package_inits(repo_root, dotted):
        result.edges.append(Edge(source=source, target=path, lineno=lineno, kind="parent_init"))
        if path not in result.files:
            result.files.add(path)
            if path.suffix == ".py":
                queue.append(path)
    result.edges.append(Edge(source=source, target=target, lineno=lineno, kind="import"))
    if target not in result.files:
        result.files.add(target)
        if target.suffix == ".py":
            queue.append(target)
    return True


def _handle_import(
    node: ast.Import,
    repo_root: Path,
    source: Path,
    result: SliceResult,
    queue: collections.deque[Path],
) -> None:
    for alias in node.names:
        if _record(repo_root, source, alias.name, node.lineno, result, queue):
            continue
        top = alias.name.split(".")[0]
        if top not in STDLIB:
            result.third_party.add(top)
            result.edges.append(Edge(source=source, target=top, lineno=node.lineno, kind="third_party"))


def _handle_import_from(
    node: ast.ImportFrom,
    repo_root: Path,
    source: Path,
    result: SliceResult,
    queue: collections.deque[Path],
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

    local = _record(repo_root, source, dotted, node.lineno, result, queue)

    for alias in node.names:
        if alias.name == "*":
            continue
        _record(repo_root, source, f"{dotted}.{alias.name}", node.lineno, result, queue)

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
        result.edges.append(Edge(source=source, target=top, lineno=node.lineno, kind="third_party"))


def find_cycles(edges: list[Edge]) -> list[list[Path]]:
    """Detect circular imports among local files."""
    graph: dict[Path, list[Path]] = collections.defaultdict(list)
    for edge in edges:
        if isinstance(edge.target, Path) and edge.kind != "parent_init":
            graph[edge.source].append(edge.target)

    cycles: list[list[Path]] = []
    visited: set[Path] = set()
    rec_stack: list[Path] = []
    rec_set: set[Path] = set()
    seen: set[frozenset[Path]] = set()

    def dfs(node: Path) -> None:
        visited.add(node)
        rec_stack.append(node)
        rec_set.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_set:
                idx = rec_stack.index(neighbor)
                cycle = rec_stack[idx:] + [neighbor]
                key = frozenset(cycle)
                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
        rec_stack.pop()
        rec_set.remove(node)

    for node in sorted(graph.keys()):
        if node not in visited:
            dfs(node)
    return cycles


def build_slice(
    repo_root: Path,
    seeds: Iterable[Path],
    includes: Iterable[Path] = (),
) -> SliceResult:
    """Expand seed files to the full local slice by walking imports in BFS order."""
    repo_root = repo_root.resolve()
    result = SliceResult()
    queue: collections.deque[Path] = collections.deque()

    for seed in seeds:
        resolved = seed.resolve()
        if resolved not in result.files:
            result.files.add(resolved)
            if resolved.suffix == ".py":
                queue.append(resolved)

    for inc in includes:
        resolved = inc.resolve()
        if resolved not in result.files:
            result.files.add(resolved)
            if resolved.suffix == ".py":
                queue.append(resolved)

    while queue:
        source = queue.popleft()
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (SyntaxError, UnicodeDecodeError, OSError):
            result.unparseable.append(source)
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                _handle_import(node, repo_root, source, result, queue)
            elif isinstance(node, ast.ImportFrom):
                _handle_import_from(node, repo_root, source, result, queue)

    result.cycles = find_cycles(result.edges)
    return result


def trace_why(
    repo_root: Path,
    seeds: Iterable[Path],
    edges: list[Edge],
    target: str | Path,
) -> list[Edge] | None:
    """Find the shortest edge sequence from any seed to target."""
    root = repo_root.resolve()
    target_str = str(target).strip()
    target_norm = target_str.lower().replace("_", "-")
    target_path = (root / target_str).resolve() if not isinstance(target, Path) else target.resolve()

    def matches(candidate: Path | str) -> bool:
        if isinstance(candidate, Path):
            if candidate == target_path:
                return True
            try:
                rel = str(candidate.relative_to(root))
                if rel == target_str or candidate.name == target_str:
                    return True
            except ValueError:
                pass
            return False
        candidate_norm = candidate.lower().replace("_", "-")
        return candidate_norm == target_norm or candidate == target_str

    adj: dict[Path | str, list[Edge]] = collections.defaultdict(list)
    for edge in edges:
        adj[edge.source].append(edge)

    queue: collections.deque[tuple[Path | str, list[Edge]]] = collections.deque()
    visited: set[Path | str] = set()

    for s in seeds:
        res = s.resolve()
        if matches(res):
            return []
        queue.append((res, []))
        visited.add(res)

    while queue:
        current, path = queue.popleft()
        for edge in adj.get(current, []):
            nxt = edge.target
            if matches(nxt):
                return path + [edge]
            if nxt not in visited:
                visited.add(nxt)
                queue.append((nxt, path + [edge]))

    return None
