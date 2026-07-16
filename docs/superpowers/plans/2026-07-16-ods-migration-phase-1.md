# Shared ODS Migration Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the active daily-selection, portfolio-backtest, P2 replay, and promotion-calendar chain to a single read-only shared-ODS market-data gateway with reproducible snapshot lineage.

**Architecture:** Extend `core.data.ashare_ods_loader` rather than changing every reader's filesystem logic. A new `market_data_gateway` wraps the loader and returns normalized bars, trading sessions, as-of metadata, execution constraints, and lineage. Phase-1 consumers use the gateway exclusively; research, training, web, and destructive legacy cleanup are later phases.

**Tech Stack:** Python 3, pandas, pytest, existing ODS partitioned Parquet, existing `utils.market_data_units` normalization, A-share P2 execution stack.

---

## File Structure

- `core/data/ashare_ods_loader.py`: low-level latest-snapshot ODS reads; add snapshot enumeration and valid trading-session support.
- `core/data/market_data_gateway.py`: source of truth for normalized market frames, metadata, execution constraints, calendars, and lineage.
- `core/data/__init__.py`: expose the gateway public API.
- `tests/test_market_data_gateway.py`: contract tests using temporary ODS partitions; no shared-data writes.
- `core/mfts_screener.py`, `scripts/daily_ml_select.py`: selection readers use gateway feature windows.
- `scripts/quant_portfolio_backtest.py`, `scripts/quant_p2_paper_trade.py`: execution readers use the same unadjusted ODS bar contract.
- `scripts/quant_p2_rolling_replay.py`, `scripts/quant_refresh_promotion_gate.py`: obtain replayable sessions from the gateway, not a parquet scan.
- `tests/test_daily_ml_select_loading.py`, `tests/test_quant_backtest_defaults.py`, `tests/test_p2_rolling_replay.py`, `tests/test_quant_refresh_promotion_gate.py`: migrate behavior assertions from a fake legacy parquet to a fake ODS root.

### Task 1: Specify and test the ODS trading-session and lineage contract

**Files:**
- Modify: `tests/test_ashare_ods_loader.py`
- Create: `tests/test_market_data_gateway.py`

- [ ] **Step 1: Add a failing session-filtering test**

Create temporary `trading_calendar` partitions with one `is_trading_day=False` date and two trading dates, but create `daily_bars` only for one trading date. Assert the public gateway returns only the date that is both a valid calendar session and has a bar partition:

```python
def test_available_market_sessions_intersects_calendar_and_daily_bars(tmp_path):
    _write_ods_partition(tmp_path, "trading_calendar", "2026-01-01", {"exchange": ["SH"], "trade_date": ["2026-01-01"], "is_trading_day": [False]})
    _write_ods_partition(tmp_path, "trading_calendar", "2026-01-02", {"exchange": ["SH"], "trade_date": ["2026-01-02"], "is_trading_day": [True]})
    _write_ods_partition(tmp_path, "trading_calendar", "2026-01-05", {"exchange": ["SH"], "trade_date": ["2026-01-05"], "is_trading_day": [True]})
    _write_ods_partition(tmp_path, "daily_bars", "2026-01-05", _bar_payload("2026-01-05"))

    gateway = AShareMarketDataGateway(tmp_path)

    assert gateway.available_trade_dates("2026-01-01", "2026-01-05") == ["2026-01-05"]
```

- [ ] **Step 2: Run the test and observe the expected import failure**

Run:

```bash
python -m pytest -q tests/test_market_data_gateway.py -k sessions
```

Expected: FAIL because `AShareMarketDataGateway` does not exist.

- [ ] **Step 3: Add failing snapshot-lineage test**

Use two snapshots for the same date. Assert that the gateway selects the lexicographically latest snapshot and that `frame.attrs["market_data_lineage"]` records the source, `unadjusted` price mode, requested date range, and the chosen `(dataset, trade_date, snapshot)` identity.

