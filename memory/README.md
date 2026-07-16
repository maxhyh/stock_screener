# Project Memory System

This directory is the project-owned memory layer for the A-share quant platform. It is meant to be read before work starts, updated after meaningful research or execution runs, and refreshed by a deterministic nightly task.

## Files

- `profile.md`: stable project identity, operating constraints, and current promotion policy.
- `actives.md`: short session boot memory. Read this first before changing strategy, backtest, execution, or governance code.
- `learnings.md`: append-only long-term learnings. New reusable entries are promoted into `actives.md`.
- `errors.md`: recurring mistakes, failure modes, and mitigations.
- `nightly_review_draft.md`: generated nightly review scaffold for the next human/agent review.
- `state.json`: generated cursor and hashes used by `scripts/quant_memory_evolve.py`.

## Operating Loop

1. Before each session, read `memory/profile.md` and `memory/actives.md`.
2. During work, write concrete findings to `memory/learnings.md` or `memory/errors.md`.
3. Run `python scripts/quant_memory_evolve.py` to refresh active memory and nightly review.
4. Promotion decisions must still come from evidence artifacts, not memory alone.
5. Treat external expert review as an escalation mechanism. Use it when local evidence cannot resolve uncertainty, when a strategic fork needs independent scrutiny, or before a serious promotion/default-profile decision. Otherwise continue the local implementation and evidence loop.

## Learning Entry Format

Use a heading and machine-readable fields:

```markdown
### 2026-04-26 | Short finding title
- tags: p2, promotion, capacity
- reusable: yes
- confidence: high
- evidence: artifact path or metric
- action: concrete future behavior

Short explanation.
```

Entries marked `reusable: yes` are candidates for `actives.md`. Entries marked `reusable: no` stay as archive context.
