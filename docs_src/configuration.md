# Configuration

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
    include:                       # extra files, directories, or globs
      - migrations/**
      - templates/
    env:                           # environment variables for probe and container verification
      DATABASE_URL: sqlite:///:memory:
    forbid_imports:                # enforce architectural boundaries
      - services.billing
      - torch
    kind: fastapi                  # fastapi | worker | job
    command: null                  # custom CMD exec list override
```

| Key | Required | Meaning |
|---|---|---|
| `entry` | yes | Path to the file that defines the service's FastAPI app, relative to the repo root. |
| `app` | no | Attribute name holding the `FastAPI` instance. Default `app`. |
| `factory` | no | Set `true` when `app` is a callable that returns the app (the app-factory pattern), rather than the app itself. |
| `base_image` | no | Docker base image. Default `python:3.12-slim`. |
| `port` | no | Port the service listens on inside the container. Default `8000`. |
| `registry` | no | When set, staleness is checked against this registry's copy of the image, not just the local Docker daemon. |
| `healthcheck` | no | Path to poll during [verification](verification.md) when the service's OpenAPI schema is disabled. |
| `include` | no | List of files, directories, or globs to force into the service's slice. |
| `env` | no | Environment variables injected during out-of-process probe and container verification. |
| `forbid_imports` | no | Banned local modules or third-party packages checked by `pyhusk lint`. |
| `kind` | no | Service workload type (`fastapi`, `worker`, `job`). Default `fastapi`. |
| `command` | no | Custom container `CMD` list (e.g. `["celery", "-A", "tasks", "worker"]`). |
