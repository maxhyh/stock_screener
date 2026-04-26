# Maintenance Loop

Use this file when the skill is applied repeatedly over time, not only for a single audit.

## Goal

Continuously improve the repo's trading realism, stability, and maintainability while avoiding repeated rediscovery of the same issues.

## Standard Loop

1. Build a fresh snapshot:
   run `python skills/audit-a-share-quant-project/scripts/build_maintenance_snapshot.py`
2. Re-read the current production path:
   `daily_all.py`
   `daily_incremental_update.py`
   `daily_ml_select.py`
   `mfts_screener.py`
   `quant_portfolio_backtest.py`
   `pretrade.py`
   `paper_broker.py`
3. Identify the highest-leverage issue in one of these buckets:
   logic bias
   execution realism
   performance
   robustness
   architecture coupling
4. Fix the issue with the smallest safe patch that materially improves the repo.
5. Add or update a regression test.
6. Re-run the relevant tests and regenerate the snapshot if the maintenance pass was substantial.
7. Leave the next highest-priority target in the response.
8. If the maintenance pass changes a strategy/profile candidate, refresh shadow evidence before recommending promotion:
   run `python scripts/quant_p2_rolling_replay.py ...`
   then run `python scripts/quant_p2_shadow_diagnosis.py ...`
   and compare NAV path, ADV blocking, and industry concentration.

## What Counts As Progress

- A silent PnL distortion is removed.
- A scan, ML, backtest, and execution mismatch is aligned.
- A repeated hot path becomes faster or less memory-heavy.
- A broad fallback becomes explicit and testable.
- A recurring repo pattern is captured in this skill for future use.
- A strategy candidate becomes easier to judge because research-side and execution-side evidence now live in the same maintenance record.

## What To Avoid

- Large speculative refactors with no regression protection.
- Repeating old findings without verifying whether code paths changed.
- Spending most of the pass on report-only code while production risks remain.
- Treating missing metadata or weak gates as harmless if they affect live constraints.
- Recommending profile promotion from research results alone when P2 shadow evidence is worse.

## Preferred Maintenance Artifacts

- New or strengthened tests
- Small reusable scripts
- Updated repo-specific references in this skill
- Clear before and after behavior notes
