# Verification

After each build pyhusk starts the container and checks it serves what the probe
found:

- **Schema** — with the OpenAPI schema enabled, compares the full route set.
- **Healthcheck** — with the schema disabled, polls the configured `healthcheck` path.
- **Boot-only** — with neither, only confirms the container stays up, and says so,
  because a weaker check should never be mistaken for the strong one.

A build that fails verification removes its image tag, so the next `pyhusk build`
retries rather than seeing a matching content hash and reporting the broken image as
unchanged.

Verification is not integration testing. It proves the container boots and serves the
expected routes, nothing more — see [Known limits](limits.md).
