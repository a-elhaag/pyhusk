# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated by the user, who asked for all old docs to be deleted and rebuilt. Plan: MkDocs (Material as the engine) with a fully custom theme and overrides for the docs, plus a hand-built static landing page at `site/index.html`. Deploy target: GitHub Pages via `.github/workflows/pages.yml` (landing at `/`, docs at `/docs/`).

## Users

Python backend and platform engineers running a FastAPI `uv` monorepo, and the engineering leads who approve tooling spend. The user confirmed both are equal readers. Engineers need commands, config, and honest limits fast. Leads need measured proof of CI time and image size savings.

## Product purpose

pyhusk builds minimal Docker images for FastAPI monorepos and rebuilds only the services that changed. It also lints architecture boundaries, runs only the tests affected by a diff, and traces why a package ended up in an image.

Mechanism: import the app out of process, follow the imports and `Depends()` chains its routes reach, and ship that slice only.

## Constraints and facts to preserve

- Python 3.12+, `uv` monorepo, Docker needed for build and benchmark only.
- License Apache-2.0. Version 0.2.0. Install: `uv tool install pyhusk`.
- Repo: https://github.com/a-elhaag/pyhusk. Site: https://a-elhaag.github.io/pyhusk/. Docs: https://a-elhaag.github.io/pyhusk/docs/.
- Commands: init, lint, test, affected, why, unused, benchmark, build, plan, log, list, skill.
- Ships agent skills (`SKILL.md`) into `.agents/skills/pyhusk/` and `.claude/skills/pyhusk/` via `pyhusk init` or `pyhusk skill`.
- No invented customers, testimonials, or benchmarks. Numbers shown must be labelled as example output.

## Voice

Plain, specific, honest about limits.

## Visual commitments stated by the user

Modern, premium, emotional, vector art, must not look AI-generated. Docs should follow the Google Cloud documentation style (left nav, centred article, right-hand table of contents). Landing page must have a GitHub star button and installation steps.
