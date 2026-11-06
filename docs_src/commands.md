# CLI Command Reference

Comprehensive reference for all commands and options in `pyhusk`.

---

## Command Matrix

| Command | Summary | Needs Docker? |
|---|---|---|
| [`pyhusk init`](#pyhusk-init) | Autodetect services, generate `pyhusk.yaml`, install agent skills. | No |
| [`pyhusk lint`](#pyhusk-lint) | Check boundary rules, forbidden imports, and circular dependencies. | No |
| [`pyhusk test`](#pyhusk-test) | Run `pytest` only on test files affected since a git ref. | No |
| [`pyhusk affected`](#pyhusk-affected) | List services and test files affected since a git ref. | No |
| [`pyhusk why`](#pyhusk-why) | Trace shortest import path to a package or file. | No |
| [`pyhusk unused`](#pyhusk-unused) | Identify unreferenced Python files across the repo. | No |
| [`pyhusk benchmark`](#pyhusk-benchmark) | Benchmark build times and sizes against whole-repo baselines. | Yes |
| [`pyhusk build`](#pyhusk-build) | Build minimal container images and verify startup. | Yes |
| [`pyhusk plan`](#pyhusk-plan) | Check which services are stale without building. | Optional |
| [`pyhusk log`](#pyhusk-log) | Display git commit history touching a service's slice. | No |
| [`pyhusk list`](#pyhusk-list) | List all configured services and their entry points. | No |
| [`pyhusk skill`](#pyhusk-skill) | Install or update AI Agent skills in the workspace. | No |

---

## Detailed Command Descriptions

### `pyhusk init`
Scans the current repository for `FastAPI()` instances inside `services/**/main.py`, writes `pyhusk.yaml`, adds `.build/` to `.gitignore`, and installs agent skills.
```bash
pyhusk init [--repo PATH] [--no-skill]
```

### `pyhusk lint`
Runs architectural, boundary, cycle, and code quality checks.
```bash
pyhusk lint [SERVICES...] [--strict] [--no-ruff] [--json]
```

### `pyhusk test`
Runs `pytest` only on test files whose transitive local import trees intersect changes since a git reference.
```bash
pyhusk test [--since GIT_REF] [--all]
```

### `pyhusk affected`
Outputs list of services and test files impacted by git changes since `--since`.
```bash
pyhusk affected [--since GIT_REF] [--json]
```

### `pyhusk why`
Prints the shortest hop-by-hop BFS import chain from a service entry point to a file or package.
```bash
pyhusk why <SERVICE> <TARGET>
```

### `pyhusk unused`
Finds local Python files not referenced by any configured service.
```bash
pyhusk unused [--json]
```

### `pyhusk benchmark`
Builds both pruned and naive whole-repo images, timing each build and reporting exact speed and size savings.
```bash
pyhusk benchmark [SERVICES...] [--markdown] [--json] [--no-cache]
```

### `pyhusk build`
Assembles contexts and builds verified container images for stale services.
```bash
pyhusk build [SERVICES...] [--force] [--compare] [--no-verify] [--show-dockerfile]
```

### `pyhusk plan`
Reports which services are stale based on content hashing and Docker registry labels.
```bash
pyhusk plan [SERVICES...] [--json]
```

### `pyhusk log`
Displays recent git commits that touched any file inside a service's slice.
```bash
pyhusk log <SERVICE> [-n LIMIT]
```

### `pyhusk list`
Lists all configured services, their entry modules, and their FastAPI application targets.
```bash
pyhusk list [--repo PATH]
```

### `pyhusk skill`
Installs or updates the pyhusk AI Agent skill inside `.agents/skills/` and `.claude/skills/`.
```bash
pyhusk skill [--repo PATH]
```
