# Project Map

Use this file to rebuild context quickly before a deep audit.

## Production Entry Points

- `scripts/daily_all.py`: main orchestration for update, scan, ML, verify, P1, P2, P3
- `scripts/daily_incremental_update.py`: market data update, metadata refresh, coverage gates
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
- `data/data_adapter.py`: source data normalization

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
  `scripts/daily_incremental_update.py`
  `data/download_5y_data.py`

### Performance Hot Paths

- `core/mfts_screener.py`: many grouped rolling transforms and factor chains
- `scripts/quant_portfolio_backtest.py`: per-trade loops, diversification filters, exit alignment
- `scripts/daily_incremental_update.py`: batch download and metadata refresh fan-out

## Current Repo Behaviors Worth Verifying

- Pretrade gates now depend on candidate weights. If blocked names change the surviving basket, verify that weights are recomputed before final approval.
- Backtest benchmark and excess-return math should be checked against realized exposure, not only full benchmark return.
- Unknown industry values should be treated as a weakening of risk control, not as harmless missing metadata.
- For historical rebuilds, verify that target-date slicing includes enough warmup bars to avoid truncated indicators.

## Useful Docs In Repo

- `docs/PROJECT_INDEX.md`: code entrypoints
- `docs/WORKFLOW.md`: operational flow
- `docs/SIGNAL_LOGIC.md`: signal meanings
- `docs/OPTIMIZATION_STATUS.md`: recent optimization notes and research state
