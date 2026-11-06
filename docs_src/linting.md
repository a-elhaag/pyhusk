# Architecture & Boundary Linting

Monorepos break down when services stop being independent. `pyhusk lint` enforces clean architectural boundaries, prevents cyclic dependencies, and blocks banned libraries without requiring separate repositories.

---

## The Monorepo Boundary Problem

In a standard Python monorepo:
- `services/auth/main.py` might import a helper from `services/billing/models.py`.
- Suddenly, the `auth` container cannot run without `billing` code, turning a microservice architecture into a distributed monolith.
- Circular imports (`a.py -> b.py -> a.py`) cause fragile import-order bugs that crash containers at startup.

---

## Running the Linter

```bash
# Lint all services in the monorepo
pyhusk lint

# Lint specific services
pyhusk lint auth billing

# Fail on warnings (such as circular imports)
pyhusk lint --strict

# Machine-readable output for CI
pyhusk lint --json
```

---

## Guardrails Enforced

### 1. Cross-Service Isolation
By default (`isolate_services: true`), pyhusk strictly forbids any service from importing files belonging to another configured service.

```text
[ERROR] auth (boundary): cross-service import: includes services/billing/models.py from service 'billing'
  services/auth/routes.py:14 -> services/billing/models.py (import)
```

### 2. Forbidden Imports (`forbid_imports`)
Prevent lightweight edge services from accidentally pulling in heavy ML, scientific, or unwanted packages.

```yaml title="pyhusk.yaml"
services:
  auth:
    entry: services/auth/main.py
    forbid_imports:
      - torch
      - pandas
      - services.billing
```

If any developer introduces an import chain reaching `torch`, `pyhusk lint` catches it and prints the exact lineage:

```text
[ERROR] auth (forbidden): imports forbidden package/module 'torch'
  services/auth/main.py:8 -> common/helpers.py:3 -> torch (third_party)
```

### 3. Circular Import Detection
Detects circular dependencies in local application code before they trigger runtime `ImportError` or `cannot import name` crashes:

```text
[WARNING] billing (cycle): circular import: common/models.py -> common/reporting.py -> common/models.py
```

### 4. Ruff Code Quality Integration
When `ruff` is available in your virtualenv (`.venv/bin/ruff`) or PATH, `pyhusk lint` automatically runs Ruff checks specifically over the files included in each service's slice. Skip with `--no-ruff` if desired.

---

## Integrating with CI & Pre-Commit

Add `pyhusk lint` to your pre-commit hooks or GitHub Actions pipeline:

```yaml title=".github/workflows/lint.yml"
name: Architecture Lint

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run pyhusk lint --strict
```
