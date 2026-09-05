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
    factory: false                 # optional; `app` is a callable returning the app
    healthcheck: /healthz          # optional; verification path when OpenAPI is off
  payment-service:
    entry: services/payment/main.py
    app: create_app
    factory: true
```

`base_image` defaults to `python:3.12-slim`; `port` defaults to `8000`; `factory`
defaults to `false`.

`registry` has no default — when unset, staleness is checked against the local image
only (section 5). When set, the built image is additionally tagged
`<registry>/<service>:latest`, and that tag is the fallback source for the slice hash
label.

`factory: true` covers the application-factory pattern, where the entry module exposes
`def create_app() -> FastAPI` rather than a module-level instance. The probe calls the
attribute instead of reading it. This cannot be auto-detected, because a FastAPI
instance is itself callable — it is an ASGI application — so an attribute being callable
proves nothing. The key is explicit.

`healthcheck` names a path for the verification stage to poll when the service disables
its OpenAPI schema (section 4.6).

If `pyhusk.yaml` is absent, `pyhusk` auto-detects: each top-level directory is scanned
for a `main.py` whose source contains a `FastAPI(` call. Each hit becomes one service,
named after its directory.

Config loading and validation live in `config.py`, backed by a pydantic model.

## 4. Pipeline

`pyhusk build <service>` runs the following stages. Everything before 4.5 is local
computation that builds nothing; the only network access is a registry manifest query to
resolve the base image digest. That is what makes staleness checking cheap enough to run
on every invocation.

### 4.1 Route and dependency discovery (`discover.py`)

A probe module runs in a subprocess using the target repo's own interpreter, with the
repo root as the working directory. Running out-of-process keeps the target repo's
imports out of pyhusk's own interpreter, and lets an import-time crash be reported
rather than propagated.

The interpreter path is resolved per platform: `.venv/bin/python` on POSIX,
`.venv\Scripts\python.exe` on Windows. A missing interpreter aborts with a message
naming the expected path, rather than falling back to a system Python that would resolve
different imports.

The probe imports the entry module and obtains the application object. With
`factory: false` it reads the named attribute; with `factory: true` it calls it. It then
collects source files from two sources.

**Route handlers.** The probe walks `app.routes`. That list is not homogeneous, and
assuming otherwise is the fastest way to crash the probe on a real repo:

- `fastapi.routing.APIRoute` and `APIWebSocketRoute` — created by `@app.get`,
  `@router.post`, and `add_api_route`. These carry both `.endpoint` and `.dependant`.
- `starlette.routing.Route` and `WebSocketRoute` — created by the inherited Starlette
  `add_route` and `add_websocket_route`. These carry `.endpoint` but **no** `.dependant`,
  because FastAPI performs no dependency injection for them. Nothing is missed by not
  scanning dependencies here; there are none to scan.
- `starlette.routing.Mount` — a sub-application. The probe recurses into `.routes` when
  the mounted app exposes them, and records the mount prefix so verification (4.6)
  compares full paths.

Every route type yields its endpoint's source file via `inspect.getsourcefile`. Route
attributes are read with `getattr(route, name, None)`, never assumed present.

**Dependency injection chains.** For routes that do carry `.dependant`, FastAPI has
already resolved `Depends()` into a dependency tree at registration time. Each dependant
exposes a `.dependencies` list of sub-dependants, recursively, each with a `.call`
attribute. The probe walks that tree to a fixed point and takes the source file of every
`.call`, including router-level and application-level dependencies, which FastAPI merges
into each route's dependant. This closes the largest correctness gap a purely static
import walk would leave open, using FastAPI's own resolved graph rather than heuristics.

The entry file itself is always included, since middleware, lifespan handlers, and
exception handlers are registered there.

Files that resolve inside `.venv` or the standard library are dropped from the local
set; the distributions providing them are picked up by the dependency stage instead.

The probe emits JSON on stdout: the file list, the set of route paths and methods, and
the value of `app.openapi_url` — all three consumed by the verification stage in 4.6.

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

**The ASGI server is injected, not inferred.** Application code does not import
`uvicorn` — the server imports the application. A purely import-derived
`requirements.txt` therefore omits the one package the generated `CMD` needs, and every
image would fail to start. `pyhusk` appends the server to `requirements.txt`
unconditionally, pinned from `uv.lock` when present there and to a known-good version
otherwise. When `Dockerfile.override` supplies its own entrypoint, the injection still
happens, since an override that runs a different server can pin it explicitly and the
duplicate is harmless.

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

`pyhusk` computes a **base hash** over the resolved `requirements.txt` content **and the
`base_image` reference, pinned to its digest**. Both inputs are required. Hashing
requirements alone would collide two services that install identical dependencies onto
different base images — say `python:3.12-slim` and `python:3.13-slim` — and silently give
one of them the other's interpreter.

When two or more services share a base hash, `pyhusk` builds `pyhusk-base:<basehash>`
once, containing the base image plus installed dependencies, and rewrites those services'
Dockerfiles to `FROM pyhusk-base:<basehash>` with the `pip install` step removed.

A service with a unique base hash keeps the self-contained Dockerfile from 4.4; there is
no benefit to a base image used once.

**Parallel-safe construction.** Section 6's `pyhusk plan --json` exists to drive a CI
matrix, so two jobs on two machines can reach the same `pyhusk-base:<basehash>` at the
same time. A file lock does not help here — the jobs share no filesystem. Base images are
therefore a separate build stage rather than a side effect of a service build:

- `plan --json` emits two lists, `bases` and `services`, where each stale service names
  the base hash it requires.
- `pyhusk build-bases [hash ...]` builds base images only.
- A CI pipeline runs `build-bases` as one job, then fans out the service matrix with that
  job as a dependency.

A single-process local `pyhusk build` does the same thing in sequence: all required bases
first, then services. The failure mode this removes is two runners pushing the same base
tag concurrently and a service resolving `FROM` against a half-pushed manifest.

`--no-shared-base` disables the mechanism entirely and forces self-contained images.

### 4.6 Build and verify

`docker build -t <service>:latest .build/<service>` runs the build. The slice hash
(see section 5) is stamped as an image label.

Verification then runs automatically. It has three tiers, and the probe's recorded
`openapi_url` (4.1) selects which one applies:

1. **Schema comparison** — the default, when OpenAPI is enabled. Start the container,
   poll the app's `openapi_url` until it responds or a timeout elapses, and compare the
   route paths and methods returned against the set the probe recorded.
2. **Healthcheck** — when `FastAPI(openapi_url=None)` disables the schema, which is a
   normal production hardening choice, and the service configures a `healthcheck` path.
   Poll that path for a 2xx or 3xx response. Route sets are not compared, because the
   container will not disclose them.
3. **Boot only** — when the schema is disabled and no `healthcheck` is configured. Assert
   the container starts and stays up for a fixed interval without exiting. This is
   reported as degraded verification with a warning naming the service, so the weaker
   guarantee is never mistaken for the strong one.

Tier 1 is what turns pyhusk's central risk — a missing file producing an image that
crashes on startup — into a build-time failure rather than a deploy-time one. A container
that fails to start, fails to serve, or serves a different route set fails the build, and
the container logs are printed.

`--no-verify` skips verification entirely, for an image that needs an unavailable
external dependency to boot.

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

**Which need rebuilding** is computed per service before any image is built. Stages 4.1
through 4.4 execute — they are fast and build nothing — producing the slice,
`requirements.txt`, and Dockerfile text. A SHA-256 is computed over four inputs:

1. the sorted list of `(repo-relative path, file bytes)` in the slice
2. the `requirements.txt` text
3. the Dockerfile text
4. **the resolved digest of the base image**

Content hashing rather than git state means the check works on uncommitted edits and
gives identical results across machines.

The fourth input exists because base image tags are mutable. `python:3.12-slim` moves
upstream on every patch release, including security patches. Without it, the Dockerfile
text is unchanged, the hash is unchanged, and pyhusk happily reports a service as
up-to-date while its image sits on a superseded base — precisely the situation where a
rebuild matters most.

The digest is resolved with `docker buildx imagetools inspect <ref>`, which queries the
registry manifest without pulling the image. Results are memoized per base reference for
the duration of a run, so a ten-service repo on one base image makes one query. If the
registry is unreachable, pyhusk falls back to the digest of the locally cached base image;
if there is no local copy either, it warns that base freshness is unverified and hashes
the tag string instead of the digest, which restores the old behavior explicitly rather
than silently.

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
  stale, without building. `--json` emits `{"bases": [...], "services": [...]}`, where
  each stale service names the base hash it needs. A CI pipeline feeds `bases` to a
  `build-bases` job and `services` to a matrix that depends on it, so only stale services
  are built and they build in parallel.
- `pyhusk build-bases [hash ...]` — build shared base images only, or every base required
  by the current plan when no hash is given. Idempotent: a base whose tag already exists
  with a matching hash is skipped.

Flags on `build`: `--include <path>` (repeatable), `--show-dockerfile`, `--force`,
`--compare`, `--no-verify`, `--no-shared-base`.

`typer` provides the CLI.

## 7. Failure handling

Every failure is loud. The tool never produces an image it believes to be incomplete.

| Condition | Behavior |
|---|---|
| Probe import fails | Print the subprocess stderr, abort that service, non-zero exit |
| `.venv` interpreter missing | Abort before any work, naming the expected platform path |
| `factory: true` but attribute is not callable | Abort that service with the attribute name |
| Base image digest unresolvable | Warn that base freshness is unverified, hash the tag, continue |
| Import resolves to nothing | Warn with file and line, continue, list all at end of run |
| Import name maps to no distribution | Warn with file and line, continue, list all at end of run |
| Handler source inside `.venv` | Skip the file, keep the providing distribution |
| Container fails verification | Print container logs, fail that service, non-zero exit |
| OpenAPI disabled, no `healthcheck` | Degrade to boot-only verification, warn naming the service |
| Docker unavailable | Abort before any work with a clear message |

With multiple services, a failure in one does not abort the others. The run exits
non-zero and the summary names which services failed.

## 8. Known limits

These are documented, not hidden.

- The static walk cannot see `importlib.import_module` with a computed string, or
  `getattr`-based dispatch. `--include` is the escape hatch.
- `Depends()` chains are resolved (4.1), but only those FastAPI has registered at
  import time. A dependency injected dynamically at request time is invisible.
- Background and scheduled work is not reachable from the route graph. An APScheduler
  job, a Celery task, or a startup-registered background coroutine is found only if the
  entry module imports it literally, which the static walk then follows. A job registered
  by string reference — `scheduler.add_job("jobs.reports:run")` — is invisible for the
  same reason `importlib.import_module` is. `--include` is the escape hatch, and a
  service whose real work happens off the request path deserves a review of its slice.
- Routes added with Starlette's `add_route` rather than FastAPI's `add_api_route` get no
  dependency scan, because FastAPI runs no injection for them (4.1). Their endpoint file
  is still included. This is a limit of the framework's behavior, not of pyhusk.
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
    dockerize.py              # context assembly, Dockerfile generation
    baseimage.py              # base hash, shared base build, digest resolution
    staleness.py              # slice hashing, image label read/compare
    verify.py                 # three-tier container verification
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
  changes, no hash change when a repo file outside the slice changes, and hash changes
  when the base image digest changes with the tag held constant.
- `test_baseimage.py` — two services with identical requirements and different
  `base_image` values produce different base hashes; identical requirements and identical
  base image collapse to one.
- `test_probe.py` — against a fixture app exercising every route type: a decorated
  `APIRoute`, a Starlette `add_route`, a `WebSocketRoute`, and a `Mount`. Asserts no
  crash on the route lacking `.dependant`, correct recursion into the mount, and correct
  handling of `factory: true`.
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
7. `verify.py` — three-tier verification.
8. `staleness.py` — slice hashing, base digest resolution, image labels, `pyhusk plan`.
9. `baseimage.py` — shared base images and `pyhusk build-bases`.
10. `--compare`, `--show-dockerfile`, `Dockerfile.override`, remote registry staleness.
11. README with quickstart and the limits from section 8.

Stage 6 is the first point at which the tool is useful on a real repo. Measure with
`--compare` there before investing in stages 9 and 10.
