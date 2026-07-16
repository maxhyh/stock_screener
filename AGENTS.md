# Agent Operating Guide

Runtime environment:

- The repository default Python environment is the Conda environment `stock`.
- Prefer `conda run -n stock python ...` for non-interactive commands, or run `conda activate stock` before interactive work.
- Do not silently use `base`, a project-local `.venv`, or another environment when validating project behavior.
- The canonical interpreter path on the current workstation is `/opt/homebrew/Caskroom/miniforge/base/envs/stock/bin/python`; `MFTS_PYTHON` may override it explicitly.

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

Codex engineering discipline:

- Follow `skills/audit-a-share-quant-project/references/codex-engineering-discipline.md` for non-trivial code, strategy, execution, promotion, and architecture work.
- Think before changing: state material assumptions, surface tradeoffs, and push back on risk relaxation that only improves optics.
- Keep changes simple and surgical. Touch only lines tied to the active request or its verification; do not do drive-by refactors.
- Preserve evidence lineage across daily selection, portfolio target weights, P2 broker/replay, shadow diagnosis, and promotion review.
- Define verification before coding. Use targeted tests for helper logic, P2 smoke for execution behavior changes, and 60/90/120 evidence plus promotion gate for default-profile decisions.
- Treat lower loss from lower exposure as cash drag until target-weight utilization and NAV/MDD parity prove otherwise.

Expert review escalation:

- Do not ask for external expert review by default after every iteration.
- Continue implementing, testing, and documenting when the next technical path is clear and evidence can be produced locally.
- Escalate to expert review only when there is genuine uncertainty, a strategic fork, a suspected methodology flaw that local evidence cannot resolve, or a promotion/default-profile decision needs independent scrutiny.
- When escalation is needed, first prepare a clean GitHub snapshot, then give the user a complete expert-review prompt with role setting, project state, evidence paths, unresolved questions, and the exact decisions that need review.
- Expert advice is input to the next plan; it does not override fresh P2/shadow/promotion evidence.
