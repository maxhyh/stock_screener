# Long-Term Learnings

Append durable research, execution, and governance learnings here. Keep entries factual, with artifact-backed evidence where possible.

## Learnings Log

### 2026-04-27 | v9 should repair execution breaks before alpha/risk tuning
- tags: v9, reserve_pool, blocked_orders, p2
- reusable: yes
- confidence: high
- evidence: Implemented `quality_regime_candidate_v9_exec_state`, capacity-safe upstream reserve ranking (`portfolio_rank_score`), blocked-order state tracking in `PaperBroker`, and rolling replay summary fields for blocked-sell/freeze state evidence. Smoke rebuilt v9 `2026-03-27` and `2026-04-03` files at 40% target posture, then P2 smoke for `2026-03-30` and `2026-04-07` produced zero fills with blocked buy states visible.
- action: Use v9 to diagnose whether 2026-03-30 and 2026-04-07 style blocked clusters can be reduced without relaxing industry/ADV caps or raising exposure floors.

Capacity-safe reserves should be generated before portfolio/P2 pretrade, and blocked sells should become explicit state that can freeze new buys when trapped sell exposure is material. This prevents false cash reuse and makes late-March/early-April execution breaks reviewable.

### 2026-04-27 | Profile-specific signal calendars are mandatory for fair replay
- tags: p2, profile, evidence, replay
- reusable: yes
- confidence: high
- evidence: Initial v8 P2 replay mixed profile-specific v8 files with shared `output/daily` files for dates absent from `output/daily_profiles/quality_regime_candidate_v8_reserve_pool`; replay was stopped and `quant_p2_rolling_replay.py` was changed to use profile calendars when present.
- action: For profile evidence, rebuild `output/daily_profiles/<profile>/daily_*.csv` first and require rolling replay to select dates from that profile calendar.

Shared daily fallback can silently contaminate candidate replay because old default-profile daily files may not match the tested profile's reserve pool, target weights, or gates.

### 2026-04-27 | v8 improves invested weight but fails execution-alpha validation
- tags: v8, p2, reserve_pool, alpha, promotion
- reusable: yes
- confidence: high
- evidence: v8 profile-isolated P2 60/90/120 NAV = -5.33%/-11.74%/-16.09%, MDD = -8.10%/-12.78%/-16.79%, target_weight_sum_mean = 34.3%/36.1%/37.2%; alpha attribution shows negative forward return for raw ML top, optimizer, and P2 fill stages.
- action: Keep v8 shadow; next work should improve capacity-safe reserve quality and blocked-order state handling before loosening risk constraints or promoting.

Reserve pool raised effective target weight compared with v7, but the higher exposure revealed weak execution-layer alpha and severe ADV/tradability blocking.

### 2026-04-26 | Reserve pool must enter before optimizer and P2 pretrade
- tags: reserve_pool, p2, capacity, tradability
- reusable: yes
- confidence: high
- evidence: Implemented `quality_regime_candidate_v8_reserve_pool`, `PortfolioConstraints.max_names`, daily reserve candidates, and P2 pretrade re-optimization.
- action: Feed expanded candidate pools into portfolio/pretrade, but keep primary topN as the initial weight budget; reserve rows should receive weight only after capacity/tradability/industry clips.

Reserve candidates cannot be appended only after execution. They must be visible before capacity clipping and before P2 pretrade so blocked buys and low-capacity names can be replaced instead of leaving cash.

### 2026-04-26 | Promotion needs target-weight source and checksum evidence
- tags: promotion, checksum, target_weight, p2
- reusable: yes
- confidence: high
- evidence: Added `target_weight_checksum`, `target_weight_source_external_rate_pct`, and checksum coverage into P2 rolling summaries and promotion hard gates.
- action: Reject candidates whose P2 ledger did not use external optimizer weights or whose target-weight checksum coverage is incomplete.

Target-weight consistency must be a first-class promotion artifact, not an informal assumption.

### 2026-04-26 | P2 execution evidence must use the canonical broker path
- tags: p2, target_weight, execution, promotion
- reusable: yes
- confidence: high
- evidence: External expert review flagged that legacy script-level `_rebalance` in `scripts/quant_p2_paper_trade.py` could recompute score weights and double-scale total position, while `core.execution.paper_broker.PaperBroker` already respected external `target_weight`.
- action: Keep P2 rolling replay on the canonical broker path; any compatibility wrapper must delegate to `PaperBroker.rebalance_on_state` and preserve `target_weight_source`.

Promotion evidence is only trustworthy if daily target weights, P2 requested weights, and ledger weights share one execution implementation.

### 2026-04-26 | Signal pretrade defaults must be research-safe
- tags: pretrade, lookahead, research_safe, a_share
- reusable: yes
- confidence: high
- evidence: External expert review highlighted that default next-trade-day pretrade checks in daily selection could leak ex-post tradability into research candidates.
- action: Default `MFTS_SIGNAL_PRETRADE_USE_NEXT_TRADE_DAY` to false in `daily_ml_select.py`; use explicit next-day mode only for replay/expost diagnostics.

T+1 tradability is execution evidence, not a default research input.

### 2026-04-26 | v7 industry balance reduces industry concentration but fails promotion
- tags: p2, promotion, industry, adv, target_weight
- reusable: yes
- confidence: high
- evidence: `output/backtest/promotion_decision_latest.json`; v7 NAV 60/90/120 = -0.67%/-1.08%/-1.13%; ADV blocked rows = 105; target weight mean = 21.03%/27.03%/30.52%
- action: Do not promote candidates that win by carrying cash or only reducing industry concentration; require NAV parity and effective target weight.

v7 improved invested-weight industry concentration to 31.86%, but the execution path failed long-window NAV parity and left too much cash in 60/90-day windows.

### 2026-04-26 | Industry concentration needs invested and NAV-weight views
- tags: shadow, industry, diagnosis
- reusable: yes
- confidence: high
- evidence: `output/backtest/quant_p2_shadow_diagnosis_latest.csv`
- action: Use invested-weight concentration for crowding and NAV-weight concentration for cash-adjusted exposure; do not rely on a single top-industry metric.

Invested concentration shows whether the active book is crowded. NAV-weight concentration shows whether low concentration is just a byproduct of low invested weight.

### 2026-04-26 | Research-side annualized return can be misleading when hard-pass rate is zero
- tags: research, rolling_compare, overfit
- reusable: yes
- confidence: medium
- evidence: `output/backtest/quant_profile_rolling_compare_summary_latest.csv`; v7 annual_return_mean positive but hard_pass_rate = 0 and P2 failed
- action: Treat positive rolling annual return with zero hard-pass rate as diagnostic only, not promotion evidence.

The latest v7 rolling compare looked attractive on mean annual return, but path quality and execution evidence did not support promotion.

### 2026-04-26 | Alpha attribution must state artifact limitations
- tags: attribution, alpha, evidence
- reusable: yes
- confidence: high
- evidence: `scripts/quant_alpha_execution_attribution.py`
- action: When only daily recommendation files exist, label raw/quality/refactor attribution as recommendation-proxy attribution, not full-universe raw prediction attribution.

The project currently persists daily candidate recommendations, not necessarily the full raw ML prediction universe. Diagnostics must be honest about this boundary.
