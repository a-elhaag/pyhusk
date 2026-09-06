# Commands

| Command | What it does |
|---|---|
| `pyhusk init` | Detect services, write `pyhusk.yaml`, ignore `.build/`. Safe to rerun. |
| `pyhusk list` | Show the services pyhusk can see. |
| `pyhusk plan` | Report which services are stale. `--json` for CI. |
| `pyhusk build [service ...]` | Build the named services, or every stale one. |
| `pyhusk build-bases` | Build shared base images only. |

## Useful flags on `build`

| Flag | Effect |
|---|---|
| `--show-dockerfile` | Write the build context without building. |
| `--include PATH` | Force a path into the slice, for anything pyhusk can't see statically (see [Known limits](limits.md)). |
| `--force` | Rebuild regardless of staleness. |
| `--compare` | Also build a whole-repo image and print the size difference. |
| `--no-verify` | Skip the container check. |
| `--no-shared-base` | Produce self-contained images instead of sharing a base. |