```python
def test_daily_bars_lineage_records_selected_snapshot(tmp_path):
    _write_ods_partition(tmp_path, "daily_bars", "2026-01-05", _bar_payload("2026-01-05", close=10.0), snapshot="20260105T010000Z")
    _write_ods_partition(tmp_path, "daily_bars", "2026-01-05", _bar_payload("2026-01-05", close=11.0), snapshot="20260105T020000Z")

    frame = AShareMarketDataGateway(tmp_path).load_bars("2026-01-05", "2026-01-05")

    assert frame.loc[0, "close"] == 11.0
    assert frame.attrs["market_data_lineage"]["price_mode"] == "unadjusted"
    assert frame.attrs["market_data_lineage"]["snapshot_count"] == 1
```

- [ ] **Step 4: Run the lineage test and observe it fail**

Run:

```bash
python -m pytest -q tests/test_market_data_gateway.py -k lineage
```

Expected: FAIL because the gateway and lineage attributes do not yet exist.

### Task 2: Implement the read-only gateway

**Files:**
- Modify: `core/data/ashare_ods_loader.py`
- Create: `core/data/market_data_gateway.py`
- Modify: `core/data/__init__.py`

- [ ] **Step 1: Add low-level selected-partition enumeration**

Add this loader method, which never reads `current_snapshot_only` and returns only latest partitions in the inclusive date range:

```python
def selected_partitions(self, dataset: str, start_date: object, end_date: object) -> list[OdsPartition]:
    return [
        part
        for date in self.available_trade_dates(dataset)
        if normalize_ods_trade_date(start_date) <= date <= normalize_ods_trade_date(end_date)
        if (part := self.latest_partition(dataset, date)) is not None
    ]
```

- [ ] **Step 2: Implement `AShareMarketDataGateway` minimally**

Create `core/data/market_data_gateway.py` with these public methods:

```python
class AShareMarketDataGateway:
    def __init__(self, data_root: str | Path | None = None) -> None: ...
    def available_trade_dates(self, start: object | None = None, end: object | None = None) -> list[str]: ...
    def load_bars(self, start: object, end: object, *, include_bj9: bool = False, lookback_sessions: int = 0, forward_sessions: int = 0) -> pd.DataFrame: ...
    def load_stock_info(self, asof_date: object, *, include_bj9: bool = False) -> pd.DataFrame: ...
```

`load_bars` must expand by trading sessions rather than calendar days, delegate to
`AShareOdsLoader.load_daily_panel`, normalize with `normalize_amount_volume_units`,
and attach a JSON-serializable `market_data_lineage` attribute. The lineage must
include `data_source="ashare_ods"`, absolute `data_root`, `price_mode="unadjusted"`,
the requested and expanded ranges, `include_bj9`, datasets used, snapshot count,
and SHA-256 digest of selected partition identities.

- [ ] **Step 3: Verify gateway contract tests pass**

Run:

```bash
python -m pytest -q tests/test_ashare_ods_loader.py tests/test_market_data_gateway.py tests/test_market_data_units.py
```

Expected: PASS.

- [ ] **Step 4: Run a real read-only ODS smoke**

Run:

```bash
ASHARE_DATA_ROOT=/Users/max/Data/ashare-source-data python - <<'PY'
from core.data.market_data_gateway import AShareMarketDataGateway
g = AShareMarketDataGateway()
f = g.load_bars("2026-04-01", "2026-04-14", lookback_sessions=20, forward_sessions=1)
print(len(f), f["trade_date"].min(), f["trade_date"].max(), f.attrs["market_data_lineage"])
PY
```

Expected: non-empty frame with normalized required columns and ODS lineage; no shared-root modifications.

### Task 3: Migrate daily selection and screener loading

**Files:**
- Modify: `core/mfts_screener.py`
- Modify: `scripts/daily_ml_select.py`
- Modify: `tests/test_daily_ml_select_loading.py`
- Modify: `tests/test_p0_code_contract.py`

- [ ] **Step 1: Write failing daily-selection ODS loading test**

Replace the legacy-parquet fixture with a temporary ODS root. Assert `load_latest_data` receives `ASHARE_DATA_ROOT`, asks the gateway for the requested feature window, returns normalized `ts_code/trade_date/open/high/low/close/vol/amount`, and exposes ODS lineage:

