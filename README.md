# pyhusk

Minimal Docker images for FastAPI monorepos, and only rebuilding the ones that changed.

pyhusk discovers each service's routes by importing its app, follows the imports and
`Depends()` chains those routes actually reach, and builds an image containing that slice
and nothing else. It then remembers what went into each image, so editing one shared
module rebuilds only the services that use it.

## Requirements

- Python 3.12 or newer
- A monorepo managed by `uv`, with a root `pyproject.toml`, `uv.lock` and `.venv`
- Docker

## Quickstart

```bash
uv tool install pyhusk
cd your-monorepo
pyhusk init          # writes pyhusk.yaml from detected services
pyhusk list
pyhusk build         # builds every stale service
```

## Configuration

`pyhusk init` writes a starting point. The full schema:

```yaml
services:
  auth-service:
    entry: services/auth/main.py   # required
    app: app                       # attribute holding the FastAPI instance
    factory: false                 # true when `app` is a callable returning the app
    base_image: python:3.12-slim
    port: 8000
    registry: ghcr.io/acme         # enables staleness checks against a registry
    healthcheck: /healthz          # used when the OpenAPI schema is disabled
```

## Commands

| Command | What it does |
|---|---|
| `pyhusk init` | Detect services, write `pyhusk.yaml`, ignore `.build/`. Safe to rerun. |
| `pyhusk list` | Show the services pyhusk can see. |
| `pyhusk plan` | Report which services are stale. `--json` for CI. |
| `pyhusk build [service ...]` | Build the named services, or every stale one. |
| `pyhusk build-bases` | Build shared base images only. |

Useful flags on `build`: `--show-dockerfile` writes the context without building,
`--include PATH` forces a path into the slice, `--force` rebuilds regardless of
staleness, `--compare` also builds a whole-repo image and prints the size difference,
`--no-verify` skips the container check, `--no-shared-base` produces self-contained
images.

## In CI

`pyhusk plan --json` prints the stale services and the base images they need, so a
pipeline builds bases once and then fans the services out in parallel:

```yaml
jobs:
  plan:
    runs-on: ubuntu-latest
    outputs:
      services: ${{ steps.plan.outputs.services }}
    steps:
      - uses: actions/checkout@v4
      - run: uv sync
      - id: plan
        run: |
          echo "services=$(pyhusk plan --json | jq -c '[.services[] | select(.stale) | .name]')" >> "$GITHUB_OUTPUT"
          pyhusk build-bases

  build:
    needs: plan
    if: needs.plan.outputs.services != '[]'
    strategy:
      matrix:
        service: ${{ fromJson(needs.plan.outputs.services) }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uv sync
      - run: pyhusk build ${{ matrix.service }}
```

The slice hash lives on the image as a label, not in a local file, so this works on
fresh runners that have no `.build/` directory.

## How staleness is decided

Each service gets a SHA-256 over the contents of its slice, its resolved
`requirements.txt`, its Dockerfile, and the digest of its base image. That hash is
stamped on the built image. A service is stale when the hash differs or the image is
gone.

Hashing content rather than git state means it works on uncommitted edits and matches
across machines. Including the base image digest means an upstream `python:3.12-slim`
security update triggers a rebuild, which a Dockerfile-text comparison would miss.

## Verification

After each build pyhusk starts the container and checks it serves what the probe found.
With the OpenAPI schema enabled it compares the full route set. With the schema disabled
it polls the configured `healthcheck` path. With neither it only confirms the container
stays up, and says so, because a weaker check should never be mistaken for the strong one.

## Known limits

Read these before trusting an image.

- Dynamic imports are invisible. `importlib.import_module` with a computed string and
  `getattr`-based dispatch cannot be seen statically. Use `--include`.
- Background and scheduled work is not reachable from the route graph. An APScheduler
  job registered as `scheduler.add_job("jobs.reports:run")` is a string, not an import.
  Use `--include`, and review the slice for any service whose real work happens off the
  request path.
- `Depends()` chains are resolved exactly, but only what FastAPI registered at import
  time. A dependency injected at request time is invisible.
- Routes added with Starlette's `add_route` get no dependency scan, because FastAPI runs
  no injection for them. Their handler file is still included.
- `if TYPE_CHECKING:` imports are included. pyhusk over-includes rather than
  under-includes when it is unsure.
- Verification is not integration testing. It proves the container boots and serves the
  expected routes, nothing more.
- Size reduction depends on services having genuinely different dependencies. Run
  `pyhusk build <service> --compare` on your repo and believe the number, not the pitch.
