# Benchmarks & ROI

Don't guess how much time and bandwidth you're saving—measure it directly. `pyhusk benchmark` builds your services both ways (surgical slice vs. traditional whole-repo) and outputs exact metrics.

---

## Running a Benchmark

```bash
# Benchmark all services in the monorepo
pyhusk benchmark

# Benchmark a specific service
pyhusk benchmark auth

# Output clean Markdown table for your team or README
pyhusk benchmark --markdown

# Output structured JSON for performance monitoring
pyhusk benchmark --json
```

---

## Example Output

```text
Benchmark Results:

auth:
  Build time:  8.2s (pruned) vs 39.5s (naive) -> saved 31.3s (79%)
  Image size:  124.0 MB vs 812.0 MB -> saved 688.0 MB (85%)
  Packages:    9 pins vs 46 pins in lockfile
  Files:       12 files vs 84 in repo

billing:
  Build time:  14.1s (pruned) vs 41.2s (naive) -> saved 27.1s (66%)
  Image size:  182.0 MB vs 812.0 MB -> saved 630.0 MB (78%)
  Packages:    16 pins vs 46 pins in lockfile
  Files:       19 files vs 84 in repo
```

---

## Formatted Markdown Table

When run with `--markdown`:

| Service | Build Time (Pruned vs Naive) | Time Saved | Compressed Size (Pruned vs Naive) | Size Saved | Packages |
|---|---|---|---|---|---|
| `auth` | 8.2s vs 39.5s | **-79%** (31.3s) | 124.0 MB vs 812.0 MB | **-85%** (688.0 MB) | 9 vs 46 |
| `billing` | 14.1s vs 41.2s | **-66%** (27.1s) | 182.0 MB vs 812.0 MB | **-78%** (630.0 MB) | 16 vs 46 |

---

## Where the Savings Come From

1. **Layer Size**: Installing 9 wheels instead of 46 avoids writing hundreds of megabytes of compiled bytecode and native C-extensions (`torch`, `pandas`, `cryptography`, `grpcio`).
2. **Registry Transfer**: Pushing and pulling smaller layers over internal Docker registries or Kubernetes nodes drastically accelerates cluster autoscaling and pod startup time.
3. **Cache Hit Ratio**: Touching `services/billing/models.py` leaves `auth` completely untouched, allowing your CI cache to skip rebuilding unrelated images entirely.
