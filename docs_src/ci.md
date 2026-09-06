# CI

`pyhusk plan --json` prints the stale services and the base images they need, so a
pipeline builds bases once and then fans the services out in parallel:

```yaml
jobs:
  plan:
    runs-on: ubuntu-latest
    outputs:
      services: ${{ steps.plan.outputs.services }}
    steps:
      - uses: actions/checkout@v4
      - run: uv sync
      - id: plan
        run: |
          echo "services=$(pyhusk plan --json | jq -c '[.services[] | select(.stale) | .name]')" >> "$GITHUB_OUTPUT"
          pyhusk build-bases

  build:
    needs: plan
    if: needs.plan.outputs.services != '[]'
    strategy:
      matrix:
        service: ${{ fromJson(needs.plan.outputs.services) }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: uv sync
      - run: pyhusk build ${{ matrix.service }}
```

The slice hash lives on the image as a label, not in a local file — see
[Staleness](staleness.md) — so this works on fresh runners that have no `.build/`
directory.
