# pyhusk

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)

Minimal Docker images for FastAPI monorepos, and only rebuilding the ones that changed.

pyhusk discovers each service's routes by importing its app, follows the imports and
`Depends()` chains those routes actually reach, and builds an image containing that slice
and nothing else. It then remembers what went into each image, so editing one shared
module rebuilds only the services that use it.

**[Landing page](https://a-elhaag.github.io/pyhusk/) · [Full docs](https://a-elhaag.github.io/pyhusk/docs/)**

![pyhusk building two services, then reporting both unchanged on the second run](site/demo.gif)

## Requirements

- Python 3.12 or newer
- A monorepo managed by `uv`, with a root `pyproject.toml`, `uv.lock` and `.venv`
- Docker

## Quickstart

```bash
uv tool install pyhusk
cd your-monorepo
pyhusk init          # writes pyhusk.yaml from detected services
pyhusk list
pyhusk build         # builds every stale service
```

New to a service? Run `pyhusk build <service> --compare` first — it builds a
whole-repo image alongside the pruned one and prints the size difference, so you can
see whether pruning is worth it on your repo before relying on it.

## Learn more

The full reference — configuration schema, every command and flag, how staleness and
verification work, and the known limits worth reading before you trust an image —
lives in the [docs](https://a-elhaag.github.io/pyhusk/docs/):

- [Quickstart](https://a-elhaag.github.io/pyhusk/docs/quickstart/)
- [Configuration](https://a-elhaag.github.io/pyhusk/docs/configuration/)
- [Commands](https://a-elhaag.github.io/pyhusk/docs/commands/)
- [Staleness](https://a-elhaag.github.io/pyhusk/docs/staleness/)
- [Verification](https://a-elhaag.github.io/pyhusk/docs/verification/)
- [CI](https://a-elhaag.github.io/pyhusk/docs/ci/)
- [Known limits](https://a-elhaag.github.io/pyhusk/docs/limits/)

## License

[Apache 2.0](LICENSE)
