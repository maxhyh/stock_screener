# 项目优化维护计划

更新时间：2026-04-16

## 当前基线

- 测试状态：`129 passed, 3 skipped`
- 热点快照：
  - `lookahead=62`
  - `performance=149`
  - `robustness=369`
  - `execution=271`
- Top hot files：
  - `core/mfts_screener.py`
  - `scripts/quant_portfolio_backtest.py`
  - `scripts/quant_p2_paper_trade.py`
  - `scripts/daily_incremental_update.py`
  - `scripts/daily_ml_select.py`

## P0 立即处理

### 1. 执行状态安全

- 问题：`paper_broker` 状态文件损坏时会静默回退到初始资金和空仓。
- 风险：伪造 NAV、成交和持仓，属于实盘一致性最高风险项。
- 目标：
  - 状态文件损坏时 fail-closed。
  - 需要显式 `reset_state` 才允许重建账户状态。
  - 增加损坏状态文件回归测试。

### 2. 元数据硬门禁外溢

- 问题：行业覆盖率门禁主要在编排层生效，独立脚本仍可能继续跑。
- 风险：行业风控、行业归因和回测分散约束失真。
- 目标：
  - 为独立执行入口增加显式 `fail_on_low_coverage` 选项。
  - 统一输出覆盖率、新鲜度和来源统计。

## P1 高价值优化

### 1. 指标链路性能重构

- 模块：`core/mfts_screener.py`
- 症状：大量 `groupby().transform(lambda x: x.rolling(...))` 导致 CPU 和内存开销过高。
- 目标：
  - 合并重复 rolling 计算。
  - 优先改造最重的均线、区间高低点、相关性、KDJ、MFI 链路。
  - 引入 profiling 基线，对比优化前后耗时。

### 2. 训练数据真正流式化

- 模块：`scripts/train_mfts_lgbm.py`
- 症状：先全量读 parquet，再按股票分批切片，仍有 OOM 风险。
- 目标：
  - 改成真正分块读取。
  - 减少中间 DataFrame 复制。
  - 保证 IC 选特征、标签生成、截面标准化口径不变。

### 3. 权重分配逻辑收敛

- 模块：
  - `core/risk/pretrade.py`
  - `core/execution/paper_broker.py`
  - `scripts/quant_portfolio_backtest.py`
- 症状：权重分配逻辑多处复制，后续易漂移。
- 目标：
  - 抽成共享模块。
  - 增加 parity tests，确保信号、回测、执行口径一致。

## P2 工程稳定性

### 1. 数据质量报表

- 输出缺失 OHLC、缺失 amount/vol、行业覆盖率、接口来源占比。

### 2. 风控统计标准化

- 统一缺失行业、未知行业命中、ADV 限制、风格暴露命中的字段名和落盘口径。

### 3. 日选股扩池降重

- 复用排序结果、bars 索引和风控中间结果，减少重复计算。

## 推荐执行顺序

1. 修复 `paper_broker` 状态安全。
2. 给独立执行入口补元数据硬门禁。
3. 收敛权重分配模块。
4. 重构 `core/mfts_screener.py` 热点链路。
5. 重构训练流式读取。

## 本轮已完成

- 前置风控改为拦截后迭代重算权重。
- IC 选特征保留未映射因子名，避免静默丢失。
- 回测 benchmark 改成 exposure-adjusted 口径。
- 前置风控与回测统一“未知行业桶”约束。
- `paper_broker` 状态文件损坏时改为 fail-closed，并增加隔离与回归测试。
- `quant_p2_paper_trade.py` 与 `quant_portfolio_backtest.py` 增加元数据覆盖率/新鲜度硬门禁。
- `daily_ml_select.py` 也接入元数据覆盖率/新鲜度硬门禁，补齐独立入口。
- 权重分配逻辑抽到共享模块，并修复“封顶后又超单票上限”的再分配缺陷。
- `core/mfts_screener.py` 首轮性能重构完成，rolling mean/min/max/std/sum 大量改为 grouped rolling helper，并移除 `pv_corr` 的 `lambda + df.loc[...]` 热点路径。
- `core/platform/` 平台骨架 Phase 1 已落地，补上运行 manifest、实验注册、订单状态机、统一组合/风险门面、观测告警、安全治理、profiling 基线与平台 API 入口。
- `quant_portfolio_backtest.py` 与 `quant_p2_paper_trade.py` 已接入平台 run manifest；P2 订单输出新增生命周期标准化字段，便于后续一致性分析与执行看板。
- `quant_p2_rolling_replay.py` 现在会为单 profile 输出独立的 `summary/runs/meta/latest` 文件，避免并行 replay 时同秒覆盖工件。
- `quant_p2_shadow_diagnosis.py` 支持自动聚合多份 profile summary，并沉淀 NAV 路径、ADV 拦截、行业集中三条执行侧证据。
- 新增 `quality_regime_candidate_v3`，把连续 ADV 容量惩罚与行业拥挤惩罚接进日选股与回测的统一执行层排序覆盖逻辑。
- `quality_regime_candidate_v3` 的 20 日 P2 shadow 已验证：
  - 执行后 NAV 从 `candidate` 的 `-0.96%` 提升到 `-0.66%`
  - 最大回撤从 `-1.41%` 收窄到 `-0.94%`
  - `adv_blocked_rows` 从 `17` 降到 `15`
  - 但行业集中仍高于原 `candidate`，`mean_top_industry_weight` 仍在 `35.69%`

## 当前验证状态

- 全量测试：`202 passed, 3 skipped`
- 最新执行层 shadow 工件：
  - `output/backtest/quant_p2_shadow_diagnosis_latest.csv`
  - `output/backtest/quant_p2_shadow_diagnosis_latest.json`

## 下一目标

- 继续围绕 `quality_regime_candidate_v3` 压行业集中，而不是再回到盲调 `TopN / hold`。
- 在执行层排序覆盖里加入更明确的行业软上限再分散逻辑，目标把 `mean_top_industry_weight` 从 `35%+` 压回 `30%` 一带。
- 将 `execution_lifecycle` 下沉进 `paper_broker` / P2 核心执行流程，而不只是出口标准化。
- 把回测/P2 的 manifest 进一步扩成 artifact lineage 与 schema version 管理。
