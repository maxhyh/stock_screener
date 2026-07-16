# Project-Wide Shared ODS Migration Design

## Goal

Replace every active project dependency on the legacy local market-data store
with the shared, read-only A-share ODS root. After all active paths have been
migrated and validated against new ODS evidence, remove all legacy data,
legacy-data maintenance scripts, and legacy-only artifacts from the project.

The shared root is supplied by `ASHARE_DATA_ROOT`, defaulting to
`/Users/max/Data/ashare-source-data`. This project only reads that root. It
does not download, repair, backfill, or otherwise modify shared data.

## Decisions

### One canonical market-data gateway

Create a source-neutral gateway in `core/data` and make it the sole active
market-data boundary. It exposes:

- trading-session dates from ODS `trading_calendar` filtered by
  `is_trading_day`, cross-checked against available `daily_bars` partitions;
- daily bars over explicit trading-session windows, with optional lookback and
  forward-label buffers;
- as-of instrument metadata, limits, suspensions, and daily basics;
- legacy-compatible columns (`ts_code`, `trade_date`, `vol`, `name`,
  `industry`) plus an explicit data-lineage record;
- unit normalization at one boundary, rather than repeated separately in
  selection, backtest, P2, and diagnostics.

Active code must not read `data/daily_all_5y.parquet`, `data/stock_info.csv`,
or `current_snapshot_only`. No compatibility switch remains once the migration
is complete.

### Price and PIT semantics

P2, portfolio backtests, pre-trade risk, blocked-order logic, and execution
diagnostics use ODS `daily_bars` in its documented `unadjusted` form together
with same-day ODS `daily_limits` and suspensions. This represents executable
price mechanics.

Research and model features must select an explicit, point-in-time adjustment
policy. The gateway will initially surface `adj_factor` as a separate field;
it will not silently transform OHLC using a later snapshot or a latest factor.
Any consumer that requires adjusted features must declare its policy and record
it in artifact lineage. This prevents a data-source migration from adding a
look-ahead adjustment.

`instrument_master` is read as of the signal date. Its use for historical
industry/listing status is recorded as metadata and cannot be treated as
proof of a fully historical classification unless ODS snapshots establish it.

### Snapshot lineage

Every ODS artifact records: selected source root, datasets, requested and
expanded session range, latest-snapshot selection policy, selected partition
snapshot digest, price-adjustment mode, BJ/9 inclusion policy, and unit
normalization version. A new ODS snapshot invalidates relevant caches.

Old legacy artifacts are labelled `legacy_data_lineage` and cannot be used as
promotion evidence after the production switch. Differences caused by the
known legacy 2026-04-03 OHLC duplication are reported as a data-quality change,
not a strategy improvement.

## Migration Batches

1. **Gateway and contracts.** Extend the current read-only ODS adapter with
   session-aware windows, as-of metadata, suspensions/limits, lineage, and
   tests. Keep no production fallback to the local parquet.
2. **Production and execution chain.** Migrate `core/mfts_screener.py`,
   `scripts/daily_ml_select.py`, `scripts/quant_portfolio_backtest.py`,
   `scripts/quant_p2_paper_trade.py`, rolling replay, shadow diagnosis,
   profile rebuild, and promotion refresh/review. Daily target, optimizer,
   P2, and promotion must carry the same ODS lineage.
3. **Research, model, and web chain.** Migrate raw-model/horizon diagnostics,
   training, research utilities, attribution, risk reports, and web data
   services. Model caches and emitted diagnostics include source lineage.
4. **Legacy removal.** Remove the local data files, all old download,
   increment, repair, and verification scripts that write them, legacy tests,
   stale configuration fields, and legacy-only artifacts. Update docs and
   ignore rules so no path can recreate the deprecated store.

## Verification

Each batch has targeted unit tests, source-lineage tests, and real read-only
ODS smoke tests. The execution batch also runs a bounded P2 smoke and checks
that target-weight, market-calendar, limit, and suspension semantics are
identical between daily selection, P2, and promotion inputs.

Before removal, the completion audit must establish all of the following:

- `rg` finds no active source or runtime configuration reference to
  `daily_all_5y.parquet` or `stock_info.csv`;
- all tests pass without either local data file;
- daily selection, backtest, P2, rolling replay, shadow diagnosis, and
  promotion refresh run against ODS and emit lineage;
- model/research and web read paths work from ODS;
- ODS evidence is regenerated and clearly separated from legacy evidence;
- the user gives final deletion confirmation after reviewing the audit.

## Non-Goals

- No shared-data download, ingestion, repair, or snapshot mutation.
- No use of `current_snapshot_only` as historical truth.
- No strategy parameter relaxation, profile promotion, or alpha claim caused
  by the source change.
- No deletion before every active reader and test has passed against ODS.
