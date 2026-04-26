# MFTS 更新日志

## [3.0.0] - 2026-04-15

### 🧠 策略核心优化

- **LambdaRank 排序学习**: ML 训练从 `regression/RMSE` 切换到 `lambdarank/NDCG`，模型聚焦 Top-N 排序质量而非绝对收益预测。通过 `MFTS_TRAIN_OBJECTIVE=regression` 环境变量可回退。
- **截面标准化**: 新增 Cross-Sectional Z-Score，逐日对因子做截面归一化（`{factor}_cs` 列），消除不同市场环境的绝对值差异。
- **5 个正交因子**: 新增与超跌因子低相关的维度：
  - `smart_money_ratio` — CLV×成交量聪明钱流向
  - `rs_5d` / `rs_20d` — 个股 vs 市场中位数相对强弱
  - `vol_compression` — 波动率压缩比（ATR5/ATR20）
  - `gap_zscore` — 隔夜跳空标准化
  - `vp_divergence` — 量价背离强度
- **排序标签构建**: 收益率按日截面分 5 档（qcut），适配 LambdaRank 训练
- **模型评估增强**: 新增 ICIR、Top10 胜率/平均收益指标

### 🏗️ 生产基础设施

- **盘中风控** (`core/risk/intraday_monitor.py`): 日内回撤熔断 (-3%/-5%)、单票止损 (7%)、面值退市保护、连续亏损降仓
- **仓位对账** (`core/execution/reconciliation.py`): 本地 vs 券商逐标的比对，NAV 1% 差异阈值
- **告警推送** (`utils/alert.py`): console/微信企业号/钉钉/Telegram 四通道
- **策略容量评估** (`scripts/capacity_estimation.py`): ADV20 × 参与率，三档估计
- **自动再训练** (`scripts/auto_retrain.py`): 4 项触发条件 + IC 衰减分析
- **日度风控报告** (`scripts/daily_risk_report.py`): 持仓明细/行业分布/退市预警
- **OOS 准入检查**: Walk-Forward 新增 6 项准入标准 + IS/OOS 过拟合检测
- **Cron 执行链升级**: 生产级调度（15:30→16:00→16:30→17:00→09:15）

### 🐛 修复（前次审计）

- 修复 `log_ret` 跨股票数据泄漏（使用 grouped shift）
- 修复 VWAP 累积计算错误（改为日均价）
- 修复动态退出前瞻偏差（trigger 用 close，execution 用 next-day open）
- 新增印花税 0.05% 卖出单边
- 新增北交所 9-prefix 30% 涨跌停支持
- 新增停牌保护（ffill limit=3 + 连续停牌 >3 天置 NaN）


## [2.1.0] - 2026-03-22

### 🐛 修复
- **开盘价缺失防回退修复**: `scripts/daily_verify.py` 新增 `open_filled` 回填逻辑（优先前收、其次当日收盘），显著降低 `open_to_open` / `open_to_close_t1` 因缺开盘价触发 `close_to_close_t1(fallback)` 的频率。
- **数据修复脚本补充**: 新增 `scripts/repair_missing_ohlc.py`，支持对指定交易日做 OHLC 缺失修复（预览/落盘两种模式）。
- **增量更新防复发**: `scripts/daily_incremental_update.py` 增加 OHLC 缺失回填步骤，防止批量接口异常导致 `open` 大面积缺失再次传导到下游。

### ⚙️ 配置更新
- **量化回测默认参数来源统一**: `scripts/quant_portfolio_backtest.py` 改为从 `config/quant_live_profiles.json` 的 `default_profile` 读取默认值，当前默认档位为 `balanced`（`top_n=10`、`holding_days=3`、`max_single_pos=0.06`、`use_regime_position=False`）。
- **训练标签默认持有期对齐实盘档位**: `config/settings.py` 新增配置解析逻辑，`TrainingConfig.LABEL_HORIZON` 默认读取 `default_profile.holding_days`（当前 `balanced=3`），仍支持 `MFTS_LABEL_HORIZON` 环境变量覆盖。
- **新增 A/B 档位与对比脚本**: `config/quant_live_profiles.json` 新增 `balanced_regime`（分市场仓位开关对照）与 `balanced_h8`（持有期对照），并新增 `scripts/quant_profile_ab_compare.py` 输出 `quant_profile_ab_*.csv/json` 对比指标表。

## [2.0.0] - 2026-01-08

### 🐛 修复
- **L2 信号逻辑修复**: 添加了缺失的 `trend_pullback` 分支，现在趋势回调也能触发 L2
- **is_bottom_surge 条件修正**: 从 `close < close_1` 改为 `close < close_5`，匹配 Pine Script 原版
- **变量定义顺序修正**: `trend_pullback` 变量现在在 L2 判断前定义

### ✨ 新增
- **trend_pullback_relaxed**: 添加宽松版趋势回调逻辑 (close ± 5% MA20)
- **项目文档**: README.md, SIGNAL_LOGIC.md, DEPLOYMENT.md
- **项目结构优化**: 按功能分目录组织
- **带日期的输出文件**: 扫描结果现在保存为 `mfts_scan_YYYYMMDD.csv`

### 🗑️ 清理
- 删除冗余脚本: `daily_scan.py`, `daily_scan_server.py`, `mfts_server_optimized.py`, `mfts_screener_optimized.py`
- 合并为单一 `mfts_screener.py`

### 📊 预期影响
修复后应显著增加 L2/L3 信号数量，特别是趋势回调类型的信号。

---

## [1.0.0] - 2026-01-07

### 初始版本
- 完整复刻 Pine Script MFTS v6.1 逻辑
- Alpha 评分系统
- 分层超跌豁免机制
- Web 仪表盘
- AKShare 数据下载

---

## 待办事项

- [ ] 添加 `effective_is_trend_mode` 战术模式自动切换
- [ ] 添加首板跟随信号 (`is_first_limit_follow`)
- [ ] 优化服务器版本数据加载性能
- [ ] 添加回测模块
