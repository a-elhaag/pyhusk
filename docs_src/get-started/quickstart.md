# Quickstart

This guide takes a `uv` monorepo with at least one FastAPI service from zero
to a verified minimal image.

## 1. Initialise

From your repository root:

```bash
pyhusk init
```

`init` scans for `main.py` files containing a `FastAPI(` call, names each
service after its directory, and writes `pyhusk.yaml`. It also adds `.build/`
to `.gitignore` and installs an agent skill into `.agents/skills/pyhusk/` and
`.claude/skills/pyhusk/` (pass `--no-skill` to skip that).

If your layout does not follow the `main.py` convention, write `pyhusk.yaml`
by hand instead — see [Configuration](../reference/configuration.md).

## 2. List what pyhusk sees

```bash
pyhusk list
```

Example output:

```
billing    billing/main.py    app
checkout   checkout/main.py   create_app()
```

## 3. Lint before you build

```bash
pyhusk lint
```

This checks service boundaries, forbidden imports, import cycles, and files
the slicer cannot follow. Fix errors now: anything the slicer cannot see is
something the image may be missing. See
[Lint architecture](../guides/linting.md) for the full check list.

## 4. Build

```bash
pyhusk build
```

pyhusk resolves every service, rebuilds the stale ones, and verifies each
fresh image by booting it. Example output:

```
billing: building
billing: built billing:latest  34/210 files  12 packages  118 MB compressed
checkout: unchanged
```

Run it again immediately and everything reports `unchanged` — the slice hash
stamped on each image matches, so there is nothing to do.

## 5. Prove it is worth it

Before relying on pruning, measure it on one service:

```bash
pyhusk build billing --compare
```

This builds a whole-repo baseline image alongside the pruned one and prints
the size delta. For time and size figures in one table, use
[`pyhusk benchmark`](../guides/benchmarks.md).

## Where build output goes

- `.build/<service>/` — the assembled context: sliced files,
  `requirements.txt`, and the generated `Dockerfile`. Removed and rewritten
  on every run, never reused.
- `.build/_bases/` — shared base image contexts.
- `.build/_naive/` — whole-repo baseline contexts from `--compare` and
  `benchmark`.

All of it is disposable. The source of truth for staleness is the
`org.pyhusk.slice` label on the image itself, not anything in `.build/`,
which is why a fresh CI runner with an empty `.build/` still works.

## Next steps

- [Build and verify images](../guides/building.md): shared bases, custom
  Dockerfiles, verification tiers, and staleness in depth.
- [Commands](../reference/commands.md): every command and flag.
