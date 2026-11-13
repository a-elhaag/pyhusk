# Configuration

pyhusk reads `pyhusk.yaml` at the repository root. Unknown keys are rejected,
so a typo fails fast with the validation error instead of silently doing
nothing.

```yaml
isolate_services: true

services:
  billing:
    entry: billing/main.py
    app: app
    base_image: python:3.12-slim
    port: 8000
    registry: ghcr.io/myorg
    factory: false
    healthcheck: /health
    include:
      - billing/templates
    env:
      LOG_LEVEL: info
    forbid_imports:
      - pandas
    kind: fastapi
    command: null
```

## Service keys

| Key | Default | Meaning |
|---|---|---|
| `entry` | (required) | Service entry file, relative to the repo root. Must exist and stay inside the root. |
| `app` | `app` | Attribute in the entry module holding the app (or the factory). |
| `base_image` | `python:3.12-slim` | Base image tag, resolved to a digest for staleness. |
| `port` | `8000` | Port the app serves and verification probes. Exposed in the image. |
| `registry` | `null` | When set, verified images are also tagged `<registry>/<name>:latest`, and staleness consults the remote tag. |
| `factory` | `false` | When `true`, `app` is called with no arguments to obtain the application. |
| `healthcheck` | `null` | Path probed when the app exposes no OpenAPI schema. Without it, verification degrades to a boot check. |
| `include` | `[]` | Extra files, directories, or globs forced into the slice. |
| `env` | `{}` | Environment variables set both when probing the app and when running the verification container. |
| `forbid_imports` | `[]` | Packages or top-level modules `lint` rejects from this service's slice. |
| `kind` | `fastapi` | `fastapi` probes routes; `worker` and `job` skip probing and slice from the entry file. |
| `command` | `null` | Custom container command (exec form). Default runs `uvicorn <module>:<app> --host 0.0.0.0 --port <port>`, with `--factory` when `factory: true`. |

## Top-level keys

| Key | Default | Meaning |
|---|---|---|
| `services` | (required) | Map of service name to service configuration. |
| `isolate_services` | `true` | When `true`, `lint` reports an error if a service's slice reaches another service's directory. |

## Auto-detection

When `pyhusk.yaml` is absent, most commands auto-detect services: every
`main.py` containing the text `FastAPI(` becomes a service named after its
directory, with default settings. Detection skips `.venv`, `.build`,
`node_modules`, `__pycache__`, `site-packages`, and dot-directories, and
unparseable files are skipped quietly. Two services in directories with the
same name is an error — write `pyhusk.yaml` to name them explicitly.

`pyhusk init` writes the detected services to `pyhusk.yaml` so you can edit
them. Detection is a text search by design; the build is where a broken
service must fail loudly, not discovery.

## Includes

`include` (and the `--include` flag on `build` and `plan`) accepts files,
directories (added recursively), and globs, all resolved inside the repo root.
Use it for assets the import walk cannot see: templates, data files, migration
directories. Paths that do not exist or escape the root are errors.
