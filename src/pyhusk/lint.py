from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pyhusk.config import PyhuskConfig
from pyhusk.discover import venv_python
from pyhusk.graph import Edge, trace_why
from pyhusk.pipeline import Resolution


@dataclass(frozen=True)
class LintIssue:
    service: str
    code: str  # "boundary", "forbidden", "cycle", "unresolved", "unparseable", "unmapped", "ruff"
    severity: str  # "error", "warning"
    message: str
    detail: str = ""


def _format_trace(repo_root: Path, trace: list[Edge] | None) -> str:
    if not trace:
        return ""
    root = repo_root.resolve()
    lines = []
    for edge in trace:
        src = edge.source.relative_to(root)
        tgt = edge.target.relative_to(root) if isinstance(edge.target, Path) else edge.target
        lines.append(f"  {src}:{edge.lineno} -> {tgt} ({edge.kind})")
    return "\n".join(lines)


def lint_service(
    repo_root: Path,
    name: str,
    resolution: Resolution,
    config: PyhuskConfig,
    strict: bool = False,
    run_ruff: bool = True,
) -> list[LintIssue]:
    """Run architectural, boundary, cycle, and code quality checks on a service."""
    root = repo_root.resolve()
    issues: list[LintIssue] = []
    sliced = resolution.sliced

    if sliced is None:
        return issues

    # 1. Cross-service boundary isolation
    if config.isolate_services:
        service_dir = resolution.service.entry.parent.resolve()
        for other_name, other_svc in config.services.items():
            if other_name == name:
                continue
            other_dir = other_svc.entry.parent.resolve()
            if other_dir == service_dir:
                continue  # co-located in the same directory
            for path in sorted(resolution.files):
                if path.is_relative_to(other_dir):
                    trace = trace_why(repo_root, [resolution.service.entry], sliced.edges, path)
                    issues.append(
                        LintIssue(
                            service=name,
                            code="boundary",
                            severity="error",
                            message=(
                                f"cross-service import: includes {path.relative_to(root)} "
                                f"from service {other_name!r}"
                            ),
                            detail=_format_trace(repo_root, trace),
                        )
                    )

    # 2. Explicit forbidden imports
    for forbidden in resolution.service.forbid_imports:
        norm = forbidden.lower().replace("_", "-")
        found = False
        for pkg in sliced.third_party:
            if pkg.lower().replace("_", "-") == norm or pkg == forbidden:
                found = True
                break
        if not found:
            for f in resolution.files:
                try:
                    rel_mod = f.relative_to(root).with_suffix("").parts
                    if ".".join(rel_mod) == forbidden or rel_mod[0] == forbidden:
                        found = True
                        break
                except ValueError:
                    pass
        if found:
            trace = trace_why(repo_root, [resolution.service.entry], sliced.edges, forbidden)
            issues.append(
                LintIssue(
                    service=name,
                    code="forbidden",
                    severity="error",
                    message=f"imports forbidden package/module {forbidden!r}",
                    detail=_format_trace(repo_root, trace),
                )
            )

    # 3. Circular imports
    cycle_severity = "error" if strict else "warning"
    for cycle in sliced.cycles:
        chain = " -> ".join(str(p.relative_to(root)) for p in cycle)
        issues.append(
            LintIssue(
                service=name,
                code="cycle",
                severity=cycle_severity,
                message=f"circular import: {chain}",
            )
        )

    # 4. Unresolved imports
    for item in sliced.unresolved:
        issues.append(
            LintIssue(
                service=name,
                code="unresolved",
                severity="error",
                message=f"unresolved import {item.module!r} at {item.file.relative_to(root)}:{item.lineno}",
            )
        )

    # 5. Unparseable files
    for p in sliced.unparseable:
        issues.append(
            LintIssue(
                service=name,
                code="unparseable",
                severity="error",
                message=f"could not parse Python file {p.relative_to(root)}",
            )
        )

    # 6. Unmapped dependencies
    for missing in resolution.requirements.unmapped:
        issues.append(
            LintIssue(
                service=name,
                code="unmapped",
                severity="warning",
                message=f"import {missing!r} matched no installed distribution in lockfile",
            )
        )

    # 7. Optional ruff integration
    if run_ruff:
        py_files = [str(f) for f in resolution.files if f.suffix == ".py"]
        if py_files:
            ruff_bin = _find_ruff(repo_root)
            if ruff_bin:
                proc = subprocess.run(
                    [str(ruff_bin), "check", "--no-fix", "--output-format=text", *py_files],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0 and proc.stdout.strip():
                    for line in proc.stdout.splitlines():
                        if ":" in line and not line.startswith("Found"):
                            issues.append(
                                LintIssue(
                                    service=name,
                                    code="ruff",
                                    severity="error",
                                    message=line.strip(),
                                )
                            )

    return issues


def _find_ruff(repo_root: Path) -> Path | None:
    venv_ruff = venv_python(repo_root).parent / ("ruff.exe" if sys_is_windows() else "ruff")
    if venv_ruff.is_file():
        return venv_ruff
    system_ruff = shutil.which("ruff")
    if system_ruff:
        return Path(system_ruff)
    return None


def sys_is_windows() -> bool:
    import sys
    return sys.platform == "win32"
