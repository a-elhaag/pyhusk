# Trace imports and dead code

Three commands answer "why is this in my image?", "what can I delete?", and
"what changed in my service lately?" — all from the same slice data the
builder uses.

## Why is this in my image?

```bash
pyhusk why billing pandas
pyhusk why billing shared/legacy.py
```

`why` finds the shortest import path from the service entry to a target,
which may be a third-party package name, a repo-relative file path, or a bare
filename. Package matching is normalised, so `pandas`, `Pandas`, and
`pandas-core`-style spellings resolve the same way. Example output:

```
billing reaches pandas:
  billing/main.py:7 -> shared/reports.py (import)
  shared/reports.py:3 -> pandas (third_party)
```

If the target is not reached, the command exits 1 and says so. `lint` uses
this same trace to explain `boundary` and `forbidden` findings.

## What can I delete?

```bash
pyhusk unused
pyhusk unused --json
```

`unused` unions every service's slice and reports repo Python files in no
service's slice. Test files (`test_*`) are never reported — they are not
supposed to be imported by services. Skipped directories (`.venv`, `.build`,
dot-directories, and the rest) are excluded from the search.

Treat the output as a candidate list, not a delete script: entry points pyhusk
does not know about (scripts, notebooks, worker kinds not yet configured)
legitimately appear here.

## What changed in my service?

```bash
pyhusk log billing
pyhusk log billing -n 5
```

`log` resolves the service's slice and shows recent commits touching any file
in it (default 10, `-n`/`--limit` to change). It answers the deploy-review
question — "what code is actually in the image I am about to ship?" — with the
commit history behind it.
