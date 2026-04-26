# 历史生成与旧回测脚本

本目录存放批量历史生成、旧式回测和对比验证脚本。

特征：

- 主要服务历史回放、离线生成、版本对比
- 不属于日常生产运行入口
- 部分脚本仍有参考价值，但不建议与 `quant_*` 主回测链路混用

当前内容：

- `backtest_5y.py`
- `backtest_comparison.py`
- `backtest_mfts_6m.py`
- `backtest_v62_compare.py`
- `generate_historical_ml.py`
- `generate_historical_scans.py`
- `generate_historical_scans_6m.py`

建议：

- 日常组合回测优先使用 `scripts/quant_portfolio_backtest.py`
- 参数搜索优先使用 `scripts/quant_optimize.py`
