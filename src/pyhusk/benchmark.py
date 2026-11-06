from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from pyhusk.deps import all_requirements
from pyhusk.docker import image_size, run_docker
from pyhusk.dockerize import assemble_context, render_dockerfile
from pyhusk.pipeline import Resolution
from pyhusk.report import count_python_files, human_size
from pyhusk.staleness import SLICE_LABEL


@dataclass
class ServiceBenchmark:
    name: str
    pruned_time_s: float
    naive_time_s: float
    pruned_size_bytes: int
    naive_size_bytes: int
    pruned_packages: int
    naive_packages: int
    pruned_files: int
    total_files: int

    @property
    def time_saved_s(self) -> float:
        return max(0.0, self.naive_time_s - self.pruned_time_s)

    @property
    def time_saved_pct(self) -> float:
        if self.naive_time_s <= 0:
            return 0.0
        return max(0.0, (self.naive_time_s - self.pruned_time_s) / self.naive_time_s)

    @property
    def size_saved_bytes(self) -> int:
        return max(0, self.naive_size_bytes - self.pruned_size_bytes)

    @property
    def size_saved_pct(self) -> float:
        if self.naive_size_bytes <= 0:
            return 0.0
        return max(0.0, (self.naive_size_bytes - self.pruned_size_bytes) / self.naive_size_bytes)

    def to_dict(self) -> dict[str, object]:
        return {
            "service": self.name,
            "pruned_time_seconds": round(self.pruned_time_s, 2),
            "naive_time_seconds": round(self.naive_time_s, 2),
            "time_saved_seconds": round(self.time_saved_s, 2),
            "time_saved_pct": f"{self.time_saved_pct:.1%}",
            "pruned_size": human_size(self.pruned_size_bytes),
            "naive_size": human_size(self.naive_size_bytes),
            "size_saved": human_size(self.size_saved_bytes),
            "size_saved_pct": f"{self.size_saved_pct:.1%}",
            "pruned_packages": self.pruned_packages,
            "naive_packages": self.naive_packages,
            "pruned_files": self.pruned_files,
            "total_files": self.total_files,
        }


def assemble_naive_context(repo_root: Path, resolution: Resolution) -> Path:
    """Write .build/_naive/<name>/ containing all repo files and all dependencies."""
    context = repo_root / ".build" / "_naive" / resolution.name
    if context.exists():
        shutil.rmtree(context)
    context.mkdir(parents=True)

    for source in repo_root.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(repo_root)
        if relative.parts and relative.parts[0] in {".build", ".venv", ".git"}:
            continue
        destination = context / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    (context / "requirements.txt").write_text(all_requirements(repo_root).text, encoding="utf-8")
    (context / "Dockerfile").write_text(
        render_dockerfile(repo_root, resolution.service, resolution.base.pinned, True),
        encoding="utf-8",
    )
    return context


def run_service_benchmark(
    repo_root: Path,
    resolution: Resolution,
    no_cache: bool = True,
) -> ServiceBenchmark:
    """Build pruned and naive images, timing both and measuring the size delta."""
    # 1. Assemble pruned context
    assemble_context(
        repo_root,
        resolution.name,
        resolution.service,
        resolution.files,
        resolution.requirements.text,
        resolution.dockerfile_text,
    )

    pruned_build_args = [
        "build",
        "-t",
        resolution.tag,
        "--label",
        f"{SLICE_LABEL}={resolution.slice_hash}",
        str(repo_root / ".build" / resolution.name),
    ]
    if no_cache:
        pruned_build_args.insert(1, "--no-cache")

    t0 = time.perf_counter()
    pruned_res = run_docker(pruned_build_args, capture_output=True)
    t_pruned = time.perf_counter() - t0
    if pruned_res.returncode != 0:
        raise RuntimeError(f"Pruned build failed for {resolution.name}:\n{pruned_res.stderr}")

    # 2. Assemble naive context
    naive_ctx = assemble_naive_context(repo_root, resolution)
    naive_tag = f"{resolution.name}-naive:latest"
    naive_build_args = ["build", "-t", naive_tag, str(naive_ctx)]
    if no_cache:
        naive_build_args.insert(1, "--no-cache")

    t1 = time.perf_counter()
    naive_res = run_docker(naive_build_args, capture_output=True)
    t_naive = time.perf_counter() - t1
    if naive_res.returncode != 0:
        raise RuntimeError(f"Naive baseline build failed for {resolution.name}:\n{naive_res.stderr}")

    pruned_size = image_size(resolution.tag)
    naive_size = image_size(naive_tag)
    total_repo_files = count_python_files(repo_root)
    naive_reqs = all_requirements(repo_root)

    return ServiceBenchmark(
        name=resolution.name,
        pruned_time_s=t_pruned,
        naive_time_s=t_naive,
        pruned_size_bytes=pruned_size,
        naive_size_bytes=naive_size,
        pruned_packages=len(resolution.requirements.pins),
        naive_packages=len(naive_reqs.pins),
        pruned_files=len(resolution.files),
        total_files=total_repo_files,
    )


def format_markdown_table(benchmarks: list[ServiceBenchmark]) -> str:
    """Format benchmark results as a Markdown table ready for README or pitch docs."""
    lines = [
        "| Service | Build Time (Pruned vs Naive) | Time Saved | Compressed Size (Pruned vs Naive) | Size Saved | Packages |",
        "|---|---|---|---|---|---|",
    ]
    for b in benchmarks:
        t_str = f"{b.pruned_time_s:.1f}s vs {b.naive_time_s:.1f}s"
        t_saved = f"**-{b.time_saved_pct:.0%}** ({b.time_saved_s:.1f}s)"
        s_str = f"{human_size(b.pruned_size_bytes)} vs {human_size(b.naive_size_bytes)}"
        s_saved = f"**-{b.size_saved_pct:.0%}** ({human_size(b.size_saved_bytes)})"
        pkg_str = f"{b.pruned_packages} vs {b.naive_packages}"
        lines.append(f"| `{b.name}` | {t_str} | {t_saved} | {s_str} | {s_saved} | {pkg_str} |")
    return "\n".join(lines)
