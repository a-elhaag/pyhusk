# Measure the savings

`pyhusk benchmark` builds each service twice — once pruned, once as a
whole-repo baseline — and reports the time and size delta. It exists so the
decision to adopt pruning is based on your repository's numbers, not ours.

```bash
pyhusk benchmark billing
pyhusk benchmark --markdown     # table for a README or proposal
pyhusk benchmark --json         # machine-readable results
```

Both builds use `--no-cache` by default, so the timing comparison is between
equivalent cold builds. (The flag is inverted: caching is already off unless
your Docker defaults say otherwise — cold builds are the honest comparison.)

## What it measures

For each service:

- **Build time**, pruned vs naive, in seconds.
- **Compressed image size**, pruned vs naive.
- **Pinned packages**, pruned requirements vs the full `uv.lock`.
- **Files**, sliced files vs total Python files in the repo.

The naive baseline is a whole-repo context (everything except `.build`,
`.venv`, and `.git`) with every lock-file package installed — the Dockerfile
you would write without pyhusk.

## Example output

The figures below are illustrative example output, not a claim about your
repository. Run the command to get yours.

```
billing:
  Build time:  8.4s (pruned) vs 39.1s (naive) -> saved 30.7s (79%)
  Image size:  121 MB vs 798 MB -> saved 677 MB (85%)
  Packages:    11 pins vs 46 pins in lockfile
  Files:       34 files vs 210 in repo
```

`--markdown` renders the same data as a table:

```markdown
| Service | Build Time (Pruned vs Naive) | Time Saved | Compressed Size (Pruned vs Naive) | Size Saved | Packages |
|---|---|---|---|---|---|
| `billing` | 8.4s vs 39.1s | **-79%** (30.7s) | 121 MB vs 798 MB | **-85%** (677 MB) | 11 vs 46 |
```

## Lighter-weight alternative

`pyhusk build <service> --compare` builds the same naive baseline for one
service during a normal build and prints a one-line size comparison. Use it
for a quick check; use `benchmark` when you need timing figures or a table for
several services at once.
