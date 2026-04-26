# Agent Operating Guide

Before doing strategy, backtest, execution, promotion, or architecture work in this repository:

1. Read `memory/profile.md`.
2. Read `memory/actives.md`.
3. Check `memory/errors.md` if the task touches execution credibility, promotion, or risk controls.

After meaningful work:

1. Append durable findings to `memory/learnings.md`.
2. Append recurring failures or traps to `memory/errors.md`.
3. Run `python scripts/quant_memory_evolve.py` to refresh `memory/actives.md` and `memory/nightly_review_draft.md`.

Rules:

- Memory is advisory evidence routing, not a source of truth for promotion.
- Promotion must still be decided by `scripts/quant_profile_promotion_review.py` and generated artifacts.
- Do not promote a profile because memory says it is promising.
- If a memory item conflicts with fresh P2/shadow evidence, fresh evidence wins and the memory should be corrected.
