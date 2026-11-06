# Quickstart

Get your monorepo configured, linted, tested, and containerized with pyhusk in under 2 minutes.

---

## 1. Installation

Install `pyhusk` globally with your favorite Python package manager:

=== "uv (Recommended)"
    ```bash
    uv tool install pyhusk
    ```

=== "pipx"
    ```bash
    pipx install pyhusk
    ```

=== "pip"
    ```bash
    pip install pyhusk
    ```

Verify the installation:
```bash
pyhusk --help
```

---

## 2. Initialize Your Monorepo

Navigate to your repository root and initialize:

```bash
cd your-monorepo
pyhusk init
```

`pyhusk init` will:
1. Automatically scan for `FastAPI()` instances inside `services/**/main.py`.
2. Generate a clean `pyhusk.yaml` declaration.
3. Add `.build/` to your `.gitignore`.
4. Install native AI Agent skills into `.agents/skills/pyhusk/` and `.claude/skills/pyhusk/`.

```yaml title="Generated pyhusk.yaml"
services:
  auth:
    entry: services/auth/main.py
    app: app
  billing:
    entry: services/billing/main.py
    app: app
```

---

## 3. Lint Architectural Boundaries

Verify that services don't illegally import each other and that no circular dependencies exist:

```bash
pyhusk lint
```

```text
[OK] auth: passed (no boundary or circular issues)
[OK] billing: passed (no boundary or circular issues)
lint passed: no architectural or code quality issues found.
```

---

## 4. Run Selective Tests

When working on a feature branch, run only the tests impacted by your changes:

```bash
pyhusk test --since origin/main
```

Instead of running hundreds of tests for 10 minutes, pyhusk runs only the 3 tests whose import trees touch modified files in under 2 seconds.

---

## 5. Build Pruned Containers

Build only the services whose source code or dependencies actually changed:

```bash
pyhusk build
```

To see the exact size difference between a naive whole-repo image and pyhusk's surgical slice:

```bash
pyhusk build auth --compare
```

```text
auth: pruned 124.0 MB vs naive 812.0 MB compressed  saved 688.0 MB (85%)
```

---

## Next Steps

- Explore **[Architecture Linting](linting.md)** to prevent cross-service coupling.
- Set up **[Selective CI Testing](selective-testing.md)** in GitHub Actions.
- Learn about **[Docker Slicing & Verification](docker-slicing.md)**.
