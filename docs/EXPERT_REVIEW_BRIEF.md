# Expert Review Brief

> Review snapshot date: 2026-04-26
> Repository purpose: A-share daily quant research, portfolio construction, paper execution, diagnostics, and promotion governance.

## 1. What This Project Is

This repository is an A-share daily stock-selection and paper-execution platform. The goal is not live broker connectivity yet. The current goal is to make the full chain credible:

`research signal -> daily selection -> portfolio construction -> backtest -> pretrade risk -> P2 paper replay -> shadow diagnosis -> promotion governance -> memory loop`

The project should be reviewed as a quant strategy platform under development, not as a finished production trading system.

## 2. Main Entry Points For Review

- `README.md`: project navigation and run commands.
- `docs/PROJECT_INDEX.md`: repository map and operating conventions.
- `config/quant_live_profiles.json`: default and candidate profile definitions.
- `core/platform/portfolio_engine.py`: target-weight generation and portfolio constraints.
- `core/risk/pretrade.py`: pretrade risk checks.
- `scripts/daily_ml_select.py`: daily ML and ranking selection.
- `scripts/quant_portfolio_backtest.py`: portfolio backtest path.
- `scripts/quant_p2_paper_trade.py`: P2 paper execution.
- `scripts/quant_p2_rolling_replay.py`: rolling P2 replay.
- `scripts/quant_p2_shadow_diagnosis.py`: profile shadow diagnosis.
- `scripts/quant_alpha_execution_attribution.py`: alpha-to-execution attribution.
- `scripts/quant_profile_promotion_review.py`: profile promotion gate.
- `schemas/promotion_decision.schema.json`: promotion decision evidence schema.
- `memory/README.md`, `memory/actives.md`, `memory/learnings.md`: project memory loop.
- `tests/`: unit and integration-style coverage.

Generated outputs in `output/`, logs in `logs/`, trained model binaries in `models/*.pkl`, and large local market data files are intentionally not tracked in Git.

## 3. Strategy Architecture

- Research signal layer: ML score, signal quality score, feature refactor/stability score, liquidity score, and execution overlay score.
- Ranking layer: candidate ordering. The intended direction is that ranking chooses candidates, while the portfolio engine owns final target weights.
- Filter and gate layer: A-share tradability filters, ST and special-board exclusions, limit-up/limit-down handling, suspension handling, minimum price, minimum traded value, ADV participation, industry, and style gates.
- Portfolio construction layer: moving toward capacity-aware and crowding-aware target-weight generation with single-name, industry, ADV, style, and turnover/cost constraints.
- Execution layer: P2 paper trade, rolling replay, shadow compare, execution consistency reports, and research-to-execution funnel diagnostics.
- Governance layer: profile promotion review, schema validation, apply gate, and memory-assisted operating discipline.

## 4. Current Profile State

- Current default profile: `quality_regime`.
- v7 shadow profile: `quality_regime_candidate_v7_industry_balance`.
- v7 direction is judged correct on industry concentration, but it has not yet delivered enough execution-layer NAV improvement.
- v7 should not be promoted now.
- v8 direction should focus on execution repair, not looser risk controls.

## 5. Latest v7 Evidence Summary

Latest local P2 and shadow evidence indicates:

- v7 60/90/120 day P2 NAV: about `-0.67% / -1.08% / -1.13%`.
- v7 60/90/120 target-weight mean: about `21.0% / 27.0% / 30.5%`.
- v7 60/90 day position utilization is too low.
- v7 invested-weight top industry concentration: about `31.86%`, which passes the 32% target.
- v7 NAV-weight top industry concentration: about `6.21%`, which passes the 24% target.
- v7 ADV blocked rows: about `105`, still above the hard target of `<100`.
- The late-March blocked-order cluster was driven mainly by `entry_not_tradable` and `exit_not_tradable`, not purely by ADV.
- Current promotion decision should remain `keep`, with `quality_regime` as default.

These figures are copied into this brief to give external reviewers context without committing the full local `output/` artifact tree.

## 6. Known Open Problems

The next review should be especially strict on these points:

1. Research-layer alpha may not yet survive execution-layer constraints.
2. Capacity clipping can leave too much cash, especially in 60/90 day windows.
3. P2 execution should be checked for any hidden target-weight recomputation.
4. Late-March blocked orders expose an execution break around T+1 tradability, limit-up/limit-down, and suspension behavior.
5. Industry concentration has improved, but effective deployed capital and post-execution NAV still need proof.
6. Profile promotion must reject candidates that win only by holding excess cash or benefiting from incomplete execution modeling.

## 7. What Expert Review Should Decide

The review should answer:

- Is the system a credible evolving quant platform, or mostly a complex backtest framework?
- Where is the most likely pseudo-alpha?
- Does the current backtest/paper chain avoid material look-ahead and execution overstatement?
- Is the portfolio engine mature enough, or should the objective function be made more explicit?
- Are the promotion gates hard enough for real A-share constraints?
- Should v8 focus on reserve candidates, redistribution after capacity clips, and tradability-block repair before any alpha tuning?

