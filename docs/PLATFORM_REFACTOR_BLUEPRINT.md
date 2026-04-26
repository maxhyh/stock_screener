# 量化平台化重构蓝图（A股）

> 更新时间：2026-04-15 07:36
> 目标：从“选股脚本集合”演进到“可回测、可执行、可审计、可风控”的量化平台。
> 平台完成度（当前评估）：
> - 工程能力完成度：约 `88%`（P0/P1/P2 完成，P3 已含一致性门禁、滚动回放、行业恢复闭环）
> - 生产就绪完成度：约 `78%`（实盘网关仍是主缺口；逐笔一致性已补订单级，待分票持仓路径级）

## 1. 总体架构分层

1. 数据层（Data Layer）
- 行情主表：`data/daily_all_5y.parquet`
- 元数据：`data/stock_info.csv`（行业/名称等）
- 数据门禁：覆盖率阈值、元数据完整率门禁、异常修复脚本

2. 研究与信号层（Research & Signal Layer）
- 规则扫描：`core/mfts_screener.py`
- ML 选股：`scripts/daily_ml_select.py`
- 历史验证/回测：`scripts/daily_verify.py`、`scripts/quant_portfolio_backtest.py`、`scripts/quant_optimize.py`
- 信号稳健化：`utils/signal_quality.py`（`signal_quality` + `hybrid_score`）
- 特征重构层：`utils/signal_refactor.py`（`stability_score` + `refactor_score` + `feature_redundancy`）

3. 风险与归因层（Risk & Attribution Layer）
- P1 新增：`scripts/quant_p1_analytics.py`
- 输出：`output/risk/`
  - `risk_exposure_summary_*.csv`
  - `risk_exposure_industry_*.csv`
  - `return_attribution_*.csv`
  - `capacity_cost_*.csv`
  - `p1_analytics_summary_*.json`

4. 执行与审计层（Execution & Audit Layer）
- P2 新增：`scripts/quant_p2_paper_trade.py`
- 输出：
  - `output/execution/`（订单、成交、账本、状态）
  - `output/audit/`（审计日志 JSONL）

5. 编排与运维层（Orchestration & Ops Layer）
- 主编排：`scripts/daily_all.py`
- 可选平台化扩展：`--with-p1`、`--with-p2`
- 状态账本：`output/pipeline_state.json`

## 2. 分阶段交付地图

### P0（已完成）
- 数据契约统一（`ts_code` 标准化）
- A股执行约束（停牌/涨跌停不可成交）
- 元数据行业完整率门禁与回退机制
- 编排稳定性增强（catchup/rebuild/覆盖率门槛）

### P1（已完成）
- 风险暴露报告（状态/行业/集中度）
- 收益归因报告（按市场状态、退出原因、月份）
- 容量与成本诊断（参与率、容量资金估算、回合成本）
- 与主流程解耦，支持独立执行与编排接入

### P2（已完成）
- 纸面 OMS 再平衡（下一交易日开盘撮合）
- 成本模型（手续费、滑点、印花税）
- A股可交易性约束（涨跌停、停牌）
- 审计链路（订单/成交/运行摘要/事件日志）
- 组合状态持久化（现金、持仓、净值）
- 策略优化推荐参数直连执行（`--use-recommendation` / `--recommend-rank`）

### P3（已启动）
- 执行通道抽象层：`core/execution/adapter.py`
- 纸面执行实现迁移：`core/execution/paper_broker.py`
- Live 通道骨架：`core/execution/live_broker.py`（`shadow/gateway`）
- 通道注册：`core/execution/__init__.py:create_broker`
- 编排支持通道参数：`daily_all.py --p2-broker`、`quant_p2_paper_trade.py --broker`
- 编排支持推荐参数透传：`daily_all.py --p2-use-recommendation --p2-recommend-rank`
- 下单前风控硬门禁：`core/risk/pretrade.py`
- 回测-执行一致性报告：`scripts/quant_exec_consistency_report.py`
- 反过拟合流水线：`scripts/quant_anti_overfit_pipeline.py`（WF 稳定区 -> robust 优化）
- 特征重构 A/B 对比：`scripts/quant_signal_refactor_compare.py`（baseline vs refactor）
- 参数一致性：流水线可透传信号质量与重构参数（`min_signal_quality/ml_quality_blend/stability_blend/min_refactor_score`）
- 策略收敛闭环：`quant_optimize -> quant_strategy_paper_recommendations -> quant_p2_paper_trade(dry-run)` 已验证可直连

### P3 最新里程碑（2026-04-10）
1. 严格门槛参数优化收敛：
- 推荐参数：`top_n=8`、`holding_days=8`、`max_single_pos=0.04`、`use_regime_position=True`
- 关键结果：`annual=24.16%`、`excess_annual=9.22%`、`MDD=-10.69%`、`Sharpe=1.54`
2. 执行链路验证：
- P2 dry-run 结果：`filled=6`、`risk_blocked=2`
- 关键产物：`output/backtest/quant_strategy_paper_recommendations.csv`、`output/execution/paper_run_*.json`

