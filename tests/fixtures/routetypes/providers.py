from fastapi import Depends


def inner_dependency() -> str:
    return "inner"


def outer_dependency(inner: str = Depends(inner_dependency)) -> str:
    return f"outer-{inner}"
