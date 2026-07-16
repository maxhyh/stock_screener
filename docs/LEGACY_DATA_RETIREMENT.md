# 旧数据退役清单

## 当前边界

市场数据的唯一生产来源是共享只读 ODS：`$ASHARE_DATA_ROOT/ods/`，默认根目录为
`/Users/max/Data/ashare-source-data`。所有当前生产、训练和核心量化诊断入口必须经
`core.data.market_data_gateway.AShareMarketDataGateway` 读取；不得读取、下载、修复或写入共享数据源。

本清单中的旧脚本不是生产入口，也不得用于生成 promotion、P2 或 raw-model 的新证据。
`data/daily_all_5y.parquet`、`data/stock_info.csv`、行业/基准缓存及 Python 缓存已于
2026-07-16 删除至系统废纸篓；共享 ODS 未被修改。

## 已迁移入口

- 日常：`daily_all.py`、`daily_ml_select.py`、`daily_verify.py`、`daily_risk_report.py`
- 研究/训练：`train_mfts_lgbm.py`、`auto_retrain.py`、`research/analyze_factor_ic.py`、
  `research/capacity_estimation.py`、raw-model 和 profile 诊断
- 执行/治理：portfolio backtest、P2 paper/replay/shadow、promotion refresh/review
- 展示：Web services/routes 与项目健康检查

## 退役对象

下列脚本仍包含旧本地缓存读写逻辑，必须保持脱离生产调度；不允许把它们改造成共享 ODS
写入器。

- 数据下载/补数/修复：`data/download_5y_data.py`、`data/data_adapter.py`、
  `scripts/daily_incremental_update.py`、`scripts/fix_missing_data.py`、
  `scripts/fix_volume_unit_by_date.py`、`scripts/repair_missing_volume.py`、
  `scripts/repair_missing_ohlc.py`
- 旧策略/历史复盘：`core/mfts_screener_v62.py`、`scripts/research/daily_hybrid_select.py`、
  `scripts/history/*`、`scripts/backtest_mfts_lite.py` 之外尚未迁移的历史回测、
  `scripts/verify_historical.py`
- 兼容回退：`utils/metadata_guard.py` 中的本地元数据健康度辅助函数；当前生产/P2 仅调用
  ODS as-of 版本。

## 最终删除前的验收

1. 静态扫描确认当前生产、训练、P2、promotion、Web 入口没有旧文件路径。
2. 全量测试通过，ODS data-lineage 与 snapshot digest 出现在新生成的研究/执行工件中。
3. 在不读取本地 `data/daily_all_5y.parquet` 和 `data/stock_info.csv` 的条件下，完成一次
   `daily_all`、核心诊断和 Web health rehearsal。
4. 单独列出将删除的本地文件、旧脚本和缓存；只有用户最终明确确认后才删除。
