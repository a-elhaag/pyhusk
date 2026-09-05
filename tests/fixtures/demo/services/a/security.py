"""Reached only through Depends(), never through a literal import in main.py."""


def current_user() -> str:
    return "anonymous"
