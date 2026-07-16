# P0 Phase 2 PIT And Price Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate adjusted research/label prices from raw execution prices and reject historical universe assertions that lack PIT security state.

**Architecture:** Add focused price and PIT providers above validated ODS generations. Consumers request a named domain instead of receiving one mixed panel. Missing formal PIT fields fail the dependent use case rather than falling back to current metadata.

**Tech Stack:** Python, pandas, pytest, validated ODS daily bars/adj factors/limits/master.

---

## File Structure

- Create `core/data/price_contract.py`: four price domains and factor application.
- Create `core/data/pit_security_state.py`: effective/visible state and eligibility checks.
- Modify loader/gateway and feature/label consumers.
- Create `tests/test_price_contract.py`, `tests/test_pit_security_state.py`.

### Task 1: Implement Signal-Date-Safe Adjusted Research Prices

- [ ] Add a synthetic split test where raw price halves and factor doubles; adjusted OHLC, returns, MA, and ATR remain continuous.

```python
def test_raw_times_factor_removes_split_discontinuity():
    raw = _split_fixture(raw_close=[100.0, 50.0], adj_factor=[1.0, 2.0])
    adjusted = build_research_adjusted_bars(raw, convention="raw_times_factor")
    assert adjusted["research_close"].tolist() == [100.0, 100.0]
```

- [ ] Add future-event invariance: adding factors after signal date cannot alter earlier feature checksums.
- [ ] Implement explicit raw-times-factor convention and preserve raw columns separately.
- [ ] Update `core/mfts_screener.py` and raw-model frame construction to consume `research_*` OHLC.
- [ ] Run price, screener, and raw-frame tests; commit.

### Task 2: Implement Total-Return Labels With Availability

- [ ] Add tests for adjusted H=8/H=10 open-to-open labels and `label_entry_date`, `label_exit_date`, `label_available_at`.

```python
expected = (exit_raw_open * exit_factor) / (entry_raw_open * entry_factor) - 1.0
assert sample.label_return == pytest.approx(expected)
assert sample.label_available_at >= sample.label_exit_date
```

- [ ] Create one shared label builder used by training and raw walk-forward.
- [ ] Prevent label columns/factors after the signal cutoff from entering feature frames.
- [ ] Run label reconciliation tests; commit.

### Task 3: Use Official Raw Execution State

- [ ] Add tests ensuring execution bars preserve ODS `pre_close`, `up_limit`, `down_limit`, and raw OHLC.
- [ ] Remove inferred previous-close/limit values when official fields exist; heuristic fallback is diagnostic-only and lineage-labelled.
- [ ] Ensure rolling capacity fields use `.shift(1).rolling(...)` for a trade-date open decision.
- [ ] Run gateway, pretrade, broker, and backtest bar-contract tests; commit.

### Task 4: Enforce PIT Security State

- [ ] Add transition fixtures for listing, delisting, ST, industry, board, and suspension visibility.
- [ ] Implement `PITSecurityStateProvider.state_at(signal_cutoff, required_fields)` with effective and visible time checks.
- [ ] Remove window-end master joins from historical panel and backtest industry maps.
- [ ] Keep current names display-only and mark them `descriptive_current`.
- [ ] If ODS lacks historical ST/industry/status, emit `pit_required_field_unavailable` and stop formal dependent runs.
- [ ] Run PIT/universe tests; commit.

### Phase 2 Gate

- [ ] Generate price reconciliation, official-limit reconciliation, PIT coverage, and survivorship-difference artifacts.
- [ ] Require zero future-factor feature changes and zero window-end historical master joins.
- [ ] Run the full suite and refresh docs/Skill/memory.
- [ ] Stop before Phase 3 if required PIT fields are unavailable.
