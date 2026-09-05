# pyhusk — Design Spec

Date: 2026-09-05
Status: Approved for implementation planning

## 1. What it is

`pyhusk` is a Python package and CLI that scans a FastAPI microservices monorepo,
discovers each service's routes, computes the minimal slice of repository code and
third-party dependencies that service actually needs, and builds a Docker image
containing only that slice.

Its second job — and in practice the more valuable one — is knowing which service
images are stale. Changing one shared module rebuilds only the services whose slice
contains that module, not the whole repo.

## 2. Design decisions

### 2.1 No Pants

The original concept wrapped Pants as the build engine while also performing its own
AST-based import walk. That is two dependency-inference engines that can disagree,
plus a Pants bootstrap, a `pants.toml`, BUILD file generation, and a second lockfile
format alongside `uv.lock`.

Once `pyhusk` computes the file slice itself, the remaining work is "copy these files,
install these pinned deps, build an image" — a generated Dockerfile and `docker build`.
Pants is therefore dropped. The tool depends on `docker` and a repository managed by
`uv`.

### 2.2 Config file is `pyhusk.yaml`

Named for the tool, not for the concept, so it is greppable and unambiguous in a repo
that may already have service manifests.

### 2.3 Target repository assumptions

- Single root `pyproject.toml` and `uv.lock` at the repo root.
- A single `.venv` at the repo root containing the union of all service dependencies.
- Services are FastAPI applications with a module-level app instance.

uv workspaces (per-service `pyproject.toml` members) are out of scope for this
version. The dependency resolution layer is written so workspace support is an
additive change, not a rewrite.

## 3. Configuration

```yaml
services:
  auth-service:
    entry: services/auth/main.py
    app: app              # name of the FastAPI() instance in the entry module
    base_image: python:3.12-slim   # optional
    port: 8000                     # optional
    registry: ghcr.io/acme         # optional; enables remote staleness checks
  payment-service:
    entry: services/payment/main.py
    app: app
```

`base_image` defaults to `python:3.12-slim`; `port` defaults to `8000`. `registry` has
no default — when unset, staleness is checked against the local image only (section 5).
When set, the built image is additionally tagged `<registry>/<service>:latest`, and that
tag is the fallback source for the slice hash label.

If `pyhusk.yaml` is absent, `pyhusk` auto-detects: each top-level directory is scanned
for a `main.py` whose source contains a `FastAPI(` call. Each hit becomes one service,
named after its directory.

Config loading and validation live in `config.py`, backed by a pydantic model.

## 4. Pipeline

`pyhusk build <service>` runs the following stages. Every stage before stage 5 is pure
computation with no Docker involvement, which is what makes staleness checking cheap.

### 4.1 Route and dependency discovery (`discover.py`)

A probe module runs in a subprocess using the target repo's own interpreter
(`.venv/bin/python -m pyhusk._probe <entry> <app>`), with the repo root as the working
directory. Running out-of-process keeps the target repo's imports out of pyhusk's own
interpreter, and lets an import-time crash be reported rather than propagated.

The probe imports the entry module, reads the app instance, and collects source files
from two sources:

1. **Route handlers.** For each entry in `app.routes`, resolve the endpoint callable
   and take `inspect.getsourcefile`.
2. **Dependency injection chains.** FastAPI already resolves `Depends()` into a
   dependency tree at route-registration time. Each route exposes `route.dependant`,
   whose `.dependencies` list contains sub-dependants recursively, each with a `.call`
   attribute. The probe walks that tree to a fixed point and takes the source file of
   every `.call`. This closes the largest correctness gap that a purely static import
   walk would leave open, using FastAPI's own resolved graph rather than heuristics.

The entry file itself is always included, since middleware, lifespan handlers, and
exception handlers are registered there.

Files that resolve inside `.venv` or the standard library are dropped from the local
set; the distributions providing them are picked up by the dependency stage instead.

The probe emits JSON on stdout: the file list, plus the set of route paths and methods
(retained for the verification stage in 4.6).

### 4.2 Static import walk (`graph.py`)

Starting from the discovered file set, parse each file with `ast` and collect `Import`
and `ImportFrom` nodes, including relative imports. Each imported module name is
resolved against the repository:

- Resolves to a file under the repo root → local, added to the work queue.
- Resolves inside `.venv` or the standard library → third-party, name recorded for the
  dependency stage.
- Resolves to nothing → recorded as an unresolved import and reported as a warning.

Package imports pull in the corresponding `__init__.py`. The walk continues to a fixed
point. Paths passed with `--include` are added verbatim and are themselves walked, so
force-including a plugin module also pulls that module's own imports.

