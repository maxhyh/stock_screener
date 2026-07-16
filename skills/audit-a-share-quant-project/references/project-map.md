# Project Map

Use this file to rebuild context quickly before a deep audit.

## Production Entry Points

- `core/data/ashare_ods_loader.py`: read-only access to canonical manifest-backed ODS datasets
- `core/data/market_data_gateway.py`: source-neutral market-data contract and artifact lineage
- `scripts/daily_all.py`: main orchestration for update, scan, ML, verify, P1, P2, P3
- `scripts/daily_ml_select.py`: daily ML recommendation and pretrade gate
- `core/mfts_screener.py`: factor computation and rule-based scan
- `scripts/quant_portfolio_backtest.py`: portfolio backtest and summary metrics
- `core/risk/pretrade.py`: pretrade hard gates for industry, ADV, style, blacklist, min price
- `core/execution/paper_broker.py`: paper OMS with A-share entry and exit constraints
- `scripts/train_mfts_lgbm.py`: feature selection, label construction, model training

## Support Modules

- `utils/signal_quality.py`: quality score blended with ML ranking
- `utils/signal_refactor.py`: stability and redundancy-adjusted ranking
- `utils/market_regime.py`: regime detection and position range suggestion
- `config/settings.py`: default strategy, training, and deployment config
- `config/settings.py`: shared ODS root and runtime defaults

## Retired Or Historical Data Paths

- `scripts/daily_incremental_update.py`, `data/download_5y_data.py`, and
  `data/data_adapter.py` belong to the retired local-cache/downloader generation.
- Do not restore `data/daily_all_5y.parquet` as a source of truth.
- Historical references to those paths may remain in archived evidence, but new
  production work must use the read-only ODS adapter and manifest lineage.

## Audit Hotspots

### Highest Priority

- Look-ahead bias in factor, label, and backtest timing:
  `core/mfts_screener.py`
  `scripts/train_mfts_lgbm.py`
  `scripts/daily_verify.py`
  `scripts/quant_portfolio_backtest.py`

- A-share execution realism:
  `core/execution/paper_broker.py`
  `core/risk/pretrade.py`
  `scripts/quant_p2_paper_trade.py`
  `scripts/quant_exec_consistency_report.py`

- Data coverage and metadata integrity:
  `core/data/ashare_ods_loader.py`
  `core/data/market_data_gateway.py`
  `scripts/train_mfts_lgbm.py`

### Performance Hot Paths

- `core/mfts_screener.py`: many grouped rolling transforms and factor chains
- `scripts/quant_portfolio_backtest.py`: per-trade loops, diversification filters, exit alignment
- `core/data/ashare_ods_loader.py`: partition discovery, manifest validation, and windowed reads

## Current Repo Behaviors Worth Verifying

- Forward labels are purged at split boundaries and feature selection is train-only.
- Missing model features or horizon/generation mismatches fail before signal output.
- P2 does not delete/recompute daily per-name targets without an explicit transform.
- Open fills use official open-time state, not the day's later high/low or full-day amount.
- Raw-model gate validity is 7/7 for data/method contracts; investment stability is assessed with preregistered fold and statistical criteria rather than a universal 7/7 absolute-profit rule.
- Project commands run in the `stock` Conda environment.
- The shared ODS root is read-only and selected snapshots are manifest-backed.
- Research labels use adjusted prices while paper execution uses raw prices.
- Historical universes and ST/board status are point-in-time, not reconstructed from a current snapshot.
- Model horizon, label definition, feature schema, and artifact lineage match the active profile contract.
- Artifacts generated before the ODS migration are historical diagnostics, not promotion evidence.
- Pretrade gates now depend on candidate weights. If blocked names change the surviving basket, verify that weights are recomputed before final approval.
- Backtest benchmark and excess-return math should be checked against realized exposure, not only full benchmark return.
- Unknown industry values should be treated as a weakening of risk control, not as harmless missing metadata.
- For historical rebuilds, verify that target-date slicing includes enough warmup bars to avoid truncated indicators.

## Useful Docs In Repo

- `docs/PROJECT_INDEX.md`: code entrypoints
- `docs/WORKFLOW.md`: operational flow
- `docs/SIGNAL_LOGIC.md`: signal meanings
- `docs/OPTIMIZATION_STATUS.md`: recent optimization notes and research state
