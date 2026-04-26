# Long-Term Learnings

Append durable research, execution, and governance learnings here. Keep entries factual, with artifact-backed evidence where possible.

## Learnings Log

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
