# Maintenance Loop

Use this file when the skill is applied repeatedly over time, not only for a single audit.

## Goal

Continuously improve the repo's trading realism, stability, and maintainability while avoiding repeated rediscovery of the same issues.

## Standard Loop

1. Build a fresh snapshot:
   run `python skills/audit-a-share-quant-project/scripts/build_maintenance_snapshot.py`
   Review both hotspot counts and architecture-size sections. Large-file counts
   are advisory refactor signals, not a reason to rewrite execution-critical
   scripts without regression coverage.
2. Re-read the Codex engineering discipline:
   `skills/audit-a-share-quant-project/references/codex-engineering-discipline.md`
3. Re-read the current production path:
   `daily_all.py`
   `daily_incremental_update.py`
   `daily_ml_select.py`
   `mfts_screener.py`
   `quant_portfolio_backtest.py`
   `pretrade.py`
   `paper_broker.py`
4. Identify the highest-leverage issue in one of these buckets:
   logic bias
   execution realism
   performance
   robustness
   architecture coupling
5. Fix the issue with the smallest safe patch that materially improves the repo.
6. Add or update a regression test.
7. Re-run the relevant tests and regenerate the snapshot if the maintenance pass was substantial.
8. Leave the next highest-priority target in the response.
9. If the maintenance pass changes a strategy/profile candidate, refresh shadow evidence before recommending promotion:
   run `python scripts/quant_p2_rolling_replay.py ...`
   then run `python scripts/quant_p2_shadow_diagnosis.py ...`
   and compare NAV path, ADV blocking, and industry concentration.
10. Decide whether expert review is actually needed. If the next evidence-producing step is clear, keep implementing locally. Escalate only when local artifacts cannot resolve a strategic or methodological uncertainty, or when a serious promotion/default-profile decision needs outside scrutiny.
11. When escalating, prepare a clean GitHub snapshot first and give the user a complete expert-review prompt with role, repository entry points, current evidence, unresolved questions, and decisions needing review.

## What Counts As Progress

- A silent PnL distortion is removed.
- A scan, ML, backtest, and execution mismatch is aligned.
- A repeated hot path becomes faster or less memory-heavy.
- A broad fallback becomes explicit and testable.
- A recurring repo pattern is captured in this skill for future use.
- A strategy candidate becomes easier to judge because research-side and execution-side evidence now live in the same maintenance record.
- A growing production script is identified early enough to extract pure helpers,
  shared contracts, or testable adapters before it becomes a fragile orchestration
  monolith.

## What To Avoid

- Large speculative refactors with no regression protection.
- Clever abstractions or broad configurability before the bottleneck is diagnosed.
- Repeating old findings without verifying whether code paths changed.
- Spending most of the pass on report-only code while production risks remain.
- Treating missing metadata or weak gates as harmless if they affect live constraints.
- Recommending profile promotion from research results alone when P2 shadow evidence is worse.
- Asking for expert review as a routine checkpoint when the project has a clear local implementation or diagnostic path.

## Preferred Maintenance Artifacts

- New or strengthened tests
- Small reusable scripts
- Updated repo-specific references in this skill
- Clear before and after behavior notes
