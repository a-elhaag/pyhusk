# Configuration Reference

`pyhusk` is configured via `pyhusk.yaml` at the root of your monorepo. Run `pyhusk init` to generate a starter configuration.

---

## Full Schema Example

```yaml title="pyhusk.yaml"
# Global monorepo settings
isolate_services: true               # Prevent services from importing each other

services:
  auth-service:
    entry: services/auth/main.py     # Required: entry module
    app: app                         # Attribute holding FastAPI instance (default: "app")
    factory: false                   # Set true if `app` is a factory callable `create_app()`
    base_image: python:3.12-slim     # Base Docker image (default: "python:3.12-slim")
    port: 8000                       # Container listening port (default: 8000)
    registry: ghcr.io/acme           # Remote container registry for CI staleness checks
    healthcheck: /healthz            # Path to poll when OpenAPI schema is disabled
    kind: fastapi                    # fastapi | worker | job (default: "fastapi")
    command: null                    # Custom CMD list override (e.g. ["celery", "-A", "tasks", "worker"])
    include:                         # Extra files, directories, or globs to force into the slice
      - migrations/**
      - templates/
      - config/certs/*.pem
    env:                             # Environment variables injected during probe and container verification
      DATABASE_URL: sqlite:///:memory:
      ENVIRONMENT: testing
    forbid_imports:                  # Architectural guardrails: banned packages/modules
      - services.billing
      - torch
      - pandas

  celery-worker:
    entry: worker/tasks.py
    kind: worker
    command: ["celery", "-A", "worker.tasks", "worker", "--loglevel=info"]
    include:
      - config/celery_settings.yaml
```

---

## Configuration Keys

| Key | Type | Default | Description |
|---|---|---|---|
| `isolate_services` | `bool` | `true` | When `true`, `pyhusk lint` ensures no service imports internal modules from another service directory. |
| `entry` | `str` | *Required* | Path to the entry file, relative to the monorepo root. |
| `app` | `str` | `"app"` | Name of the attribute holding the `FastAPI` instance. |
| `factory` | `bool` | `false` | Set `true` when `app` is a callable that returns the application (e.g. `def create_app(): ...`). |
| `base_image` | `str` | `"python:3.12-slim"` | The Docker image used in the `FROM` line. |
| `port` | `int` | `8000` | Port exposed in Docker and polled during verification. |
| `registry` | `str \| null` | `null` | Container registry repository. Enables remote label inspection in CI. |
| `healthcheck` | `str \| null` | `null` | HTTP path to poll during container verification if OpenAPI is disabled. |
| `kind` | `str` | `"fastapi"` | Workload type: `fastapi`, `worker`, or `job`. Workers and jobs skip route probing. |
| `command` | `list[str] \| null` | `null` | Overrides the generated Docker `CMD`. |
| `include` | `list[str]` | `[]` | List of non-Python assets, directories, or glob patterns copied into the build context. |
| `env` | `dict[str, str]` | `{}` | Key-value environment variables passed to the discovery probe and verification container. |
| `forbid_imports` | `list[str]` | `[]` | List of package names or module paths that `pyhusk lint` forbids this service from importing. |
