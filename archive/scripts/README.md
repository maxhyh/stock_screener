# 归档脚本

本目录存放已退出主维护面的脚本实现。

这些脚本具备以下特征之一：

- 已被新的 `quant_*` / `daily_*` 主链路替代
- 仅保留历史参考价值
- 强依赖旧环境或实验性依赖，不适合继续作为默认入口

当前归档内容：

- `backtest.py`：旧版规则回测入口，已被 `scripts/quant_portfolio_backtest.py` 等替代
- `optimize.py`：旧版参数优化入口，已被 `scripts/quant_optimize.py` 替代
- `qlib_integration.py`：Qlib 试验性集成脚本，非当前生产链路
- `debug_download.py`：一次性下载调试脚本

维护原则：

- 新功能不要继续加在这里
- 若需要复用能力，应迁移到生产主链路或研究主链路后再维护
