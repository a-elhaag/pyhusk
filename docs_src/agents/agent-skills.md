# Agent skills

pyhusk ships a short skill file that teaches AI coding agents what it can do
and when to reach for it. Agents working in a pyhusk-managed monorepo can
lint boundaries, plan builds, trace imports, and run affected tests without
guessing at flags.

## What gets installed

`pyhusk init` (and `pyhusk skill`) write the same `SKILL.md` to two locations:

- `.agents/skills/pyhusk/SKILL.md` — generic agent skills directory
- `.claude/skills/pyhusk/SKILL.md` — Claude Code skills directory

The skill contains a command quick-reference:

| Command | Purpose |
|---|---|
| `pyhusk lint [services...]` | Verify boundaries, circular imports, and `forbid_imports`. |
| `pyhusk plan [--json]` | Identify stale services requiring Docker builds. |
| `pyhusk why <service> <target>` | Trace shortest BFS import chain from entry to file or package. |
| `pyhusk affected [--since REF]` | Show services and test files touched since git ref. |
| `pyhusk test [--since REF]` | Run `pytest` only on test files affected by changes. |
| `pyhusk unused` | Find unreferenced Python files across the monorepo. |
| `pyhusk build [services...]` | Build pruned Docker images and verify via OpenAPI/healthcheck. |
| `pyhusk log <service>` | Display git commit history affecting a service's slice. |

## Refreshing

The skill is versioned with pyhusk. After upgrading, run `pyhusk skill` to
rewrite both copies with the current command list. To install pyhusk without
touching agent directories, use `pyhusk init --no-skill`.
