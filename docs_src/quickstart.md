# Quickstart

```bash
uv tool install pyhusk
cd your-monorepo
pyhusk init          # writes pyhusk.yaml from detected services
pyhusk list
pyhusk build         # builds every stale service
```

`pyhusk init` autodetects services by scanning for `FastAPI(` in `main.py` files and
writes a starting `pyhusk.yaml` you can edit — see [Configuration](configuration.md)
for the full schema. It's safe to rerun.

`pyhusk list` shows every service pyhusk can see, and which file/attribute each one's
app comes from.

`pyhusk build` builds every service whose slice, dependencies, Dockerfile, or base
image digest changed since the last build — see [Staleness](staleness.md). Add
`--compare` on a single service to see whether pruning is actually worth it on your
repo:

```bash
pyhusk build my-service --compare
```