The result is the **local slice**: the minimal set of repository files for that service.

### 4.3 Dependency resolution (`deps.py`)

Third-party top-level import names are mapped to distribution names using
`importlib.metadata.packages_distributions()`, executed inside the target repo's
`.venv` so the mapping reflects what is actually installed. This handles the cases
where import name and distribution name differ.

Those distributions are then expanded to their transitive closure by walking `uv.lock`
with `tomllib`, and emitted as a pinned `requirements.txt`. A dependency present in the
lock but not reachable from the service's imports never enters the image.

An import name with no matching distribution produces a warning naming the file and
line. It is never silently dropped.

### 4.4 Image context assembly (`dockerize.py`)

`.build/<service>/` is populated with:

- the local slice, copied preserving repo-relative paths
- `requirements.txt` from stage 4.3
- a generated `Dockerfile`

The generated Dockerfile:

```dockerfile
FROM <base_image>
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "<module.path>:<app>", "--host", "0.0.0.0", "--port", "<port>"]
```

The uvicorn module path is derived from the entry file's path relative to the repo
root. Dependencies are installed before code is copied so that a code-only change
reuses the dependency layer.

If a file named `Dockerfile.override` sits next to the entry file, it is used verbatim
in place of the generated Dockerfile. The slice and `requirements.txt` are still
computed and written, so an override still gets a pruned context.

`--show-dockerfile` writes the full context and stops before building.

### 4.5 Shared base images

Services frequently resolve to identical dependency sets. Since image size is dominated
by wheels rather than application source, building those wheels once is where the size
and pull-time win actually comes from.

`pyhusk` hashes the resolved `requirements.txt` content. When two or more services in a
build share a dependency hash, it builds `pyhusk-base:<dephash>` once, containing the
base image plus installed dependencies, and rewrites those services' Dockerfiles to
`FROM pyhusk-base:<dephash>` with the `pip install` step removed.

A service with a unique dependency set keeps the self-contained Dockerfile from 4.4;
there is no benefit to a base image used once.

`--no-shared-base` disables this and forces self-contained images.

### 4.6 Build and verify

`docker build -t <service>:latest .build/<service>` runs the build. The slice hash
(see section 5) is stamped as an image label.

Verification then runs automatically: start the container, poll `/openapi.json` until
it responds or a timeout elapses, and compare the route paths and methods returned
against the set the probe recorded in 4.1.

This is what turns pyhusk's central risk — a missing file producing an image that
crashes on startup — into a build-time failure rather than a deploy-time one. A
container that fails to start, fails to serve, or serves a different route set fails
the build, and the container logs are printed.

`--no-verify` skips this for the case where the image needs an unavailable external
dependency to boot.

### 4.7 Reporting

On success, print for each service: files in slice against total repo files,
dependencies installed against total in lock, and final image size.

`--compare` additionally builds a naive whole-repo image with the full lock installed
and prints the size delta. Off by default because it doubles build time. It exists to
answer honestly whether the pruning is worth anything on a given repo.

## 5. Staleness detection

Two separate questions: which services exist, and which of them need rebuilding.

**Which services exist** comes from `pyhusk.yaml`, or from auto-detection when that
file is absent.

**Which need rebuilding** is computed per service before any Docker command runs.
Stages 4.1 through 4.4 execute — they are fast and involve no Docker — producing the
slice, `requirements.txt`, and Dockerfile text. A SHA-256 is computed over the sorted
list of `(repo-relative path, file bytes)` in the slice, plus the `requirements.txt`
text, plus the Dockerfile text.

Content hashing rather than git state means the check works on uncommitted edits and
gives identical results across machines.

The hash is compared against two sources, in order:

1. The label on the local image `<service>:latest`, read with `docker image inspect`.
2. If a registry is configured for the service and the local image is absent, the label
   on the remote tag, read with `docker buildx imagetools inspect`.

Storing staleness in the image label rather than in a `.build/` file is what makes this
survive ephemeral CI runners. A file under `.build/` dies with the runner, every CI run
then rebuilds everything, and the tool's main benefit disappears exactly where it
matters most.

If the hash matches and the image exists, the service is skipped and reported as
unchanged. Otherwise it is built. `--force` rebuilds regardless.

The consequence: editing `common/auth.py` in a ten-service repo where three services
import it rebuilds three containers.

## 6. CLI

- `pyhusk init` — auto-detect services, write `pyhusk.yaml`, add `.build/` to
  `.gitignore`. Idempotent; never overwrites an existing `pyhusk.yaml`.
