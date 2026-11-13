# Lint architecture

`pyhusk lint` checks each service's slice for structural problems: the same
slice the image is built from, so a lint error is a preview of a broken or
bloated image.

```bash
pyhusk lint              # all services
pyhusk lint billing      # one service
pyhusk lint --strict     # cycles become errors
pyhusk lint --no-ruff    # skip the ruff pass
pyhusk lint --json       # machine-readable output
```

## Checks

| Code | Severity | Meaning |
|---|---|---|
| `boundary` | error | The slice reaches into another service's directory |
| `forbidden` | error | The slice imports a package or module listed in `forbid_imports` |
| `cycle` | warning (`--strict`: error) | Two or more local files import each other in a loop |
| `unresolved` | error | A relative import escapes the repository |
| `unparseable` | error | A sliced file cannot be parsed (it is still shipped, but its imports are not followed) |
| `unmapped` | warning | A third-party import matches no installed distribution, so it gets no pin |
| `ruff` | error | `ruff check` reported a diagnostic on a sliced file |

`boundary` and `forbidden` findings include the shortest import chain from the
service entry to the offending file or package, so you can see exactly which
import to cut.

The exit code is 1 when any error is present, 0 otherwise. Warnings never fail
the run unless `--strict` promotes cycles.

## Boundaries

With the default `isolate_services: true`, a service may not import code from
another service's directory. Services co-located in the same directory are
exempt — they are treated as one unit. Shared code belongs in a directory that
is not a service directory (for example `shared/`), where every service may
import it freely.

Set `isolate_services: false` at the top of `pyhusk.yaml` to disable the
check globally. There is no per-service opt-out: a boundary with exceptions
listed next to it stops being a boundary.

## Forbidden imports

Use `forbid_imports` to keep heavy or inappropriate dependencies out of a
service:

```yaml
services:
  checkout:
    entry: checkout/main.py
    forbid_imports: [pandas, billing]
```

Entries match third-party packages (normalised, so `pydantic-core` and
`pydantic_core` are the same) and top-level local modules alike.

## Ruff integration

When `ruff` is available — in the target repository's `.venv` first, otherwise
on `PATH` — pyhusk runs `ruff check --no-fix` over the sliced Python files
and reports each diagnostic as a `ruff` issue. This lints exactly the code
that ships, not the whole repo. If ruff is not installed, the step is skipped
silently; pass `--no-ruff` to skip it explicitly.

## CI usage

`--json` emits an array of `{service, code, severity, message, detail}`
objects and still exits 1 on errors, so a CI step can both gate the merge and
annotate it:

```bash
pyhusk lint --json > lint.json
```
