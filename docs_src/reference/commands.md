# Commands

Every command accepts `--repo <dir>` to run against a repository other than
the current directory, and `--help` for its flags. Commands that need Docker
(`build`, `build-bases`, `benchmark`, `build --compare`) fail early with a
clear error when the daemon is unreachable; the rest never touch it.

## `pyhusk init`

Write `pyhusk.yaml` from detected services, add `.build/` to `.gitignore`,
and install the agent skill.

```bash
pyhusk init [--no-skill]
```

Refuses to overwrite an existing `pyhusk.yaml`, and refuses to write one when
no `main.py` containing `FastAPI(` is found. `--no-skill` skips the agent
skill installation.

## `pyhusk skill`

Install or refresh the agent skill in `.agents/skills/pyhusk/` and
`.claude/skills/pyhusk/`.

```bash
pyhusk skill
```

## `pyhusk list`

List the services pyhusk can see: name, entry path, and app attribute
(`()` suffix marks factories).

```bash
pyhusk list
```

## `pyhusk build`

Build minimal images for the named services, or every stale service.

```bash
pyhusk build [SERVICES...] [--force] [--show-dockerfile] [--compare]
           [--no-verify] [--no-shared-base] [--include PATH...]
```

Services already matching their stamped slice hash report `unchanged` and are
skipped unless `--force` is given. See
[Build and verify images](../guides/building.md).

## `pyhusk build-bases`

Build the shared `pyhusk-base` images the current plan requires, skipping tags
already present locally.

```bash
pyhusk build-bases [SERVICES...]
```

## `pyhusk plan`

Report which services are stale without building anything.

```bash
pyhusk plan [SERVICES...] [--json] [--no-shared-base] [--include PATH...]
```

`--json` emits `{bases: [...], services: [...]}` with per-service `tag`,
`base`, `hash`, and `stale` fields, for driving a CI build matrix.

## `pyhusk lint`

Lint architecture, boundaries, circular imports, and code quality.

```bash
pyhusk lint [SERVICES...] [--strict] [--no-ruff] [--json]
```

Exit code 1 when any error-severity issue is found. See
[Lint architecture](../guides/linting.md).

## `pyhusk test`

Run pytest only on test files affected by changes since a git ref.

```bash
pyhusk test [--since REF] [--all]
```

`--since` defaults to `HEAD~1`. With no affected tests the command exits 0;
`--all` runs the full suite instead. See
[Run affected tests](../guides/selective-testing.md).

## `pyhusk affected`

Show services and test files affected by changes since a git ref.

```bash
pyhusk affected [--since REF] [--json]
```

Prints the changed file count, affected services, and affected test files.

## `pyhusk why`

Show the shortest import path from a service entry to a file or package.

```bash
pyhusk why <service> <target>
```

Exits 1 when the target is not reached. See
[Trace imports and dead code](../guides/import-lineage.md).

## `pyhusk unused`

Find Python files in no service's slice.

```bash
pyhusk unused [--json]
```

Test files and skipped directories are excluded.

## `pyhusk log`

Show git commit history for a service's slice.

```bash
pyhusk log <service> [-n LIMIT]
```

Shows the 10 most recent commits touching sliced files by default.

## `pyhusk benchmark`

Build pruned and whole-repo images per service and compare time and size.

```bash
pyhusk benchmark [SERVICES...] [--markdown] [--json]
```

Builds run with `--no-cache` so cold builds are compared. See
[Measure the savings](../guides/benchmarks.md).
