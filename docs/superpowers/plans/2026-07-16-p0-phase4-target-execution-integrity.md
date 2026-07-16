# P0 Phase 4 Target And Execution Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve one immutable target portfolio through pretrade and P2, model every change as an auditable transform, and eliminate open-execution and sell-trap budget inconsistencies.

**Architecture:** A target-instruction contract becomes the handoff object. Pretrade, reserve replacement, lot rounding, broker fills, and blocked orders create parent-linked transforms. Backtest and P2 share per-security event semantics.

**Tech Stack:** Python dataclasses, pandas, JSON, existing portfolio/pretrade/paper broker, pytest.

---

## File Structure

- Create `core/platform/target_instruction.py` and schema.
- Modify daily selection, portfolio engine, pretrade, P2, broker, replay, backtest, and promotion.
- Add target-lineage and event-replay tests.

### Task 1: Define Immutable Target Instructions

- [ ] Add order-invariant checksum and round-trip tests covering security weights, score/rank source, constraints, IDs, signal cutoff, and profile hash.
- [ ] Implement `TargetPortfolioInstruction` and `TargetTransform`; reject duplicate codes and negative/over-cap weights.
- [ ] Emit an instruction artifact from daily selection.
- [ ] Run target-contract tests; commit.

### Task 2: Remove Silent P2 Re-Optimization

- [ ] Add a regression proving P2 receives exact daily per-name weights and checksum.
- [ ] Remove the unconditional drop of target-weight fields in `quant_p2_paper_trade.py`.
- [ ] Convert reserve/capacity/industry changes into deterministic child transforms with parent checksum and reasons.
- [ ] Require rolling replay to compare checksum equality, not coverage alone.
- [ ] Run P2/replay tests; commit.

### Task 3: Fix Open Tradability And Capacity Timing

- [ ] Add tests: open at upper limit blocks buy even if later low is lower; open at lower limit blocks sell even if later high is higher.
- [ ] Make broker/pretrade use official limit fields and open-time information only.
- [ ] Make signal-date ADV/capacity exclude execution-day amount; keep full-day amount/high/low for post-trade TCA only.
- [ ] Run broker/pretrade/gateway tests; commit.

### Task 4: Keep Trapped Positions In Risk Budgets

- [ ] Add a state test with 30% trapped sell and 60% total cap; post-buy gross must remain at or below 60%.
- [ ] Include trapped positions in gross, industry, style, single-name, and cash feasibility.
- [ ] Freeze all new buys only when no feasible remaining budget exists or the configured threshold is crossed.
- [ ] Run blocked-state and pretrade tests; commit.

### Task 5: Eliminate Hard-Filter Resurrection

- [ ] Classify eligibility, ST/BJ, blacklist, official tradability, required metadata, model contract, and configured hard ADV/industry/style limits as fail-closed.
- [ ] Keep quality/refactor/overheat/quantile fallback as labelled soft variants only.
- [ ] Add a test where ten of thirteen names are hard-blocked and only three or cash survive.
- [ ] Run daily/pretrade tests; commit.

### Task 6: Canonicalize Per-Security Backtest Events

- [ ] Add a two-name exit test: one exits, one remains trapped and marked to market.
- [ ] Reuse broker event semantics or label the old aggregate backtest `research_only_non_executable` until replacement is complete.
- [ ] Remove whole-trade skip behavior from any artifact eligible for promotion.
- [ ] Run backtest/P2 parity tests; commit.

### Phase 4 Gate

- [ ] Require zero unexplained checksum differences, zero open-time future fields, zero gross/style/industry overruns from trapped positions, and zero hard-filter resurrection.
- [ ] Run full tests and update docs/Skill/memory.
- [ ] Enter `EXECUTION_ELIGIBLE` only if the raw-model gate already passed.
