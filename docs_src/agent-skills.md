# AI Agent Integration

`pyhusk` is built agent-first. When working with AI coding assistants (like Google Antigravity, Claude Code, Cursor, or Aider), pyhusk provides native agent skills so models understand your monorepo topology without hallucinating dependencies.

---

## What is an Agent Skill?

An agent skill is an instruction specification defined in a `SKILL.md` file. It teaches AI coding assistants:
1. When to invoke `pyhusk` commands.
2. How to interpret import boundaries and cyclic errors.
3. How to selectively test code changes without wasting token budget or running slow full test suites.

---

## Automatic Installation

Whenever you run:
```bash
pyhusk init
```
or
```bash
pyhusk skill
```
pyhusk automatically places the official skill into standard agent discovery directories:
- `.agents/skills/pyhusk/SKILL.md` (Antigravity & Agent standard)
- `.claude/skills/pyhusk/SKILL.md` (Claude Code standard)

---

## How AI Agents Use pyhusk

When an AI agent pairs with you in your repository, it automatically leverages pyhusk for:

| User Task | Agent Action |
|---|---|
| *"Check if my changes broke any service boundaries"* | Runs `pyhusk lint` and fixes any cross-service imports. |
| *"Run tests for what I just modified"* | Runs `pyhusk test --since origin/main` in &lt;1 second. |
| *"Why is my Docker image so huge?"* | Runs `pyhusk why <service> <package>` to explain the import chain. |
| *"Are there any dead files we can delete?"* | Runs `pyhusk unused` and safely cleans unreferenced modules. |
| *"Prepare my pull request"* | Runs `pyhusk affected` and `pyhusk benchmark --markdown` to generate PR descriptions. |
