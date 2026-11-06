# Import Lineage & Bloat Debugging

In a monorepo, a single innocent import can cause a microservice image to balloon by hundreds of megabytes. `pyhusk why` and `pyhusk unused` give you instant visibility into dependency provenance and dead code.

---

## Tracing Bloat: `pyhusk why`

When you notice a service image has grown unexpectedly, use `pyhusk why` to trace the shortest import path from the service's entry point to the culprit file or third-party distribution.

### Tracing a 3rd-Party Package
```bash
pyhusk why auth pandas
```

```text
auth reaches pandas:
  services/auth/main.py:12 -> common/auth.py:5 (import)
  common/auth.py:18 -> common/analytics.py:2 (import)
  common/analytics.py:1 -> pandas (third_party)
```

Now you know exactly where `pandas` entered the dependency tree and can refactor or isolate the import.

### Tracing a Local Module
```bash
pyhusk why billing common/reporting.py
```

```text
billing reaches common/reporting.py:
  services/billing/main.py:6 -> services/billing/routes.py:10 (import)
  services/billing/routes.py:12 -> common/reporting.py (import)
```

If a package or file is not reachable by the service:
```bash
pyhusk why auth httpx
```
```text
error: 'httpx' is not reached by service 'auth'
```

---

## Finding Dead Code: `pyhusk unused`

Monorepos accumulate abandoned files and zombie modules over time. `pyhusk unused` computes the union of all reachable service code and flags every unreferenced `.py` file:

```bash
pyhusk unused
```

```text
Found 3 unreferenced Python file(s):
  common/legacy_auth.py
  common/unused_helpers.py
  services/billing/old_schema.py
```

Output as JSON for automated audits:
```bash
pyhusk unused --json
```

```json
{
  "unused_files": [
    "common/legacy_auth.py",
    "common/unused_helpers.py",
    "services/billing/old_schema.py"
  ]
}
```
