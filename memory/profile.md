# Project Profile

## Identity

This repository is an A-share daily quant research, backtest, paper execution, and profile governance platform. Its goal is not only higher backtest return, but execution-credible alpha that survives costs, capacity, industry concentration, T+1 constraints, and promotion gates.

## Non-Negotiables

- Default runtime environment is the Conda environment `stock`. Use `conda run -n stock python ...` for non-interactive commands or activate it explicitly; do not validate the project with an accidental `base`/`.venv` interpreter.
- Default profile remains `quality_regime` unless promotion review explicitly approves a change.
- 20-day P2 shadow is warning evidence only. 60/90/120-day P2 windows are the main promotion evidence.
- Research OOS strength does not justify promotion without P2 execution parity.
- Do not treat lower drawdown from low invested weight as alpha.
- Promotion evidence must use unclamped metrics where available.
- A-share constraints matter: T+1, ST filtering, limit-up/down, suspensions, BJ/9-code filtering, sell-side stamp duty, liquidity capacity, industry crowding, and style exposure.

## Current Working Baseline

- Capital assumption: RMB 1,000,000.
- Main profile: `quality_regime`.
- The v7-v29 candidate line is retained as historical shadow/diagnostic evidence. None is approved for promotion.
- All P2, backtest, and raw-model artifacts produced before the read-only ODS migration are historical diagnostics only and cannot support current return or promotion claims.
- Current P0 work is upstream of profiles: adjusted research/label prices, historical point-in-time universe metadata, official limit/suspension fields, manifest enforcement, and model label-horizon/lineage alignment.
- Independent review added binding P0 work: horizon-aware label purge/embargo, fail-closed feature/horizon inference, immutable daily-to-P2 per-name target lineage, and open-time execution without same-day high/low or full-day amount.
- Do not create a new profile or run capacity/P2 optimization until the P0 data/model generation contract is repaired and a full seven-fold raw-universe gate passes on one frozen ODS generation.
- Data/method contracts must be valid in all folds. Investment acceptance uses preregistered fold stability, worst-fold floors, residual alpha and statistical confidence; it does not mechanically require positive long-only absolute return in every fold.
- Current implementation sequence is `docs/superpowers/plans/2026-07-16-p0-evidence-remediation-master.md`.
- v7 is not promotable as of the latest review because long-window P2 NAV parity, effective target weight, and ADV hard caps did not pass.
- v8 is an execution-repair shadow profile that added reserve-pool replacement and improved target-weight utilization, but its latest 60/90/120 P2 NAV/MDD and alpha attribution failed promotion quality.
- v9 is an execution-credibility shadow profile focused on capacity-safe reserve generation and blocked-order state handling, not on loosening risk to chase return.
- v22 passed some score-alpha prerequisites but failed 60-day P2 smoke versus `quality_regime`.
- v23 improved execution exposure by using NAV-weighted style exposure, but exposed weaker NAV/MDD under higher deployment.
- v24 tested conditional holiday-gap cap relief, passed signal coverage, but failed score-alpha before P2 and should remain shadow/skipped.
- v25 tested liquidity_score as the target-score override, but its 60-day P2 smoke improvement came mainly from low target-weight exposure and executable-pool halts.
- v26 tested liquidity_score with NAV-weighted style exposure. After capacity-aware fallback was disabled, it produced valid zero-target evidence and failed the hardened score-alpha gate because the top bucket was still negative in absolute forward return.

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

## Expert Review Escalation

External expert review is not required after every optimization pass. Keep progressing locally when the next engineering, diagnostic, or evidence step is clear.

Escalate to expert review only when one of these is true:

- The project reaches a strategic fork where local evidence supports multiple incompatible paths.
- A methodology or execution-credibility risk cannot be resolved by local tests, replay, attribution, or promotion artifacts.
- A candidate is close enough to promotion/default-profile change that independent scrutiny is useful before applying it.
- Fresh evidence contradicts the current operating thesis and the next action is genuinely uncertain.

When escalation is needed, prepare a clean GitHub snapshot first, then provide the user with a complete expert-review prompt covering the expert role, repository entry points, current evidence, unresolved questions, and decisions needing review. Expert advice is advisory; fresh P2/shadow/promotion evidence remains authoritative.
