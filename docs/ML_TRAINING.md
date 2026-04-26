# ML 训练指南（本地版）

本项目已切换为本地训练流程，不再依赖云服务器同步。

## 1. 环境

```bash
cd /path/to/stock_screener
source .venv/bin/activate   # 或 conda activate stock
pip install -r requirements.txt
```

## 2. 训练模型

```bash
python scripts/train_mfts_lgbm.py

# 标签模式（建议与实盘执行一致）
# 默认 label_horizon 会跟随 config/quant_live_profiles.json 的 default_profile.holding_days（当前 3）
python scripts/train_mfts_lgbm.py --label-mode open_to_open

# 显式指定 horizon（A/B 对比示例）
python scripts/train_mfts_lgbm.py --label-mode open_to_open --label-horizon 3
python scripts/train_mfts_lgbm.py --label-mode open_to_open --label-horizon 8
```

训练输出：

- `models/mfts_lgbm_YYYYMMDD_HHMMSS.pkl`
- `output/feature_importance_*.csv`
- 模型内会保存执行口径元信息：`label_mode`、`label_horizon`、`execution_hint`

## 3. 每日推理

```bash
python scripts/daily_ml_select.py --top 30
```

输出：

- `output/daily/daily_YYYYMMDD.csv`（兼容旧路径 `output/daily_YYYYMMDD.csv`）
- 输出已包含实盘字段：`市场状态`、`建议仓位`、`单票上限`、`建议持有天数`
- 推理前会自动做可交易性过滤（涨停触发/过热/量能异常）
- `daily_ml_select.py` 已改为“按目标日期动态切片”以支持历史重算；可选环境变量：
  - `MFTS_ML_LOOKBACK_DAYS`（默认 `450`）
  - `MFTS_ML_FORWARD_BUFFER_DAYS`（默认 `2`）

## 4. 回测与验证

```bash
# 策略对比
python scripts/history/backtest_comparison.py --days 30

# 历史验证
python scripts/verify_historical.py --days 30

# 指定口径验证（推荐与训练一致）
python scripts/daily_verify.py --date 20260309 --label-mode open_to_open --label-horizon 3
```

说明：

- `daily_verify.py` 已内置开盘价鲁棒回填（`open_filled`），会优先使用前收价补齐缺失开盘价，尽量避免 `open_to_open` 频繁回退到 `close_to_close_t1`。
- 如需对历史异常交易日做一次性修复，可执行：
  - `python scripts/repair_missing_ohlc.py --dates 20260210,20260227`
  - `python scripts/repair_missing_ohlc.py --dates 20260210,20260227 --apply`

## 5. 建议流程

1. 交易日收盘后先跑 `daily_incremental_update.py`
2. 再跑 `daily_ml_select.py`
3. 每周或每月重训一次 `train_mfts_lgbm.py`
4. 用 `verify_historical.py` 观察收益稳定性

## 6. 常见问题

- 模型加载失败：确认 `models/` 下存在 `.pkl` 文件。
- 训练过慢：先缩短训练区间，确认流程后再全量训练。
- 内存压力大：关闭其他进程，或按时间段分批训练。
