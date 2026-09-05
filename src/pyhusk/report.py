from __future__ import annotations

UNITS = ["B", "KB", "MB", "GB", "TB"]


def human_size(count: int) -> str:
    """Byte count as a short human string."""
    size = float(count)
    for unit in UNITS:
        if size < 1024 or unit == UNITS[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} {UNITS[-1]}"
