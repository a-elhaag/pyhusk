# Overview

pyhusk builds minimal Docker images for FastAPI monorepos, and rebuilds only
the services that changed.

A monorepo image usually ships the whole repository: every service, every
shared module, every dependency in the lock file. pyhusk instead discovers each
service's routes by importing its app, follows the imports and `Depends()`
chains those routes actually reach, and builds an image containing that slice
and nothing else. It then remembers what went into each image, so editing one
shared module rebuilds only the services that use it.

## How it works

Every build runs the same pipeline, in order:

1. **Probe.** pyhusk imports the service's app in a subprocess running the
   target repository's own `.venv`, walks `app.routes` (including mounts and
   nested routers), and records the source file of every endpoint and every
   callable in each route's `Depends()` tree. The entry module is always
   included, since middleware and lifespan handlers live there.
2. **Slice.** Starting from those seed files, pyhusk walks imports with an AST
   pass, following local modules and recording third-party top-level packages.
   Files it cannot parse are kept in the image with a warning rather than
   dropped.
3. **Requirements.** Third-party import names are mapped to distributions via
   the target venv's installed metadata, pinned from `uv.lock`, and closed
   transitively over the lock graph. `uvicorn` is added explicitly, because
   application code never imports its own server.
4. **Base.** The configured base image tag is resolved to a content digest, so
   an upstream patch release is noticed. Services whose base digest plus
   requirements are identical share one `pyhusk-base` image.
5. **Hash.** File paths and contents, the requirements text, the Dockerfile
   text, and the base digest are hashed into a slice hash, stamped onto the
   image as the `org.pyhusk.slice` label.
6. **Build and verify.** Only services whose stamped hash differs are rebuilt.
   Each fresh image is booted and checked: the OpenAPI schema is compared
   against the probed routes when available, otherwise a healthcheck path,
   otherwise a boot check. An image that fails verification is removed, so a
   missing file becomes a build failure instead of a deploy failure.

## What else it does

The slice is useful beyond Docker. The same machinery powers:

| Command | Purpose |
|---|---|
| `pyhusk lint` | Enforce service boundaries, forbidden imports, and cycles |
| `pyhusk test` | Run only the tests affected by a git diff |
| `pyhusk affected` | Show which services and tests a diff touches |
| `pyhusk why` | Trace the shortest import path to a file or package |
| `pyhusk unused` | Find Python files no service reaches |
| `pyhusk log` | Show the commits that touched a service's slice |
| `pyhusk benchmark` | Measure pruned vs whole-repo build time and size |
| `pyhusk plan` | Report stale services as JSON for CI |

## Requirements

- Python 3.12 or newer
- A monorepo managed by `uv`, with a root `pyproject.toml`, `uv.lock`,
  and `.venv` (created by `uv sync`)
- Docker, for `build`, `benchmark`, and `build --compare` only. Everything
  else — `lint`, `test`, `affected`, `why`, `unused`, `log`, `plan` — runs
  without a daemon.

## Next steps

- [Install](get-started/install.md) pyhusk on your machine
- [Run the quickstart](get-started/quickstart.md) against your monorepo
- Read the [configuration reference](reference/configuration.md) when you
  outgrow the defaults
