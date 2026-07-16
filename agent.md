# Agent Guide

The canonical agent guide is `AGENTS.md`.

This compatibility file exists because some tools or humans look for `agent.md`. Follow the same boot sequence:

1. Read `memory/profile.md`.
2. Read `memory/actives.md`.
3. Read `memory/errors.md` when touching strategy execution, risk, or promotion governance.
4. After meaningful work, append durable findings to `memory/learnings.md` and run `python scripts/quant_memory_evolve.py`.

For non-trivial engineering work, also follow `skills/audit-a-share-quant-project/references/codex-engineering-discipline.md`. In short: surface material assumptions, keep patches simple and surgical, preserve research-to-execution evidence lineage, define verification before coding, and never treat lower loss from lower exposure as alpha.

External expert review is an escalation mechanism, not a per-iteration habit. Keep moving locally when the next engineering or evidence step is clear. Escalate only for genuine uncertainty, strategic forks, suspected methodology flaws that local artifacts cannot resolve, or promotion/default-profile decisions needing independent scrutiny. When escalating, prepare a clean GitHub snapshot and give the user a complete expert-review prompt.
