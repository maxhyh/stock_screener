# Project Profile

## Identity

This repository is an A-share daily quant research, backtest, paper execution, and profile governance platform. Its goal is not only higher backtest return, but execution-credible alpha that survives costs, capacity, industry concentration, T+1 constraints, and promotion gates.

## Non-Negotiables

- Default profile remains `quality_regime` unless promotion review explicitly approves a change.
- 20-day P2 shadow is warning evidence only. 60/90/120-day P2 windows are the main promotion evidence.
- Research OOS strength does not justify promotion without P2 execution parity.
- Do not treat lower drawdown from low invested weight as alpha.
- Promotion evidence must use unclamped metrics where available.
- A-share constraints matter: T+1, ST filtering, limit-up/down, suspensions, BJ/9-code filtering, sell-side stamp duty, liquidity capacity, industry crowding, and style exposure.

## Current Working Baseline

- Capital assumption: RMB 1,000,000.
- Main profile: `quality_regime`.
- Active shadow profiles include `quality_regime_candidate_v6_liquidity_guard`, `quality_regime_candidate_v7_industry_balance`, `quality_regime_candidate_v8_reserve_pool`, and `quality_regime_candidate_v9_exec_state`.
- v7 is not promotable as of the latest review because long-window P2 NAV parity, effective target weight, and ADV hard caps did not pass.
- v8 is an execution-repair shadow profile that added reserve-pool replacement and improved target-weight utilization, but its latest 60/90/120 P2 NAV/MDD and alpha attribution failed promotion quality.
- v9 is an execution-credibility shadow profile focused on capacity-safe reserve generation and blocked-order state handling, not on loosening risk to chase return.

## Promotion Gate Summary

A candidate must satisfy:

- At least 2 of 60/90/120 P2 windows with NAV not below main.
- MDD not worse than main.
- ADV blocked rows not above main and hard target below 100.
- 60/90/120 average `target_weight_sum_mean` not below 30%; 60-day floor 24%.
- Invested-weight top industry mean not above 32%.
- NAV-weight top industry mean not above 24%.
- No unclamped backtest failure.

Memory can inform what to test next, but cannot override these gates.
