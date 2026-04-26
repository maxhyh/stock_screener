# Error Memory

Record recurring mistakes and failure modes. Keep this practical: symptom, cause, mitigation, and evidence.

## Error Log

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
