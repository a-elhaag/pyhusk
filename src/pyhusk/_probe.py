"""Route and dependency probe. Runs inside the TARGET repository's interpreter.

Import nothing from pyhusk here, and nothing outside the standard library. This
file is handed to a foreign interpreter by absolute path, because pyhusk is not
installed in the target's virtualenv.

Output on stdout is a single JSON object. Anything diagnostic goes to stderr, so
stdout stays parseable.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
from pathlib import Path


def _source_file(obj: object) -> str | None:
    """Best-effort source file for a callable, seeing through decorators."""
    try:
        unwrapped = inspect.unwrap(obj)
    except Exception:
        unwrapped = obj
    try:
        found = inspect.getsourcefile(unwrapped)
    except (TypeError, OSError):
        found = None
    if found is None:
        # A callable instance: fall back to the class that defines __call__.
        try:
            found = inspect.getsourcefile(unwrapped.__class__)
        except (TypeError, OSError, AttributeError):
            return None
    return found


def _collect_dependant(dependant: object, files: set[str], seen: set[int]) -> None:
    """Walk a FastAPI dependant tree, recording the source of every callable.

    FastAPI has already resolved Depends() into this tree at route-registration
    time, including router-level and app-level dependencies, so walking it is
    exact rather than heuristic.
    """
    if dependant is None or id(dependant) in seen:
        return
    seen.add(id(dependant))

    call = getattr(dependant, "call", None)
    if call is not None:
        found = _source_file(call)
        if found:
            files.add(found)

    for sub in getattr(dependant, "dependencies", None) or []:
        _collect_dependant(sub, files, seen)


def _collect_routes(
    routes: object,
    prefix: str,
    files: set[str],
    described: list[dict[str, object]],
    seen: set[int],
) -> None:
    """Walk app.routes, which is NOT homogeneous.

    Three shapes must survive here:
      * fastapi.routing.APIRoute / APIWebSocketRoute - .endpoint and .dependant
      * starlette.routing.Route / WebSocketRoute - .endpoint, NO .dependant,
        because FastAPI runs no dependency injection for them
      * starlette.routing.Mount - no .endpoint, but .routes to recurse into

    Every attribute is read with getattr(..., None). Assuming APIRoute is how a
    probe crashes on the first real repository it meets.
    """
    for route in routes or []:
        if id(route) in seen:
            continue
        seen.add(id(route))

        path = prefix + (getattr(route, "path", "") or "")

        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None:
            found = _source_file(endpoint)
            if found:
                files.add(found)

        dependant = getattr(route, "dependant", None)
        _collect_dependant(dependant, files, set())

        nested = getattr(route, "routes", None)
        if nested:
            _collect_routes(nested, path, files, described, seen)
            continue

        if endpoint is None:
            continue

        methods = sorted(getattr(route, "methods", None) or [])
        # Only APIRoute carries .dependant, and only a documented one appears in
        # the OpenAPI schema. A plain Starlette route added with add_route never
        # does, so verification must not demand it there.
        documented = bool(
            dependant is not None
            and getattr(route, "include_in_schema", False)
            and methods
        )
        described.append({"path": path, "methods": methods, "documented": documented})


def _import_entry(entry: Path) -> object:
    """Import the entry file as a module, so its relative imports resolve."""
    repo_root = Path.cwd()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return importlib.import_module(".".join(entry.with_suffix("").parts))


def main() -> int:
    parser = argparse.ArgumentParser(description="pyhusk route probe")
    parser.add_argument("--entry", required=True, help="entry file, relative to repo root")
    parser.add_argument("--app", required=True, help="attribute holding the app")
    parser.add_argument(
        "--factory",
        action="store_true",
        help="the attribute is a callable returning the app, not the app itself",
    )
    args = parser.parse_args()

    module = _import_entry(Path(args.entry))

    if not hasattr(module, args.app):
        print(
            f"module {module.__name__!r} has no attribute {args.app!r}; "
            f"check the 'app' key for this service",
            file=sys.stderr,
        )
        return 1

    application = getattr(module, args.app)
    if args.factory:
        if not callable(application):
            print(
                f"{module.__name__}.{args.app} is not callable, but factory: true "
                f"was configured for this service",
                file=sys.stderr,
            )
            return 1
        application = application()

    if not hasattr(application, "routes"):
        hint = "" if args.factory else ". If it is a factory function, set factory: true"
        print(
            f"{module.__name__}.{args.app} has no .routes attribute; it does not look "
            f"like a FastAPI or Starlette application{hint}",
            file=sys.stderr,
        )
        return 1

    files: set[str] = set()
    described: list[dict[str, object]] = []
    _collect_routes(application.routes, "", files, described, set())

    # Middleware, lifespan handlers and exception handlers are registered in the
    # entry module and reachable from no route, so it is always part of the slice.
    entry_source = _source_file(module)
    if entry_source:
        files.add(entry_source)

    json.dump(
        {
            "files": sorted(str(Path(f).resolve()) for f in files),
            "routes": described,
            "openapi_url": getattr(application, "openapi_url", None),
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