```python
def test_load_latest_data_uses_read_only_ods_gateway(monkeypatch, tmp_path):
    _write_minimal_ods_root(tmp_path)
    monkeypatch.setenv("ASHARE_DATA_ROOT", str(tmp_path))

    frame = select.load_latest_data(start_date="2026-01-02", end_date="2026-01-05")

    assert set(["ts_code", "trade_date", "open", "close", "vol", "amount"]).issubset(frame.columns)
    assert frame.attrs["market_data_lineage"]["data_source"] == "ashare_ods"
```

- [ ] **Step 2: Run the test and observe it fail on the legacy reader**

Run:

```bash
python -m pytest -q tests/test_daily_ml_select_loading.py -k ods_gateway
```

Expected: FAIL because `load_latest_data` still reads `data/daily_all_5y.parquet`.

- [ ] **Step 3: Replace selection readers**

Make `daily_ml_select.load_latest_data` call the gateway with its existing
requested date range. Preserve cache behavior, but key `_DATA_CACHE` and
`_INDICATOR_DATA_CACHE` by ODS lineage digest and requested column set. Change
`core.mfts_screener.load_data` to call `gateway.load_bars` from
`START_DATE_FILTER` through the latest available session and use
`gateway.load_stock_info(target_date)` instead of `stock_info.csv`.

- [ ] **Step 4: Run focused selection tests**

Run:

```bash
python -m pytest -q tests/test_daily_ml_select_loading.py tests/test_p0_code_contract.py
```

Expected: PASS without creating or reading a local legacy parquet.

### Task 4: Migrate portfolio backtest and P2 to one bar contract

**Files:**
- Modify: `scripts/quant_portfolio_backtest.py`
- Modify: `scripts/quant_p2_paper_trade.py`
- Modify: `tests/test_quant_backtest_defaults.py`
- Modify: `tests/test_p2_paper_trade.py`

- [ ] **Step 1: Write failing shared-contract tests**

Create temporary ODS bars with an amount value that needs the existing unit
normalizer. Assert P2 and portfolio backtest invoke the same gateway helper and
produce equal `prev_close`, `amount_ma20`, `amount_min5`, and `amount_min10`
for the same code/date.

```python
def test_p2_and_backtest_share_ods_bar_contract(monkeypatch, tmp_path):
    _install_fake_gateway(monkeypatch, tmp_path)
    p2 = p2_trade._load_bars()
    bt, _ = qbt._load_market_open_prices()
    cols = ["trade_date", "code", "prev_close", "amount_ma20", "amount_min5", "amount_min10"]
    pd.testing.assert_frame_equal(p2[cols].reset_index(drop=True), bt[cols].reset_index(drop=True))
```

- [ ] **Step 2: Run and confirm failure**

Run:

```bash
python -m pytest -q tests/test_quant_backtest_defaults.py tests/test_p2_paper_trade.py -k ods_bar_contract
```

Expected: FAIL because each script independently opens the legacy parquet.

- [ ] **Step 3: Extract one execution-bar helper**

Add `load_execution_bars` to the gateway module. It calls `load_bars`, applies
the current `prev_close`, `amount_ma20`, `amount_min5`, and `amount_min10`
calculations once, and returns `(market_df, bars_idx, lineage)`. Replace both
script-local parquet loaders with this helper. Add the lineage to their JSON
run manifests under `market_data_lineage`.

- [ ] **Step 4: Verify focused tests**

Run:

```bash
python -m pytest -q tests/test_quant_backtest_defaults.py tests/test_p2_paper_trade.py tests/test_platform_portfolio_engine.py
```

Expected: PASS.

### Task 5: Migrate replay and promotion market calendars

**Files:**
- Modify: `scripts/quant_p2_rolling_replay.py`
- Modify: `scripts/quant_refresh_promotion_gate.py`
- Modify: `tests/test_p2_rolling_replay.py`
- Modify: `tests/test_quant_refresh_promotion_gate.py`

- [ ] **Step 1: Write failing calendar tests**

Make a temporary ODS calendar with a non-trading day, an incomplete bar date,
and two valid sessions. Assert both `_load_market_trade_dates` helpers return
only the shared valid sessions in `YYYYMMDD` form.