### P3 最新里程碑（2026-04-13）
1. 40 日双档执行回放（P2）：
- `alpha_high`：`nav_return=-3.2224%`、`exec_block=17.53%`、`risk_block=30.03%`
- `low_turnover`：`nav_return=-2.4882%`、`exec_block=17.60%`、`risk_block=32.94%`
2. 40 日风控参数网格（`low_turnover`）：
- 最优参数：`risk_max_industry_weight=0.35`、`risk_max_adv_participation=0.06`、`risk_min_price=2.0`
- 相对 `adv=0.05`：`nav +1.4137pct`、`exec_block -0.31pct`、`risk_block -1.27pct`
3. 工程落地：
- `quant_p2_paper_trade.py` 支持从 profile 继承执行与风控默认值（含 `fee/slippage/risk_*`）
- `daily_all.py` 新增 P2 风控透传参数：`--p2-risk-max-industry-weight`、`--p2-risk-max-adv-participation`、`--p2-risk-min-price`
- `right_h8_low_turnover` profile 固化风控参数，减少“命令层参数漂移”风险
4. 运行稳定性补丁：
- 验证目标改为 horizon-aware（按 `label_mode/label_horizon` 过滤可验证日期）
- `daily_verify.py` 增加非严格跳过机制（无样本不再拉红主流程）
- `resolve_default_label_horizon` 支持 `MFTS_ACTIVE_PROFILE`，研究/执行档位口径可对齐
- P2 新增默认 `exclude_st` 过滤，避免 ST 股票进入执行
- 元数据行业映射新增 spot 字段回退，提升行业覆盖恢复能力

### P3 最新里程碑（2026-04-14）
1. 行业覆盖率硬门禁接入编排：
- `daily_all.py` 新增 `--min-industry-coverage-pct`（默认 80）与 `--disable-industry-coverage-gate`
- 行业覆盖不足时，自动阻断 P2/P3，防止失真风控结果继续扩散
2. 行业元数据恢复闭环打通：
- `daily_incremental_update.py` 新增新浪行业兜底（`stock_sector_spot + stock_sector_detail(label)`）
- 新增 `refresh_stock_metadata()`，并在“数据已最新”分支自动刷新元数据
- 实测 `stock_info.csv` 行业覆盖恢复至 `91.89%`（`5055/5501`），门禁稳定通过
3. 一致性报告升级为“可门禁诊断”：
- `quant_exec_consistency_report.py` 新增 run_id 级主因拆解（订单阻塞原因、风控拦截原因）
- 新增阈值参数与 `--enforce-thresholds`，支持 CI/编排失败快返
- `daily_all.py` 已打通 P3 阈值参数透传
4. 一致性口径对齐优化：
- P3 默认自动择优 `quant_trades`（按与 ledger 交易日重叠度）
- P3 默认按交易日去重 ledger（保留同日最后一次 run）
- P3 默认按 expected 时间窗过滤 ledger，减少窗口外样本稀释
- 新增 `rate-eval-rows` 滚动窗口（默认 10）用于订单/风控阻塞率门槛计算
5. 严格门槛验收：
- `daily_all.py ... --with-p3-consistency --p3-enforce-thresholds` 已实测全流程通过
6. 回放评估能力升级：
- `quant_p2_paper_trade.py` 新增 `--channel`，支持同 broker 下隔离账本/订单/审计
- 新增 `quant_p2_rolling_replay.py`，支持 `profiles x windows(60/90/120)` 的滚动回放与多指标目标评分
7. 风格暴露硬门禁落地：
- `core/risk/pretrade.py` 新增组合风格门禁（Size/Beta/Momentum/Vol）
- `quant_p2_paper_trade.py` / `daily_all.py` 新增风格参数透传与账本统计字段
- `right_h8_low_turnover` profile 固化默认风格阈值（可命令行覆盖）
8. style 阈值网格回放：
- `quant_p2_rolling_replay.py` 新增 style 网格参数（size/beta/momentum/vol/lb）
- 汇总新增 `style_hit_rate_pct` 等指标，支持“收益-回撤-阻塞-风格拦截”联动评分
9. 一致性报告升级（风格归因 + 逐笔回放）：
- `quant_exec_consistency_report.py` 新增 `style_hit` 分层归因输出
- 新增逐笔（订单级）一致性回放明细/分层/摘要产物
10. 信号端前置风控联动闭环：
- `daily_ml_select.py` 新增前置风控门禁（复用 `core/risk/pretrade.py`）
- `daily_all.py` Step3 自动透传 P2 风控阈值到 ML（`MFTS_RISK_*`）
- 新增信号端拦截明细产物：`output/risk/signal_pretrade_gates_*.csv`
11. 前置风控一致性诊断：
- 新增 `quant_signal_pretrade_alignment_report.py`，可逐日对齐“信号端前置风控 vs P2风控”
- 新增 `signal_pretrade_summary_*.json`，沉淀 gate trade_date/pool_n/top_reason
- 修复节假日 trade_date 错位（前瞻窗口下限）

## 3. 关键接口契约

1. 信号输入契约
- 文件：`output/daily/daily_YYYYMMDD.csv`
- 必备列：`代码`、`名称`、`ML评分`
- 可选列：`建议仓位`、`单票上限`、`排名`、`质量分`、`综合分`、`稳定分`、`重构分`

2. 回测输入契约
- 文件：`output/backtest/quant_trades_*.csv`
- 必备列：`entry_date`、`codes`、`weights`、`total_exposure`、`portfolio_ret`

3. 审计输出契约
- `output/audit/paper_audit_log.jsonl` 每行一条事件，需包含：`run_id`、`signal_date`、`trade_date`、`filled/blocked/rejected`、`nav_post`

## 4. 下一阶段（P3）重点

1. 真实交易网关抽象
- 统一 `BrokerAdapter`：仿真/实盘同接口，减少“回测-实盘双代码”分叉。

2. 组合级风控前置
- 下单前风控（行业/流动性/集中度 + 风格暴露） hard check 已落地，下一步补“滚动窗口阈值校准 + 风险预算联动”。

3. 监控与告警
- 引入“数据覆盖异常、成交失败率、风控拒单率、净值异常回撤”告警面板与消息推送。

4. 回测-执行一致性回放
- 日级偏差报告与阈值门禁、订单级逐笔回放已落地，后续需补“分票持仓路径偏差归因”。
