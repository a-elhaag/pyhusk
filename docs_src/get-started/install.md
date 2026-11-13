# Install

## Install pyhusk

pyhusk is a standalone CLI. Install it as an isolated tool so it never
interferes with your monorepo's dependencies:

```bash
uv tool install pyhusk
```

Then confirm it runs:

```bash
pyhusk --help
```

## Prepare your monorepo

pyhusk inspects a monorepo from the outside. The repository itself needs three
things at its root:

1. `pyproject.toml` — the workspace root.
2. `uv.lock` — dependency pins are read from the lock file. Generate it with
   `uv lock` if it is missing.
3. `.venv` — pyhusk imports your apps using the repository's own interpreter.
   Create it with `uv sync`.

Docker is required only for commands that build images (`build`,
`build-bases`, `benchmark`, and `build --compare`). Linting, selective
testing, import tracing, and planning all work without it.

## Upgrade

```bash
uv tool upgrade pyhusk
```

## Next steps

- [Quickstart](quickstart.md): initialise pyhusk in your repo and build
  your first pruned image.