```python
def test_replay_and_refresh_use_ods_replayable_sessions(monkeypatch, tmp_path):
    _install_ods_gateway(monkeypatch, tmp_path, ["20260102", "20260105"])
    assert replay._load_market_trade_dates() == ["20260102", "20260105"]
    assert refresh._load_market_trade_dates() == ["20260102", "20260105"]
```

- [ ] **Step 2: Run and observe failure**

Run:

```bash
python -m pytest -q tests/test_p2_rolling_replay.py tests/test_quant_refresh_promotion_gate.py -k ods_replayable_sessions
```

Expected: FAIL because the helpers scan `daily_all_5y.parquet`.

- [ ] **Step 3: Replace calendar scans**

Replace PyArrow and pandas legacy-file scans with the gateway's
`available_trade_dates`, converting values only at the script boundary. Add the
same `market_data_lineage` payload to replay and precheck summaries. Do not use
signal files as a market calendar.

- [ ] **Step 4: Verify focused replay and gate tests**

Run:

```bash
python -m pytest -q tests/test_p2_rolling_replay.py tests/test_quant_refresh_promotion_gate.py tests/test_quant_profile_promotion_review.py
```

Expected: PASS.

### Task 6: Phase-1 integration audit and evidence marking

**Files:**
- Modify: `docs/WORKFLOW.md`
- Modify: `docs/PROJECT_INDEX.md`
- Modify: `scripts/README.md`
- Modify: `memory/learnings.md`
- Modify: `memory/errors.md`

- [ ] **Step 1: Document only canonical ODS runtime commands**

Update commands to set `ASHARE_DATA_ROOT=/Users/max/Data/ashare-source-data`
and state that the shared root is read-only. Mark legacy P2/backtest artifacts
as non-comparable historical evidence because the old 2026-04-03 bar slice is
corrupt.

- [ ] **Step 2: Run the Phase-1 checks**

Run:

```bash
python -m pytest -q tests/test_ashare_ods_loader.py tests/test_market_data_gateway.py tests/test_daily_ml_select_loading.py tests/test_quant_backtest_defaults.py tests/test_p2_paper_trade.py tests/test_p2_rolling_replay.py tests/test_quant_refresh_promotion_gate.py tests/test_quant_profile_promotion_review.py
ASHARE_DATA_ROOT=/Users/max/Data/ashare-source-data python scripts/daily_ml_select.py --help
ASHARE_DATA_ROOT=/Users/max/Data/ashare-source-data python scripts/quant_p2_paper_trade.py --help
```

Expected: all tests pass; commands import without a local legacy data file.

- [ ] **Step 3: Run an ODS P2 smoke without promotion**

Use a bounded existing profile daily-signal fixture and run the documented
single-day/in-process P2 smoke. Confirm the output includes
`market_data_lineage`, source `ashare_ods`, `price_mode=unadjusted`, and no
legacy file path. Do not compare NAV to legacy evidence or promote any profile.

- [ ] **Step 4: Update memory after verified results**

Append the actual source, snapshot, and regression findings to
`memory/learnings.md`; append any session/limit/PIT issue to `memory/errors.md`.
Run:

```bash
python scripts/quant_memory_evolve.py
```

- [ ] **Step 5: Commit only Phase-1 files after clean verification**

Because the worktree contains unrelated pre-existing modifications, stage only
the gateway, direct Phase-1 consumer, test, documentation, and memory files:

```bash
git add core/data core/mfts_screener.py scripts/daily_ml_select.py scripts/quant_portfolio_backtest.py scripts/quant_p2_paper_trade.py scripts/quant_p2_rolling_replay.py scripts/quant_refresh_promotion_gate.py tests/test_ashare_ods_loader.py tests/test_market_data_gateway.py tests/test_daily_ml_select_loading.py tests/test_quant_backtest_defaults.py tests/test_p2_paper_trade.py tests/test_p2_rolling_replay.py tests/test_quant_refresh_promotion_gate.py docs/WORKFLOW.md docs/PROJECT_INDEX.md scripts/README.md memory/learnings.md memory/errors.md memory/actives.md memory/nightly_review_draft.md
git commit -m "Migrate execution chain to shared ODS gateway"
```

Expected: commit contains no output files, shared data, models, or unrelated user changes.
