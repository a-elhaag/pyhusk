# pyhusk

Minimal Docker images for FastAPI monorepos, and only rebuilding the ones that changed.

pyhusk discovers each service's routes by importing its app, follows the imports and
`Depends()` chains those routes actually reach, and builds an image containing that
slice and nothing else. It then remembers what went into each image, so editing one
shared module rebuilds only the services that use it.

## How it works

1. **Discover** — imports the service's app, walks its routes and their `Depends()`
   trees to find every module a request can actually reach.
2. **Prune** — follows the import graph from there, then resolves the transitive
   package closure from your lockfile. Nothing unreferenced comes along.
3. **Build and verify** — builds the image, boots it, and checks its OpenAPI schema
   (or a healthcheck) before calling the build done.

See [Staleness](staleness.md) for how pyhusk decides what needs rebuilding, and
[Verification](verification.md) for what "checked" means.

## Requirements

- Python 3.12 or newer
- A monorepo managed by `uv`, with a root `pyproject.toml`, `uv.lock` and `.venv`
- Docker

Next: [Quickstart](quickstart.md).
