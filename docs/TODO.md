# MFTS Stock Screener - TODO List

> 注：本文件包含历史记录（含云服务器阶段事项）。当前执行以本地部署流程为准。

## 项目进度概览

当前阶段：**平台化过渡中（P0已完成，P1/P2已落地，向实盘网关演进）**

---

## 🆕 平台化增量进展（2026-04-10）

### ✅ 已完成
- [x] P1 风险归因模块：`scripts/quant_p1_analytics.py`
  - [x] 风险暴露汇总（状态/集中度/行业）
  - [x] 收益归因（状态/退出原因/月度）
  - [x] 容量与成本评估（参与率/容量资金估算/回合成本）
- [x] P2 纸面 OMS：`scripts/quant_p2_paper_trade.py`
  - [x] 下一交易日开盘撮合（含滑点/手续费/印花税）
  - [x] A股执行约束（停牌/涨跌停）
  - [x] 持仓状态持久化 + 订单/成交/账本
  - [x] 审计日志落地（JSONL）
- [x] `daily_all.py` 编排扩展
  - [x] `--with-p1`
  - [x] `--with-p2`
- [x] 文档补齐
  - [x] `docs/OPTIMIZATION_STATUS.md`
  - [x] `docs/PLATFORM_REFACTOR_BLUEPRINT.md`
- [x] A：策略信号稳健化
  - [x] `utils/signal_quality.py`（质量分 + 综合分）
  - [x] `daily_ml_select.py` 接入质量门禁与综合排序
  - [x] `quant_portfolio_backtest.py` 接入质量门禁参数
- [x] C：反过拟合流程固化
  - [x] `scripts/quant_anti_overfit_pipeline.py`
  - [x] `quant_walk_forward.py` 兼容新版硬门槛接口
- [x] B：信号特征重构（Round2）
  - [x] `utils/signal_refactor.py`（`stability_score` + `refactor_score` + `feature_redundancy`）
  - [x] `quant_portfolio_backtest.py` 接入重构参数与门禁
  - [x] `daily_ml_select.py` 接入重构排序与输出列
  - [x] `scripts/quant_signal_refactor_compare.py`（baseline vs refactor A/B 对比）
  - [x] `quant_walk_forward.py` / `quant_optimize.py` / `quant_anti_overfit_pipeline.py` 参数链路打通（WF+优化+报告一致）

### ⏳ 待完成（高优先级）
- [ ] 实盘网关真实接入（当前仅 LiveBroker 抽象 + shadow）
- [x] 下单前组合风控硬门禁（行业/流动性/集中度）
- [x] 回测-执行一致性偏差报告（自动化）

---

## 🎯 当前任务

### 1. ✅ MFTS策略实现（已完成）
- [x] MFTS v6.1 Pine Script完整复刻
- [x] 40+技术指标计算
- [x] Alpha评分系统
- [x] Web界面展示
- [x] 本地部署（已切换）
- [x] 运行MFTS策略回测 (基线测试)

### 2. ✅ MFTS机器学习增强（已完成）
- [x] 制定技术方案（MFTS因子 + LightGBM）
- [x] 运行因子IC分析（10年数据，57分钟完成）
  - 15个因子，2550个交易日
  - Top因子：ATR%, Volume Ratio, BIAS-20
- [x] 训练LightGBM模型（测试集胜率58%，平均收益+1.99%）
- [x] 模型已保存（models/mfts_lgbm_*.pkl）
- [x] 模型部署和集成

### 3. ✅ 每日执行系统（已完成）
- [x] 设计完整流程方案
  - [x] 创建核心脚本
  - [x] daily_mfts_select.py - 纯MFTS选股
  - [x] daily_ml_select.py - ML增强选股
  - [x] scripts/research/daily_hybrid_select.py - **v6.2+ML融合选股（新增）**
  - [x] daily_verify.py - T+1验证
  - [x] verify_historical.py - 历史验证（T+1/T+5/T+10）
  - [x] daily_incremental_update.py - 数据更新
  - [x] scripts/history/backtest_5y.py - 5年完整回测（流式处理）
  - [x] scripts/history/backtest_comparison.py - 策略对比
  - [x] scripts/history/backtest_v62_compare.py - **v6.1 vs v6.2对比（新增）**
- [x] 扩展Web API（历史验证API）
- [x] 创建历史验证页面
- [x] 建立本地手动执行流程（daily_all.py）
- [x] 流程测试通过
- [ ] 测试完整流程

