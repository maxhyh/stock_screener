# 研究脚本

本目录存放偏研究、分析、实验用途的脚本。

特征：

- 不属于日常生产主链路
- 常用于因子分析、容量评估、实验性选股
- 可根据研究结论反哺 `quant_*` 或 `daily_*` 主链路

当前内容：

- `analyze_factor_ic.py`：因子 IC 分析
- `capacity_estimation.py`：策略容量估计
- `daily_hybrid_select.py`：v6.2 + ML 融合选股实验

建议：

- 研究结论若稳定，应迁移回主链路
- 临时研究脚本不要直接写进 `scripts/` 根目录
