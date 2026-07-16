# Raw-Model ODS Entry Design

## Goal

Add a read-only shared-ODS input mode to the raw-model walk-forward diagnostic
without changing the default legacy-data evidence path or touching P2, capacity,
or profile promotion behavior.

## Decision

`scripts/quant_raw_model_walkforward_diagnosis.py` is the first migrated
consumer. It will retain `data/daily_all_5y.parquet` as the default. A caller
must explicitly choose `--data-source ashare_ods` to read the shared root via
`core.data.ashare_ods_loader.AShareOdsLoader`.

The horizon diagnostic is deliberately out of scope for this change. It will be
migrated only after the walk-forward bridge has a field- and label-parity
report.

## Data Flow

1. The command resolves `--data-source legacy|ashare_ods`; `legacy` is the
   default.
2. Legacy mode keeps the existing parquet reader and existing data-file option.
3. ODS mode expands the requested range by 252 preceding trading days for
   long-window features and by `max(horizon)+1` following trading days for
   open-to-open labels, then reads `daily_bars`, `daily_basic`,
   `daily_adj_factor`, and `daily_limits` through the read-only loader.
4. The adapter supplies the legacy-compatible fields needed by indicators and
   labels: `ts_code`, `trade_date`, `open`, `high`, `low`, `close`, `vol`,
   `amount`, and `pct_chg`.
5. Both modes retain the existing BJ/9-code exclusion and amount/volume unit
   normalization before indicator calculation.

## Evidence And Cache Lineage

The raw-model frame cache request and final diagnostic metadata will record:

- `data_source`;
- legacy file identity, or ODS root plus requested date range;
- the adapter snapshot-selection policy (`latest_snapshot_per_trade_date`);
- the ODS feature warm-up and label-buffer trading-day policy;
- a digest of the exact latest `daily_bars` snapshots used by the expanded ODS
  window;
- the existing feature, horizon, date, and BJ/9-code controls.

This prevents ODS frames from colliding with legacy cache files or silently
surviving a historical snapshot replacement, and makes any comparison
auditable. The change does not claim that two sources are identical: a parity
report will show row/date/code coverage, required-field nulls, and
open-to-open label overlap before full walk-forward use.

## Error Handling

ODS mode fails clearly when the configured root has no `ods/daily_bars` trade
dates in the requested interval or when required daily-bar fields are absent.
If the ODS history begins fewer than 252 sessions before the request, it uses
the available history and leaves insufficient indicators visibly null rather
than fabricating a value. Missing auxiliary ODS datasets remain left joins,
matching the adapter's existing behavior. The adapter never writes to the
shared root.

## Verification

- A new test proves legacy remains the default path.
- A new test proves ODS mode routes through the loader, forwards the requested
  date range, and produces the required legacy-compatible panel columns.
- A cache-key test proves legacy and ODS requests cannot share a cache entry.
- A small real-data smoke compares the two sources over a bounded common date
  range, reporting coverage and label-ready columns without changing strategy
  evidence.

## Non-Goals

- No global replacement of `data/daily_all_5y.parquet`.
- No model retraining, label/objective changes, new profile, P2 replay, or
  promotion decision.
- No use of `current_snapshot_only` as historical PIT data.
