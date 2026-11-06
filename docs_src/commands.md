# Commands

| Command | What it does |
|---|---|
| `pyhusk init` | Detect services, write `pyhusk.yaml`, ignore `.build/`. Safe to rerun. |
| `pyhusk list` | Show the services pyhusk can see. |
| `pyhusk why <service> <target>` | Trace shortest import path from service entry/route to a file or package. |
| `pyhusk unused` | Find Python files not referenced by any service. |
| `pyhusk lint [service ...]` | Lint monorepo boundaries, circular imports, forbidden imports, and code quality. |
| `pyhusk log <service>` | Show git commit history touching a service's slice. |
| `pyhusk affected [--since REF]` | List services and test files affected by changes since a git ref. |
| `pyhusk test [--since REF]` | Run `pytest` only on test files affected by changes since a git ref. |
| `pyhusk plan` | Report which services are stale. `--json` for CI. |
| `pyhusk build [service ...]` | Build the named services, or every stale one. |
| `pyhusk build-bases` | Build shared base images only. |

## Useful flags on `lint`

| Flag | Effect |
|---|---|
| `--strict` | Treat warnings (such as circular imports) as errors. |
| `--no-ruff` | Skip external `ruff` linter check. |
| `--json` | Output issues in machine-readable JSON. |

## Useful flags on `build`

| Flag | Effect |
|---|---|
| `--show-dockerfile` | Write the build context without building. |
| `--include PATH` | Force a path into the slice, for anything pyhusk can't see statically (see [Known limits](limits.md)). |
| `--force` | Rebuild regardless of staleness. |
| `--compare` | Also build a whole-repo image and print the size difference. |
| `--no-verify` | Skip the container check. |
| `--no-shared-base` | Produce self-contained images instead of sharing a base. |
