# Error Memory

Record recurring mistakes and failure modes. Keep this practical: symptom, cause, mitigation, and evidence.

## Error Log

### 2026-04-26 | Promotion can pass strict gates over inconsistent target-weight evidence
- tags: promotion, checksum, target_weight
- status: active
- severity: critical
- mitigation: Require P2 summaries to report external target-weight source rate and checksum coverage, and hard-fail candidates below 100%.
- evidence: Expert review emphasized that strict promotion logic is insufficient if daily, optimizer, and P2 requested weights are not provably the same evidence chain.

Do not accept a candidate whose execution artifacts cannot prove target-weight lineage.

### 2026-04-26 | P2 replay can become invalid if a script-level rebalance path recomputes target weights
- tags: p2, target_weight, promotion
- status: active
- severity: critical
- mitigation: Use `core.execution.paper_broker.PaperBroker` as the canonical rebalance path and require tests proving external `target_weight` is preserved.
- evidence: External expert review found that legacy `_rebalance` code in `scripts/quant_p2_paper_trade.py` could overwrite optimizer weights and double-apply total position.

Rolling replay and promotion gates become unreliable if P2 requested weights are not the same weights produced by the portfolio layer.

### 2026-04-26 | Next-day pretrade gates can leak execution outcomes into research selection
- tags: lookahead, pretrade, research_safe
- status: active
- severity: critical
- mitigation: Default daily selection to signal-day pretrade checks; require explicit opt-in for next-trade-day replay diagnostics.
- evidence: External expert review flagged `MFTS_SIGNAL_PRETRADE_USE_NEXT_TRADE_DAY` default behavior and forward buffers as a possible ex-post tradability leak.

A-share next-day buy/sell availability must be modeled as execution outcome unless explicitly labeled as replay evidence.

### 2026-04-26 | Low-invested candidates can look safer than they are
- tags: promotion, target_weight, cash_drag
- status: active
- severity: high
- mitigation: Require `target_weight_sum_mean` floors and compare NAV/MDD against the main profile across 60/90/120 P2 windows.
- evidence: v7 60/90-day target weight means were 21.03% and 27.03%, below promotion floors.

Lower drawdown from high cash is not a valid improvement unless NAV parity and effective exposure both pass.

### 2026-04-26 | Industry ranking penalties alone do not guarantee portfolio-level diversification
- tags: industry, optimizer, execution
- status: active
- severity: medium
- mitigation: Keep industry crowding light in ranking and enforce hard caps in portfolio/pretrade, including post-trade holdings.
- evidence: v3/v6/v7 evolution showed ranking penalties can improve one metric while leaving concentration or cash shortfall elsewhere.

Ranking should prioritize candidate quality; final portfolio constraints must live in the portfolio and pretrade layers.

### 2026-04-26 | Research strong, execution weak is often a capacity/portfolio issue, not just a signal issue
- tags: p2, capacity, turnover
- status: active
- severity: high
- mitigation: Diagnose ADV blocked rows, target weight utilization, order blocked rate, and industry concentration before changing alpha parameters.
- evidence: v6/v7 reduced some execution friction but still failed promotion gates.

Avoid blindly tuning signal blends when the bottleneck is execution pass-through.
