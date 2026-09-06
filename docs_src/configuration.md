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