- `pyhusk list` — list configured services and their entry points.
- `pyhusk build [service ...]` — build the named services, or every stale service when
  no name is given.
- `pyhusk plan [--json]` — run staleness detection only and report which services are
  stale, without building. `--json` emits a machine-readable list suitable for feeding
  a CI matrix, so a pipeline spawns build jobs only for stale services and runs them in
  parallel.

Flags on `build`: `--include <path>` (repeatable), `--show-dockerfile`, `--force`,
`--compare`, `--no-verify`, `--no-shared-base`.

`typer` provides the CLI.

## 7. Failure handling

Every failure is loud. The tool never produces an image it believes to be incomplete.

| Condition | Behavior |
|---|---|
| Probe import fails | Print the subprocess stderr, abort that service, non-zero exit |
| Import resolves to nothing | Warn with file and line, continue, list all at end of run |
| Import name maps to no distribution | Warn with file and line, continue, list all at end of run |
| Handler source inside `.venv` | Skip the file, keep the providing distribution |
| Container fails verification | Print container logs, fail that service, non-zero exit |
| Docker unavailable | Abort before any work with a clear message |

With multiple services, a failure in one does not abort the others. The run exits
non-zero and the summary names which services failed.

## 8. Known limits

These are documented, not hidden.

- The static walk cannot see `importlib.import_module` with a computed string, or
  `getattr`-based dispatch. `--include` is the escape hatch.
- `Depends()` chains are resolved (4.1), but only those FastAPI has registered at
  import time. A dependency injected dynamically at request time is invisible.
- Conditional imports inside `if TYPE_CHECKING:` blocks are included, which is
  conservative and slightly over-includes rather than under-including.
- Verification proves the container boots and serves the expected route set. It is not
  a substitute for integration testing the built image.
- Size reduction depends on services having genuinely divergent dependencies. Where
  every service shares one stack, the shared base image (4.5) captures most of the
  available win and the per-service delta is small. `--compare` reports the truth.

## 9. Package structure

```
pyhusk/
  pyproject.toml
  src/pyhusk/
    __init__.py
    cli.py                    # typer commands
    config.py                 # pyhusk.yaml pydantic model, loader, auto-detect
    discover.py               # subprocess probe driver
    _probe.py                 # runs inside target venv: routes + Depends walk
    graph.py                  # ast import walk, local slice resolution
    deps.py                   # import name -> distribution -> uv.lock closure
    dockerize.py              # context assembly, Dockerfile generation, shared base
    staleness.py              # slice hashing, image label read/compare
    verify.py                 # container boot + /openapi.json route comparison
  tests/
    fixtures/demo/            # 2-service monorepo with shared common/
    test_config.py
    test_graph.py
    test_deps.py
    test_staleness.py
    test_build_integration.py
  README.md
```

## 10. Testing

The fixture monorepo at `tests/fixtures/demo/` contains `common/`, `services/a`, and
`services/b`, where `b` imports a third-party package that `a` does not, and both share
part of `common/`. This makes both pruning claims — code and dependencies — directly
assertable.

- `test_config.py` — schema validation, defaults, auto-detection.
- `test_graph.py` — the walk against the fixture: `a`'s slice contains the shared
  `common/` module and excludes `services/b` and the unshared parts of `common/`.
  Relative imports, package imports, and `--include` propagation.
- `test_deps.py` — `uv.lock` transitive closure and import-to-distribution mapping,
  against a fixture lock file.
- `test_staleness.py` — hash stability across runs, hash changes when a slice file
  changes, and no hash change when a repo file outside the slice changes.
- `test_build_integration.py` — full build of service `a`, asserting `services/b` is
  absent from the context, the dependency unique to `b` is absent from
  `requirements.txt`, and verification passes. Marked `docker` so it can be deselected.

## 11. Build order

1. Package scaffold, `typer` CLI skeleton, `pyhusk init`.
2. `config.py` — schema, loader, auto-detection.
3. `_probe.py` and `discover.py` — routes plus `Depends()` walk.
4. `graph.py` — import walk, tested against the fixture repo.
5. `deps.py` — distribution mapping and lock closure.
6. `dockerize.py` — context and Dockerfile generation; `build` wired end to end.
7. `verify.py` — container boot and route comparison.
8. `staleness.py` — slice hashing, image labels, `pyhusk plan`.
9. Shared base images.
10. `--compare`, `--show-dockerfile`, `Dockerfile.override`, remote registry staleness.
11. README with quickstart and the limits from section 8.

Stage 6 is the first point at which the tool is useful on a real repo. Measure with
`--compare` there before investing in stages 9 and 10.
