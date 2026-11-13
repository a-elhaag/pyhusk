# Build and verify images

`pyhusk build` turns each service's slice into a Docker image, rebuilding only
what changed and verifying every fresh image by booting it.

```bash
pyhusk build                  # every stale service
pyhusk build billing          # one service
pyhusk build billing checkout # several services
```

Useful flags:

| Flag | Effect |
|---|---|
| `--force` | Rebuild even when the image is unchanged |
| `--show-dockerfile` | Write `.build/<service>/` and stop before Docker |
| `--no-verify` | Skip container verification |
| `--no-shared-base` | Produce self-contained images instead of using shared bases |
| `--compare` | Also build a whole-repo image and print the size delta |
| `--include <path>` | Force a path, directory, or glob into the slice (repeatable) |
| `--repo <dir>` | Run against another repository root |

## Shared base images

By default, dependencies live in a shared base image tagged
`pyhusk-base:<16 hex chars>`, where the tag is a hash of the base image digest
plus the requirements text. Services with identical dependencies reuse one
base; services with different dependencies get different bases. The service
image then contains only code on top of its base.

Bases are built automatically as part of `build`. To build them explicitly
(for example, in a CI step before a matrix of service builds):

```bash
pyhusk build-bases
```

With `--no-shared-base`, each image installs its own requirements and is fully
self-contained. The images are larger and share less, but there are no extra
tags to manage.

## Custom Dockerfiles

Place a `Dockerfile.override` next to a service's entry file to take full
control of its image. pyhusk uses the override verbatim as the Dockerfile
while still assembling the pruned context (sliced files plus
`requirements.txt`) around it. Services with an override never use shared
bases. The override text feeds the slice hash, so editing it marks the service
stale.

To inspect what pyhusk generates before committing to an override, run
`pyhusk build <service> --show-dockerfile` and read
`.build/<service>/Dockerfile`.

## Staleness

A service is stale when its image is missing or was built from different
content. The comparison is a slice hash over:

- every sliced file's repo-relative path and content,
- the generated `requirements.txt`,
- the Dockerfile text (generated or override),
- the base image digest.

The hash is stamped onto the image as the `org.pyhusk.slice` label at build
time, alongside `org.pyhusk.commit` with the last commit that touched the
slice. `pyhusk plan` (and the start of every `build`) recomputes the hash and
compares it against the label.

Because the hash lives on the image rather than in `.build/`, staleness works
on a fresh CI runner: when the image is absent locally, pyhusk reads the label
from the registry copy via `registry` configuration. Base image freshness is
handled the same honest way — the base tag is resolved to a digest (registry
first, local store next, hour-long cache to stay under Docker Hub rate
limits), so an upstream patch release restales every service on that base.

`pyhusk plan` reports the same verdict without building anything, as text or
`--json` for CI:

```bash
pyhusk plan --json
```

```json
{
  "bases": [{"tag": "pyhusk-base:9f2c...", "packages": 12}],
  "services": [
    {"name": "billing", "tag": "billing:latest",
     "base": "pyhusk-base:9f2c...", "hash": "…", "stale": true}
  ]
}
```

## Verification

Every freshly built image is started and checked before pyhusk reports
success. Three tiers exist, and each service gets the strongest its
configuration allows:

| Tier | When | What is checked |
|---|---|---|
| `schema` | The app exposes an OpenAPI URL | Every probed route documented in the schema is served by the container |
| `healthcheck` | No schema, but `healthcheck:` is set | The healthcheck path responds with 2xx–3xx |
| `boot` | Neither | The container is still running after 5 seconds |

Only `APIRoute`s with `include_in_schema` are compared at the schema tier —
plain Starlette routes never appear in OpenAPI, so demanding them there would
be a false failure. Container environment comes from the service's `env:`
mapping.

Verification runs the container with its service port published on a random
localhost port, polls for up to 60 seconds, then removes the container. If
verification fails, the image is force-removed (`docker rmi -f`) so a later
build retries from scratch, and the failure output includes the container's
last 50 log lines.

A service verified at a weaker tier than `schema` succeeds with a warning
naming the tier. Pass `--no-verify` to skip verification entirely.

## Private registries

Set `registry:` on a service and pyhusk tags the verified image as
`<registry>/<service>:latest` in addition to `<service>:latest`. Staleness
checks consult the remote tag too, which is what makes `plan` and `build`
correct on runners that start with an empty local image store.

## Non-HTTP workloads

Services with `kind: worker` or `kind: job` skip the route probe — there is no
app to import — and the slice starts from the entry file alone. Everything
downstream (AST walk, requirements, bases, hashing, verification at the boot
tier) works the same.