### 4. ✅ v6.2策略优化（已完成）
- [x] IC因子分析（识别最强因子）
- [x] 5年回测脚本（2023-2025）
- [x] v6.2核心代码（core/mfts_screener_v62.py）
  - [x] 权重调整（ATR×3.0，量比×2.5，ADX×0.1）
  - [x] 动态阈值机制
  - [x] 信号质量过滤（alpha≥5）
  - [x] 风控增强（新股120天）
- [x] v6.1 vs v6.2对比回测（T+5收益改善+0.84%）
- [x] 优化指南文档（docs/MFTS_OPTIMIZATION.md）
- [ ] A/B测试验证优化效果

### 5. ✅ 信号分析优化与前端增强（进行中）
- [x] 创建信号分析页面 (`signal_analysis.html`)
- [x] 升级分析脚本 (`analyze_signal_performance.py`)
- [x] 添加月度趋势图表
- [x] 优化表格排序和筛选体验
- [ ] 整合至每日自动化流程 (`daily_all.py`)
- [ ] 修复历史回测数据自动更新

### 6. 📝 文档更新（进行中）
- [x] 更新 README.md
- [x] 更新 TODO.md
- [ ] 更新 LOCAL_GUIDE.md

---

## 🚀 下一步工作

### 立即任务（模型训练完成后）
1. **验证模型效果**
   ```bash
   # 查看模型报告
   cat models/mfts_lgbm_*_report.txt
   
   # 查看Feature Importance
   # 使用此信息优化MFTS
   ```

2. **执行本地每日流程**
   ```bash
   cd /path/to/stock_screener
   conda activate stock
   python scripts/daily_all.py
   ```

3. **运行5年回测**
   ```bash
   python scripts/history/backtest_5y.py
   python scripts/history/backtest_comparison.py --days 30
   ```

### 短期任务（1周内）
1. [ ] 基于IC和Feature Importance优化MFTS权重
2. [ ] A/B测试对比优化效果
3. [ ] 模拟盘测试3-5天
4. [ ] 完善监控和日志系统

### 中期任务（1月内）
1. [ ] 实盘小资金测试
2. [ ] 策略参数自适应优化
3. [ ] 多市场支持（可选）
4. [ ] 移动端适配

---

## 📊 项目里程碑

- ✅ **2026-01-08** - MFTS v6.1完整实现
- ✅ **2026-01-09** - IC分析完成
- 🔄 **2026-01-09** - LightGBM训练（进行中）
- ✅ **2026-03-19** - 切换为本地手动流程
- ⏳ **2026-01-15** - 5年回测完成
- ⏳ **2026-01-20** - 策略优化和实盘测试

---

## 🎁 已完成的重要功能

### 数据和基础设施
- ✅ AKShare数据下载（5年全市场）
- ✅ 本地部署流程稳定运行
- ✅ 虚拟环境配置（qlib_env）
- ✅ Parquet数据存储（高效）

### 核心算法
- ✅ MFTS v6.1 100%复刻
- ✅ 40+技术指标计算
- ✅ Alpha评分系统
- ✅ 流式数据处理（内存优化）

### ML增强
- ✅ IC因子分析脚本
- ✅ LightGBM训练脚本
- ✅ Feature选择逻辑
- ✅ 模型评估框架

### 日常流程
- ✅ 双策略选股（MFTS + ML）
- ✅ T+1验证系统
- ✅ 历史验证（T+1/T+5/T+10）
- ✅ 一键执行脚本（`daily_all.py`）

### 回测和验证
- ✅ 5年完整回测脚本
- ✅ 策略对比工具
- ✅ 历史验证分析
- ✅ 可视化图表生成

### Web界面
- ✅ Flask后端API（6个端点）
- ✅ ML选股展示页面
- ✅ 历史验证页面
- ✅ 实时数据刷新

### 文档
- ✅ README（全面更新）
- ✅ 实战应用指南
- ✅ ML训练指南
- ✅ 优化指南
- ✅ 本地手动流程文档
- ✅ 多个artifacts文档

---

## 💡 待优化项

### 性能优化
- [ ] 选股速度优化（目标<30秒）
- [ ] Web界面缓存
- [ ] 数据库化（可选，当前CSV足够）

### 功能增强
- [ ] 实时盯盘提醒
- [ ] 微信/邮件推送
- [ ] 止盈止损自动提醒
- [ ] 持仓管理系统

### 策略研究
- [ ] 卖出信号优化
- [ ] 仓位管理优化
- [ ] 多周期结合
- [ ] 板块轮动识别

---

**最后更新**: 2026-04-10 12:11
**下一次review**: P3（实盘网关抽象）首版完成后
