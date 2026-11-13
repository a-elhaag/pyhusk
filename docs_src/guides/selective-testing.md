# Run affected tests

`pyhusk test` runs only the tests that can observe a change, by intersecting
the git diff with import slices. In a large monorepo this turns a full-suite
CI step into a handful of files.

```bash
pyhusk test                  # tests affected since HEAD~1
pyhusk test --since origin/main
pyhusk test --all            # fall back to the full suite when nothing is affected
```

Without `--all` and with no affected tests, the command reports that and exits
0 without invoking pytest.

## How selection works

1. The diff is collected with `git diff --name-only <since>` plus everything
   `git status --porcelain` reports, so uncommitted and untracked files count.
2. Every test file in the repo (`test_*.py` or `*_test.py`, outside skipped
   directories) gets its own import slice via the same AST walk the builder
   uses.
3. A test file is selected when it changed itself or its slice intersects the
   diff.
4. The selected files are run with the repository's own `.venv` interpreter:
   `python -m pytest <files...>`.

To preview a selection without running anything:

```bash
pyhusk affected --since origin/main
```

This prints the changed file count, the affected services (any service whose
slice intersects the diff), and the affected test files. `--json` emits all
three lists for scripting.

## Global triggers

A change to `pyhusk.yaml` or the root `pyproject.toml` marks every service
affected: configuration edits cannot be attributed to one slice. (Test
selection is unaffected by this rule — it is purely slice intersection.)

## CI recipe

```yaml
- name: Affected tests
  run: pyhusk test --since origin/${{ github.base_ref }} --json
```

Or gate the Docker builds on the same diff with
[`pyhusk plan --json`](building.md#staleness), which reports per-service
staleness for a build matrix.
