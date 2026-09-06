# Staleness

Each service gets a SHA-256 over the contents of its slice, its resolved
`requirements.txt`, its Dockerfile, and the digest of its base image. That hash is
stamped on the built image as a label. A service is stale when the hash differs or the
image is gone.

Hashing content rather than git state means it works on uncommitted edits and matches
across machines. Including the base image digest means an upstream `python:3.12-slim`
security update triggers a rebuild, which a Dockerfile-text comparison would miss.

The label lives on the image itself, not in a local file, so this works on fresh CI
runners that have no `.build/` directory from a previous run.
