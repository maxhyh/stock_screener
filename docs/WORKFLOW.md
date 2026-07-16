# MFTS 选股系统 - 操作流程

> 说明：
> - 看“项目结构/代码入口”请转到 `docs/PROJECT_INDEX.md`
> - 看“文档去哪找”请转到 `docs/README.md`
> - 看“脚本该不该用”请转到 `scripts/README.md`

## 📋 日常操作流程

### 每日流程图

```
┌─────────────────────────────────────────────────────────┐
│                    交易日收盘后 (18:00+)                   │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│  Step 1: 激活环境                                        │
│  $ conda activate stock                                 │
│  $ cd /Users/max/Desktop/Projects/trading/stock_screener  │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│  Step 2: 运行一键更新脚本                                 │
│  $ python scripts/daily_all.py                          │
│                                                         │
│  自动执行:                                               │
│  ├── 增量数据更新 (从东方财富获取)                         │
│  ├── MFTS 规则选股扫描                                    │
│  └── ML 模型预测                                         │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│  Step 3: 运行信号分析 (可选)                             │
│  $ python scripts/analyze_signal_performance.py         │
│  (生成最新统计数据)                                      │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│  Step 4: 查看结果                                        │
│  浏览器访问: http://127.0.0.1:5001                       │
│  (如 Web 服务未运行，先执行 python web/app.py)            │
└─────────────────────────────────────────────────────────┘
```

---

## 🔧 各功能模块说明

### 1. Web 服务 (查看结果)
```bash
conda activate stock
python web/app.py
```
- 访问地址: http://127.0.0.1:5001
- 功能: 交易平台总览（执行清单/风险指标/回测表现/参数候选）+ 选股详情
- 运行模式: 后台持续运行
- 前端展示:
  - 首页默认即“交易平台总览”视图，整合 `daily/scan/verify/backtest/optimize` 结果
  - 股票统一展示“名称（代码）”，并支持点击查看个股详情
  - 涨跌和收益采用 A 股习惯配色（红涨绿跌）
  - 首页可点击股票查看个股详情（K线）与关联交易记录
  - 首页包含最近组合交易执行记录表（信号日/入场/出场/组合收益/权益）
  - 首页新增收益率钻取面板（年 -> 月 -> 交易日，图表与明细联动）
  - `/ml` 页面同步展示分市场仓位建议标签（正常/震荡/恐慌）
  - 首页日期选择器新增“日期可用性提示”（有结果/低覆盖/未重算/无主数据）

### 2. 一键全流程更新
```bash
python scripts/daily_all.py
```
- 执行时间: 收盘后 (建议 18:00-18:30)
- 超时设置: 每步 5 分钟
- 输出位置: `output/` 分层目录（`scan/`, `daily/`, `verify/`, `backtest/`）
- 运行模式:
```bash
# 仅跑最新交易日
python scripts/daily_all.py --mode latest

# 收盘前自动使用上一交易日（默认阈值 18:00，可按需调整）
MFTS_AUTO_TARGET_CUTOFF_HOUR=18 python scripts/daily_all.py --mode latest

# 说明：若主数据已覆盖目标日，latest 模式会跳过增量下载（避免冗余补数）
# 同时仍可执行后续扫描/ML/P1/P2/P3，行业门禁依然生效

# 默认模式：补齐最近缺口（适合隔几天更新）
python scripts/daily_all.py --mode catchup --catchup-days 10

# 只做验证补齐
python scripts/daily_all.py --mode verify-only --catchup-days 10

# 验证阶段增加覆盖率门槛（避免低覆盖交易日失真）
python scripts/daily_all.py --mode catchup --catchup-days 10 --verify-min-stocks 3000

# 扫描/ML 也增加覆盖率门槛（建议开启，避免“仅20只股票”也参与推荐）
python scripts/daily_all.py --mode catchup --catchup-days 10 --stage-min-stocks 3000 --verify-min-stocks 3000

# 策略升级后重算最近20个交易日（覆盖已有结果）
python scripts/daily_all.py --mode catchup --rebuild-days 20 --stage-min-stocks 3000 --verify-min-stocks 3000

# 平台化扩展：追加 P1（风控归因）+ P2（纸面 OMS）
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --p2-broker paper --p2-dry-run

# 追加 P3：回测 vs 执行一致性偏差报告
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --with-p3-consistency --p2-broker paper --p3-broker paper --p2-dry-run

# P3 增加阈值门禁（不达标直接失败）
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --with-p3-consistency \
  --p2-broker paper --p3-broker paper --p2-dry-run \
  --p3-max-ret-gap-mae-pct 2.0 --p3-min-match-coverage-pct 60 \
  --p3-max-order-block-rate-pct 35 --p3-max-risk-block-rate-pct 35 \
  --p3-min-matched-rows 20 --p3-rate-eval-rows 10 --p3-enforce-thresholds

# 说明：P3 默认会自动择优 trades 文件、按交易日去重 ledger，并使用 expected 时间窗对齐比较
# 说明：--p3-rate-eval-rows 仅作用于订单/风控阻塞率门槛（收益偏差与覆盖率仍按全匹配样本）

# 行业门禁阈值（默认80）；仅排障时可临时关闭
python scripts/daily_all.py --mode latest --with-p2 --with-p3-consistency --min-industry-coverage-pct 80
python scripts/daily_all.py --mode latest --with-p2 --with-p3-consistency --disable-industry-coverage-gate

# 验证口径切换（默认 open_to_close_t1）
python scripts/daily_verify.py --date 20260320 --label-mode open_to_close_t1

# 推荐：与交易系统一致（次日开盘买入，持有 default_profile 对应天数；当前 quality_regime=8 天）
python scripts/daily_verify.py --date 20260320 --label-mode open_to_open --label-horizon 8
```

### 3. 共享 ODS 数据可用性
```bash
export ASHARE_DATA_ROOT=/Users/max/Data/ashare-source-data
python scripts/daily_all.py --mode latest
```
- 本项目仅读取共享 ODS；不会下载、补数、修复或写入数据。
- 数据生产与快照维护由外部供应链负责。若 ODS 未覆盖目标交易日，`daily_all.py` 会停止并记录 `data_availability` 失败。
- 历史研究/执行统一使用 ODS `daily_bars` 分区和最新 snapshot；不得使用 `current_snapshot_only` 作为历史 PIT 数据。

### 6. 组合交易回测（新增）
```bash
# 首次先生成沪深300基准文件
python scripts/build_benchmark_hs300.py --start-date 20100101

# 把每日推荐转成“真实可执行组合”，含成本/仓位/持有期
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20

# 可选：单笔组合止损（例如 -3%）
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 --max-loss-per-trade 0.03

# 新增：策略引擎与基准
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 --engine-mode hybrid --benchmark-mode hs300

# 新增：组合风控增强（行业分散 + 相关性去重 + 动态退出 + 风险开关）
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 --engine-mode hybrid --benchmark-mode hs300 \
  --max-industry-positions 3 --max-pair-corr 0.85 --take-profit 0.18 --stop-loss 0.08 --trail-drawdown 0.10 \
  --risk-window 5 --risk-cut-win-rate 0.35 --risk-cut-avg-ret -0.005 --risk-cut-factor 0.60

# 新增：分市场参数（正常/震荡/恐慌）
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 \
  --tp-normal 0.18 --tp-choppy 0.14 --tp-panic 0.10 \
  --sl-normal 0.08 --sl-choppy 0.06 --sl-panic 0.05 \
  --trail-normal 0.10 --trail-choppy 0.08 --trail-panic 0.06 \
  --corr-normal 0.85 --corr-choppy 0.75 --corr-panic 0.65

# 新增：信号质量门禁（默认开启）
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 \
  --min-signal-quality 0.35 --ml-quality-blend 0.85 --max-abs-pct-chg 9.0

# 新增：信号特征重构（稳定性融合 + 重构门禁）
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 \
  --stability-blend 0.20 --min-refactor-score 0.45

# 回退旧排序（关闭重构）用于A/B验证
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 --disable-feature-refactor
```
- 默认参数来源：`config/quant_live_profiles.json` 的 `default_profile`（当前 `quality_regime`）
- 当前默认（quality_regime）：`top_n=13`、`holding_days=8`、`max_single_pos=0.04`、`fallback_total_position=0.60`
- `balanced`、`balanced_regime`、`balanced_h8` 仍可作为历史对照档，但不是当前默认档
- 默认排除：北交所 `9` 开头代码（不参与选股/回测）
- 新增对标指标：`benchmark_annual_return_pct`、`excess_annual_return_pct`、`beat_rate_pct`、`info_ratio`
- 策略模式：`left`（偏左侧）/`right`（偏右侧）/`hybrid`（随市场切换）
- 主要输出：
  - `output/backtest/quant_trades_*.csv`（交易明细）
  - `output/backtest/quant_backtest_summary.csv`（汇总指标）
  - `signal_quality_mean`（单笔交易平均信号质量，写入交易明细）
  - `stability_score_mean` / `refactor_score_mean`（特征重构统计，写入交易明细）

### 7. 参数优化（新增）
```bash
# 网格优化：TopN/持有天数/单票上限/是否启用分市场仓位
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20

# 新增：多目标评分 + 失效原因 + 模拟盘推荐参数表
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 \
  --robust-mode on \
  --min-annual-return-pct 0 --min-excess-annual-pct 0 --min-sharpe 0 --max-drawdown-limit-pct -15 \
  --turnover-cap-pct 4500 \
  --recommend-top-k 5

# 新增：指定策略引擎与基准（推荐先用 hybrid + hs300）
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 --engine-mode hybrid --benchmark-mode hs300

# 新增：参数优化可直接评估组合风控增强参数
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 --engine-mode hybrid --benchmark-mode hs300 \
  --max-industry-positions 3 --max-pair-corr 0.85 --take-profit 0.18 --stop-loss 0.08 --trail-drawdown 0.10

# 分市场参数也可接入优化器
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 --engine-mode hybrid --benchmark-mode hs300 \
  --tp-normal 0.18 --tp-choppy 0.14 --tp-panic 0.10 \
  --sl-normal 0.08 --sl-choppy 0.06 --sl-panic 0.05 \
  --trail-normal 0.10 --trail-choppy 0.08 --trail-panic 0.06 \
  --corr-normal 0.85 --corr-choppy 0.75 --corr-panic 0.65

# 新增：优化后自动生成分市场参数建议（输出 quant_regime_suggestion.json）
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 --engine-mode hybrid --benchmark-mode hs300 --auto-regime-tune on

# 新增：稳健评分（默认开启）- 优先 OOS 超额与回撤稳定
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 --engine-mode hybrid --benchmark-mode hs300 --robust-mode on --oos-warmup-months 6 --oos-test-months 2 --oos-step-months 2

# 新增：优化时同步启用特征重构参数
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 \
  --engine-mode hybrid --benchmark-mode hs300 \
  --stability-blend 0.20 --min-refactor-score 0.45
```
- 默认网格已切换为低频偏实盘参数：
  - `top_n`: 10,12,15,20
  - `holding_days`: 3,5,8,10
  - `max_single_pos`: 0.04,0.06,0.08
- 评分函数含“年化换手惩罚”
- 评分与筛选规则（2026-03 更新）：
  - 先硬门槛筛选：`annual_return_pct > 0`、`sharpe > 0`、`max_drawdown_pct > -15`、`excess_annual_return_pct > 0`
  - 稳健模式下，额外要求 OOS 稳健门槛：`oos_excess_annual_median > 0`、`oos_mdd_worst > -15`、`oos_pass_rate >= 45%`
  - 在门槛内按综合分排序；若无组合过门槛，自动回退到综合分最高组合
  - 换手惩罚使用归一口径：`annual_turnover_pct / 100`
- 输出：`output/backtest/quant_optimization_results.csv`
- 新增输出：
  - `output/backtest/quant_strategy_paper_recommendations.csv`
  - `output/backtest/quant_strategy_paper_recommendations.json`

### 8. Walk-Forward 滚动验证（新增）
```bash
# 训练窗选参 + 测试窗验证，避免单一区间“过拟合最优”
python scripts/quant_walk_forward.py --start 2025-01-01 --end 2026-03-20 --train-months 6 --test-months 2 --step-months 2 --engine-mode hybrid --benchmark-mode hs300

# 新增：Walk-Forward 启用信号重构参数
python scripts/quant_walk_forward.py --start 2025-01-01 --end 2026-03-20 \
  --train-months 6 --test-months 2 --step-months 2 \
  --engine-mode hybrid --benchmark-mode hs300 \
  --stability-blend 0.20 --min-refactor-score 0.45

# 固定参数模式（覆盖网格）
python scripts/quant_walk_forward.py \
  --start 2025-01-01 --end 2026-03-20 \
  --train-months 6 --test-months 2 --step-months 2 \
  --engine-mode hybrid --benchmark-mode hs300 \
  --benchmark-file /Users/max/Desktop/Projects/trading/stock_screener/data/benchmarks/hs300_daily.csv \
  --top-n 10 --holding-days 3 --max-single-pos 0.06 --no-regime-position \
  --max-loss-per-trade 0.03 \
  --tp-normal 0.18 --tp-choppy 0.14 --tp-panic 0.08 \
  --sl-normal 0.08 --sl-choppy 0.06 --sl-panic 0.04 \
  --trail-normal 0.10 --trail-choppy 0.08 --trail-panic 0.05 \
  --corr-normal 0.85 --corr-choppy 0.75 --corr-panic 0.60
```
- 输出：
  - `output/backtest/quant_walk_forward_windows_*.csv`（每个滚动窗参数与测试指标）
  - `output/backtest/quant_walk_forward_oos_trades_*.csv`（OOS 交易明细）
  - `output/backtest/quant_walk_forward_summary_*.json`（OOS 汇总）

### 8.1 反过拟合两阶段流水线（新增）
```bash
# 先WF找稳定参数区，再在稳定区内做 robust-mode 优化
python scripts/quant_anti_overfit_pipeline.py \
  --start 2025-01-01 --end 2026-03-20 \
  --wf-train-months 6 --wf-test-months 2 --wf-step-months 2 \
  --wf-topn-grid 8,10,12,15,18 --wf-hold-grid 4,5,6,8 --wf-maxpos-grid 0.04,0.05,0.06

# 新增：流水线一键透传信号质量/重构参数到 WF + Optimize
python scripts/quant_anti_overfit_pipeline.py \
  --start 2025-01-01 --end 2026-03-20 \
  --wf-train-months 6 --wf-test-months 2 --wf-step-months 2 \
  --wf-topn-grid 8,10,12,15,18 --wf-hold-grid 4,5,6,8 --wf-maxpos-grid 0.04,0.05,0.06 \
  --min-signal-quality 0.35 --ml-quality-blend 0.85 --max-abs-pct-chg 9.0 \
  --stability-blend 0.20 --min-refactor-score 0.45
```
- 输出：
  - `output/backtest/quant_anti_overfit_report_*.json`
  - `output/backtest/quant_anti_overfit_report_*.md`

### 8.2 Signal Refactor A/B 对比（新增）
```bash
python scripts/quant_signal_refactor_compare.py \
  --start 2026-01-01 --end 2026-03-20 \
  --top-n 10 --holding-days 6 \
  --engine-mode hybrid --benchmark-mode hs300 \
  --stability-blend 0.20 --min-refactor-score 0.45
```
- 输出：
  - `output/backtest/quant_signal_refactor_compare_*.csv`
  - `output/backtest/quant_signal_refactor_compare_*.json`
  - `output/backtest/quant_signal_refactor_compare_*.md`

### 10. 平台化扩展（P1/P2）
```bash
# P1：风险暴露/归因/容量报告
python scripts/quant_p1_analytics.py --write-latest

# P2：纸面 OMS（默认读取最新 daily 推荐）
python scripts/quant_p2_paper_trade.py --broker paper --write-latest

# P2：隔离输出通道（用于回放/实验，不污染主 paper 账本）
python scripts/quant_p2_paper_trade.py --broker paper --channel paper_exp_a --write-latest
python scripts/quant_p2_paper_trade.py --broker live --live-mode shadow --write-latest

# P2：自动套用优化推荐参数（覆盖 top_n/max_single_pos）
python scripts/quant_p2_paper_trade.py --broker paper --use-recommendation --recommend-rank 1 --dry-run --write-latest

# P2：风格因子预交易门禁（Size/Beta/Momentum/Vol）
python scripts/quant_p2_paper_trade.py --broker paper --dry-run --write-latest \
  --risk-max-style-size-exposure-abs 1.1 --risk-max-style-beta-exposure-abs 1.1 \
  --risk-max-style-momentum-exposure-abs 1.2 --risk-max-style-vol-exposure-abs 1.3 \
  --risk-style-lb-short 20 --risk-style-lb-beta 60

# 编排中透传推荐参数到 P2
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --p2-broker paper --p2-dry-run --p2-use-recommendation --p2-recommend-rank 1

# P3：回测-执行一致性偏差报告
python scripts/quant_exec_consistency_report.py --broker paper --write-latest

# P3：开启阈值强制（CI/编排推荐）
python scripts/quant_exec_consistency_report.py --broker paper --rate-eval-rows 10 --write-latest --enforce-thresholds

# P2：多窗口滚动回放（隔离 channel，不污染主 paper 账本）
python scripts/quant_p2_rolling_replay.py --profiles right_h8_low_turnover --windows 60,90,120 --broker paper --write-latest

# P2：style 阈值网格回放（避免阈值拍脑袋）
python scripts/quant_p2_rolling_replay.py \
  --profiles right_h8_low_turnover --windows 7 --broker paper \
  --risk-max-industry-weight 0.35 --risk-max-adv-participation 0.06 --risk-min-price 2.0 \
  --style-size-grid 0.7,0.9,1.1 --style-beta-grid 0.7,0.9,1.1 \
  --style-momentum-grid 1.0,1.2,1.4 --style-vol-grid 0.9,1.1,1.3 \
  --style-lb-short-grid 20 --style-lb-beta-grid 60 \
  --write-latest
```
- P1 产物：`output/risk/`
  - `risk_exposure_summary_*.csv`
  - `risk_exposure_industry_*.csv`
  - `return_attribution_*.csv`
  - `capacity_cost_*.csv`
- P2 产物：
  - `output/execution/paper_orders_*.csv`
  - `output/execution/paper_fills_*.csv`
  - `output/execution/paper_risk_gates_*.csv`
  - `output/execution/paper_ledger.csv`
  - `output/audit/paper_audit_log.jsonl`
- P3 产物：
  - `output/risk/exec_consistency_paper_*.csv`
  - `output/risk/exec_consistency_summary_paper_*.json`
  - `output/risk/exec_consistency_style_attribution_*.csv`
  - `output/risk/exec_tick_replay_*.csv`
  - `output/risk/exec_tick_replay_layer_*.csv`
  - `output/risk/exec_tick_replay_summary_*.json`

### 9. 实盘参数档位运行（新增）
```bash
# 按配置档位运行（配置文件：config/quant_live_profiles.json）
python scripts/run_quant_profile.py --profile quality_regime --start 2025-01-01 --end 2026-03-20
python scripts/run_quant_profile.py --profile quality_regime_candidate_v18_balanced_trap_guard --start 2025-01-01 --end 2026-03-20
python scripts/run_quant_profile.py --profile quality_regime_candidate_v23_nav_weighted_style_gate --start 2025-01-01 --end 2026-03-20

# A/B 对比（默认主档 vs shadow 诊断档）
python scripts/quant_profile_ab_compare.py --start 2025-01-01 --end 2026-03-20

# 多组对比
python scripts/quant_profile_ab_compare.py --base-profile quality_regime --compare-profile quality_regime_candidate_v18_balanced_trap_guard --extra-profiles quality_regime_candidate_v23_nav_weighted_style_gate --start 2025-01-01 --end 2026-03-20
```
- 档位说明：
  - `quality_regime`: 当前默认档，只有 promotion gate 可改变默认状态
  - `quality_regime_candidate_v18_balanced_trap_guard`: cleaner execution-credibility shadow，未升档
  - `quality_regime_candidate_v23_nav_weighted_style_gate`: NAV-weighted style exposure 诊断档，未升档
  - `balanced*` / `aggressive`: 历史对照档，不能当作当前生产默认

候选档进入长窗前，先按“便宜证据 -> 执行烟测 -> 长窗”的顺序筛选，避免研究侧幸存者直接消耗 90/120 日 P2：

```bash
# 1) 候选 daily 覆盖不足时，先重建 profile-isolated daily；排除无下一交易日的尾端信号
python scripts/quant_rebuild_profile_daily_signals.py \
  --profiles quality_regime_candidate_v22_relaxed_low_volume_gate \
  --date-source daily-files --days 70 --replayable-only \
  --execution-mode inprocess --max-metadata-staleness-days 999

# 2) 创建 vNext shadow 前，先做 capacity-feasible alpha 诊断；
#    若没有任何 score 在容量/行业/reserve/exit-trap 约束后通过，不创建新候选
python scripts/quant_capacity_feasible_alpha_diagnosis.py \
  --profile quality_regime_candidate_v28_ranking_gate_relief \
  --stage auto --end 2026-04-14 --write-latest \
  --primary-promotion-modes keep,score_topn

# 3) score-alpha + daily 覆盖率 + target utilization 预检；
#    要求候选覆盖主档同一批 replayable signal dates，且 last-60 target_weight_mean >= 30%、zero-target <= 5%；
#    只写 precheck 工件，不跑 P2
python scripts/quant_refresh_promotion_gate.py \
  --profiles quality_regime,quality_regime_candidate_v22_relaxed_low_volume_gate \
  --end 2026-04-14 --refresh-score-alpha \
  --precheck-score-alpha --precheck-signal-coverage --precheck-only

# 4) 60 日 P2 fail-fast；若 NAV/MDD/仓位/阻塞弱于主档，直接跳过 90/120 和 promotion
python scripts/quant_refresh_promotion_gate.py \
  --profiles quality_regime,quality_regime_candidate_v22_relaxed_low_volume_gate \
  --end 2026-04-14 \
  --precheck-score-alpha --precheck-signal-coverage \
  --p2-windows 60,90,120 --fail-fast-p2-smoke-window 60 \
  --p2-execution-mode inprocess --max-metadata-staleness-days 999

# 5) 若需要手动复跑 60 日 P2 smoke 失败归因
python scripts/quant_p2_smoke_failure_diagnosis.py \
  --profiles quality_regime,quality_regime_candidate_v22_relaxed_low_volume_gate \
  --window 60 --write-latest

# 6) 若需要手动下钻最差相对日的订单/风控原因
python scripts/quant_p2_failure_day_attribution.py \
  --profiles quality_regime_candidate_v22_relaxed_low_volume_gate \
  --window 60 --worst-n 3 --write-latest

# 7) 若需要判断 holiday-gap guard 是保护还是错杀收益
python scripts/quant_p2_holiday_gap_guard_attribution.py \
  --profiles quality_regime_candidate_v22_relaxed_low_volume_gate \
  --windows 60 --write-latest

# 8) 若 capacity-feasible alpha 通过但 60 日 P2 smoke 失败，连接静态 alpha 和 P2 路径
python scripts/quant_static_to_p2_pass_through_diagnosis.py \
  --profile quality_regime_candidate_v29_capacity_feasible_alpha \
  --main-profile quality_regime --window 60 \
  --score-col target_blend_score --write-latest

# 9) 若要判断瓶颈是 raw 模型、pipeline 排名还是 P2 residual，合成决策表
python scripts/quant_raw_alpha_p2_residual_diagnosis.py \
  --profile quality_regime_candidate_v29_capacity_feasible_alpha \
  --main-profile quality_regime \
  --stage-label v29_raw_stage --write-latest

# 10) 若 raw ml_score 弱，进一步检查是整体失效、符号反向，还是和 open_to_open 持有期不匹配
python scripts/quant_raw_ml_horizon_diagnosis.py \
  --stage-glob 'output/research_stage_profiles/quality_regime_candidate_v29_capacity_feasible_alpha/research_stages_*.csv' \
  --profile quality_regime_candidate_v29_capacity_feasible_alpha \
  --stage raw_scored_post_indicator \
  --score-col ml_score \
  --horizons 1,3,5,8,10,15 \
  --top-n 20 --end 2026-04-14 --write-latest

# 11) 若确认 raw ml_score 弱，回到模型层训练 H=8/H=10 raw-universe walk-forward 对照
python scripts/quant_raw_model_walkforward_diagnosis.py \
  --horizons 8,10 --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 120000 \
  --num-boost-round 120 --early-stopping-rounds 20 \
  --label h8_h10_raw_walkforward --write-latest

# 12) 若 pooled 指标有线索但 fold pass rate 不足，专门解释失败 fold
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 6,7 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 100000 \
  --num-boost-round 120 --early-stopping-rounds 20 \
  --label h10_instability_focus --write-latest

# 13) 若要比较 regime-specific / drift-robust / objective-family 是否能全 7-fold 稳定
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 1,2,3,4,5,6,7 --critical-folds 7 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 100000 \
  --num-boost-round 120 --early-stopping-rounds 20 \
  --variants baseline,recency_weighted,lambdarank,regression_l1,huber,rank_normalized,cross_sectional_only,drop_high_drift,regime_specific,rank_norm_drop_high_drift,blend_rank_norm_huber \
  --label h10_model_family_7fold --write-latest

# 14) 若某个 model-family 只在部分随机 seed 中通过，改用确定性交易日分层抽样复核
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 1,2,3,4,5,6,7 --critical-folds 7 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 120000 --max-test-rows 0 \
  --sample-mode date_stratified \
  --num-boost-round 120 --early-stopping-rounds 20 \
  --variants baseline,rank_norm_drop_high_drift \
  --label h10_ranknorm_drop_drift_7fold_date_stratified --write-latest

# 15) 将多个 seed / sample-mode 的 variant_family_summary 汇总成硬 gate；
#     只有 sample_stability_pass 才能进入下一层 raw-model review，仍不能直接建 profile/P2
python scripts/quant_raw_model_seed_stability_report.py \
  --summary-files output/backtest/quant_raw_model_instability_attribution_latest_h10_ranknorm_family_7fold_variant_family_summary.csv,output/backtest/quant_raw_model_instability_attribution_latest_h10_ranknorm_family_7fold_seed2_variant_family_summary.csv,output/backtest/quant_raw_model_instability_attribution_latest_h10_ranknorm_drop_drift_7fold_seed3_variant_family_summary.csv,output/backtest/quant_raw_model_instability_attribution_latest_h10_ranknorm_drop_drift_7fold_date_stratified_variant_family_summary.csv \
  --variants baseline,rank_normalized,blend_rank_norm_huber,blend_rank_norm_l1,rank_norm_drop_high_drift \
  --label h10_ranknorm_seed_stability --write-latest

# 16) 若 critical fold 反复失败，把 fold metrics / regime / feature exposure / drifted importance 合成 failure matrix
python scripts/quant_raw_model_fold_failure_matrix.py \
  --artifact-prefixes output/backtest/quant_raw_model_instability_attribution_latest_h10_ranknorm_family_7fold,output/backtest/quant_raw_model_instability_attribution_latest_h10_ranknorm_family_7fold_seed2,output/backtest/quant_raw_model_instability_attribution_latest_h10_ranknorm_drop_drift_7fold_seed3,output/backtest/quant_raw_model_instability_attribution_latest_h10_ranknorm_drop_drift_7fold_date_stratified \
  --variants baseline,rank_normalized,blend_rank_norm_huber,blend_rank_norm_l1,rank_norm_drop_high_drift \
  --focus-fold 7 \
  --label h10_fold7_ranknorm_failure_matrix --write-latest

# 17) 若 ex-ante regime 能定位失败区，先做 fold7 regime-specific 探针；
#     只有绝对 top bucket、spread、RankIC 同时通过，才允许扩展到全 7-fold
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 7 --critical-folds 7 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 120000 --max-test-rows 0 \
  --sample-mode date_stratified \
  --num-boost-round 120 --early-stopping-rounds 20 \
  --seed 20260510 \
  --variants baseline,rank_normalized,regime_specific,rank_norm_regime_specific,rank_norm_drop_high_drift \
  --label h10_fold7_regime_specific_probe --write-latest

# 18) 若 regime-specific 接近通过但 absolute top 仍偏弱，测试逐日标签目标处理；
#     fold7 通过后仍必须跑全 7-fold，不能直接进入 capacity/P2
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 1,2,3,4,5,6,7 --critical-folds 7 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 120000 --max-test-rows 0 \
  --sample-mode date_stratified \
  --num-boost-round 120 --early-stopping-rounds 20 \
  --variants baseline,rank_normalized,rank_norm_label_ranked,rank_norm_regime_specific,rank_norm_regime_label_ranked \
  --label h10_label_objective_7fold_date_stratified --write-latest

# 19) 若 label-objective 能救 fold7 但全 7-fold 仍不稳，解释 residual folds；
#     默认拆 fold2/fold6，不训练模型、不建 profile、不跑 P2
python scripts/quant_raw_model_residual_fold_diagnosis.py \
  --artifact-prefix output/backtest/quant_raw_model_instability_attribution_latest_h10_label_objective_7fold_date_stratified \
  --variant rank_norm_regime_label_ranked \
  --baseline-variant baseline \
  --focus-folds 2,6 \
  --label h10_label_objective_fold2_fold6_residuals --write-latest

# 20) 将 residual fold 拆成不同 treatment hypothesis；
#     仍然只定义下一轮 raw-model 实验，不建 profile、不跑 P2
python scripts/quant_raw_model_residual_treatment_probe.py \
  --residual-summary output/backtest/quant_raw_model_residual_fold_diagnosis_latest_h10_label_objective_fold2_fold6_residuals_summary.csv \
  --label h10_label_objective_fold2_fold6_treatment_probe --write-latest

# 21) 实际跑 fold2 absolute-return calibration 与 fold6 pos_52w/beta 捕捉 treatment；
#     必须覆盖 full 7-fold，并把 2/6/7 作为 critical folds。失败则继续停在 raw-model 层
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 1,2,3,4,5,6,7 --critical-folds 2,6,7 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 120000 --max-test-rows 0 \
  --sample-mode date_stratified \
  --num-boost-round 120 --early-stopping-rounds 20 \
  --variants baseline,rank_norm_regime_label_ranked,abs_calibrated_rank_norm_regime_label_ranked,pos52w_beta_rank_norm_regime_label_ranked,abs_pos52w_beta_rank_norm_regime_label_ranked \
  --label h10_residual_treatments_7fold_date_stratified --write-latest

# 22) 更严格版本：fold2 用 signal-date day-level deployment veto；
#     fold6 用训练期 regime-aware conditional pos_52w/beta 捕捉，并报告部署覆盖率
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 1,2,3,4,5,6,7 --critical-folds 2,6,7 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 120000 --max-test-rows 0 \
  --sample-mode date_stratified \
  --num-boost-round 120 --early-stopping-rounds 20 \
  --variants baseline,rank_norm_regime_label_ranked,day_veto_rank_norm_regime_label_ranked,conditional_pos52w_beta_rank_norm_regime_label_ranked,day_veto_conditional_pos52w_beta_rank_norm_regime_label_ranked \
  --label h10_residual_strict_treatments_7fold_date_stratified --write-latest

# 23) 不再做粗 veto / 简单 overlay：fold2 用 signal-date day-state absolute calibration；
#     fold6 用 train-time day-state opportunity detector 判断 pos_52w/beta 是否应激活。
#     先跑 critical folds 2/6/7；若不全过，不回到 capacity/P2/profile
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 2,6,7 --critical-folds 2,6,7 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 120000 --max-test-rows 0 \
  --sample-mode date_stratified \
  --num-boost-round 120 --early-stopping-rounds 20 \
  --variants baseline,rank_norm_regime_label_ranked,day_calibrated_rank_norm_regime_label_ranked,day_opportunity_pos52w_beta_rank_norm_regime_label_ranked,day_calibrated_opportunity_rank_norm_regime_label_ranked \
  --label h10_day_state_calibration_opportunity_critical_folds_date_stratified --write-latest

# 24) 若 day-state 仍不够有辨识度，测试新原始特征、新标签目标和二阶段 positive-hit 模型；
#     必须跑 full 7-fold，并继续把 2/6/7 作为 critical folds。失败则仍禁止 capacity/P2/profile
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 1,2,3,4,5,6,7 --critical-folds 2,6,7 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 120000 --max-test-rows 0 \
  --sample-mode date_stratified \
  --num-boost-round 100 --early-stopping-rounds 20 \
  --variants baseline,rank_norm_regime_label_ranked,engineered_rank_norm_regime_label_positive_ranked,two_stage_hit_rank_norm_regime_label_ranked,engineered_two_stage_hit_rank_norm_regime_label_positive_ranked \
  --label h10_engineered_positive_two_stage_7fold_date_stratified --write-latest

# 25) 若 engineered two-stage 仍未过 critical folds，测试 market-context feature family；
#     context features 使用信号日 OHLCV、市场宽度、相对市场表现和 trailing market stress。
#     若只救回 fold6/fold7 而 fold2 仍为负，仍不得回到 capacity/P2/profile
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 1,2,3,4,5,6,7 --critical-folds 2,6,7 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 120000 --max-test-rows 0 \
  --sample-mode date_stratified \
  --num-boost-round 100 --early-stopping-rounds 20 \
  --variants baseline,rank_norm_regime_label_ranked,context_rank_norm_regime_label_ranked,context_rank_norm_regime_label_tail_ranked,context_two_stage_hit_rank_norm_regime_label_tail_ranked \
  --label h10_context_tail_two_stage_7fold_date_stratified --write-latest

# 26) 修复 ex-ante regime 字段清洗口径后，重跑 context + downside-aware weighting；
#     downside variants 只改变训练样本权重，不降低部署覆盖率、不进 capacity/P2/profile
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 1,2,3,4,5,6,7 --critical-folds 2,6,7 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 120000 --max-test-rows 0 \
  --sample-mode date_stratified \
  --num-boost-round 100 --early-stopping-rounds 20 \
  --variants baseline,rank_norm_regime_label_ranked,context_rank_norm_regime_label_ranked,downside_context_rank_norm_regime_label_ranked,downside_context_rank_norm_regime_label_tail_ranked \
  --label h10_downside_context_7fold_date_stratified --write-latest

# 27) 如果 downside context 仍只救 fold6/fold7，测试 richer context day-state calibration；
#     这仍然只做 raw-model attribution，不能用来创建 profile 或跑 P2
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 1,2,3,4,5,6,7 --critical-folds 2,6,7 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 120000 --max-test-rows 0 \
  --sample-mode date_stratified \
  --num-boost-round 100 --early-stopping-rounds 20 \
  --variants baseline,context_rank_norm_regime_label_ranked,downside_context_rank_norm_regime_label_ranked,day_calibrated_context_rank_norm_regime_label_ranked,day_calibrated_downside_context_rank_norm_regime_label_ranked \
  --label h10_context_day_calibration_7fold_date_stratified --write-latest

# 28) 如果 defensive day-state 仍不能转正 fold2，测试 weak-positive 训练目标；
#     该目标在训练弱日只强奖励正收益股票，并可叠加 positive-hit 二阶段 head。
#     通过标准仍是 full 7-fold + critical folds 2/6/7，不得因 5/7 好看进入 P2
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 1,2,3,4,5,6,7 --critical-folds 2,6,7 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 120000 --max-test-rows 0 \
  --sample-mode date_stratified \
  --num-boost-round 100 --early-stopping-rounds 20 \
  --variants baseline,context_rank_norm_regime_label_ranked,context_rank_norm_regime_label_weak_positive_ranked,downside_context_rank_norm_regime_label_weak_positive_ranked,context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked,day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked \
  --label h10_weak_positive_context_7fold_date_stratified --write-latest

# 29) 如果 weak-positive 已救回 fold6/fold7 但 fold2 仍负，测试 abstention/deployability head；
#     先跑 fold2-only probe，只有 fold2 top bucket 转正且部署率不低于地板，才考虑 full 7-fold
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 2 --critical-folds 2 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 60000 --max-test-rows 0 \
  --sample-mode date_stratified \
  --num-boost-round 80 --early-stopping-rounds 15 \
  --variants baseline,context_rank_norm_regime_label_weak_positive_ranked,validated_abstain_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked,hit_abstain_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked \
  --label h10_hit_abstention_fold2_probe --write-latest

# 30) 如果 abstention 预期失准，测试更严格的绝对正收益标签；
#     仍先跑 fold2-only，若 strict/margin positive 仍不能转正，就不要扩展到 full 7-fold
python scripts/quant_raw_model_instability_attribution.py \
  --horizon 10 --focus-folds 2 --critical-folds 2 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --top-n 30 --max-train-rows 60000 --max-test-rows 0 \
  --sample-mode date_stratified \
  --num-boost-round 80 --early-stopping-rounds 15 \
  --variants baseline,context_rank_norm_regime_label_weak_positive_ranked,context_rank_norm_regime_label_strict_positive_ranked,context_rank_norm_regime_label_margin_positive_ranked,context_two_stage_hit_rank_norm_regime_label_strict_positive_ranked,context_two_stage_hit_rank_norm_regime_label_margin_positive_ranked \
  --label h10_strict_positive_fold2_probe --write-latest
```

`quant_capacity_feasible_alpha_diagnosis.py` 是 vNext 建档前的前置证据，只能说明“约束内是否值得构造 shadow 假设”，不能作为 promotion pass。它会同时输出 `selection_loss_pct`、`top_selected_overlap_rate_pct`、`top_dropped_*`、`selected_replacement_*` 和 `selection_loss_label`，用于判断是 ADV/行业/reserve/exit-trap 约束替换了正向 top bucket，还是 score 本身在约束内已经失效。`--primary-promotion-modes keep,score_topn` 只做诊断：`score_topn` 会临时把某个 score 的 topN 标为 primary，验证正向 top 名单是否被 reserve cap 换成弱样本；若它通过，也只允许创建 shadow 档，并必须再重建 profile daily 和跑 P2 smoke。`--precheck-signal-coverage` 不只检查数量，还会检查候选是否覆盖主档参考日历里的同一批 replayable signal dates；reference calendar 只使用同时存在 shared daily 和主数据行情的日期，旧 daily 文件若没有对应 market bars 会被当作 stale/orphan signal 排除。候选缺主档日期时会记录 `profile_signal_calendar_mismatch`，避免用向前补天数的候选窗口和主档窗口硬比。该参数还会同步生成 `quant_target_utilization_precheck_latest.json/csv`，记录 `target_weight_sum_mean_60`、`target_weight_sum_p10_60`、`zero_target_days_60`、`zero_target_rate_pct_60`；候选 last-60 mean 低于 30% 或 zero-target rate 高于 5% 时，在 P2 前跳过，除非主档同口径同样更差。各 precheck 都会对原始 requested profiles 写证据，最终 P2 只跑通过所有前置 gate 的交集。`--fail-fast-p2-smoke-window 60` 会生成 `output/backtest/quant_p2_smoke_precheck_latest.json/csv`。若候选被烟测跳过，refresh 会自动调用 `quant_p2_smoke_failure_diagnosis.py` 连接 score-alpha、P2 precheck 和逐日 ledger，判断是 sell trap、cash drag、calendar mismatch，还是 score-alpha 没有执行穿透，并继续调用 `quant_p2_failure_day_attribution.py` 下钻最差相对日的 orders / risk gates，同时调用 `quant_p2_holiday_gap_guard_attribution.py` 判断 holiday-gap guard 触发日是否真实保护了组合，或只是降低仓位造成 missed upside；若该候选已有 capacity-feasible daily latest，refresh 还会自动调用 `quant_static_to_p2_pass_through_diagnosis.py` 检查静态正 alpha 是否穿透到 P2 相对收益。holiday attribution 的 downside/MDD 字段是归因代理，不是完整反事实回放；它只用于解释 guard 效果，不直接决定升档。手动命令只用于重跑或排障。这个烟测只是节省计算与防止错跑长窗，不是升档依据；真正升档仍必须通过 60/90/120 P2、shadow diagnosis、funnel 和 `quant_profile_promotion_review.py`。

`quant_static_to_p2_pass_through_diagnosis.py` 是 v29 之后新增的失败解释层：当 capacity-feasible alpha、score-alpha、coverage、target utilization 都通过，但 P2 smoke 仍输给主档时，用它把静态 selected forward return 与同窗 P2 daily return 对齐。它会输出静态正收益日、静态正收益但 P2 跑输日、cash-drag proxy、holiday guard、exit block、blocked-sell weight 和 `pass_through_label`，结论只用于决定下一轮研究问题，不允许直接触发 promotion。

`quant_raw_alpha_p2_residual_diagnosis.py` 是更上层的决策表：它不重新计算 heavy stage snapshots，而是消费 `quant_stage_transition_diagnosis.py` 的 `score_stage_summary` / `transition_summary` 和 `quant_static_to_p2_pass_through_diagnosis.py` 的 summary，合成 raw ML alpha、raw component alpha、final target 静态 alpha、P2 pass-through residual 和 damaging transition。它的 verdict 用来决定下一轮该回到 raw model/label、修 ranking pipeline，还是继续做执行路径 residual 诊断；不能作为 promotion pass。

`quant_raw_ml_horizon_diagnosis.py` 是 raw 模型审查层：它不改 profile，不跑 P2，只在全市场 `raw_scored_post_indicator` stage 上用同一个 `ml_score` 计算多组 open-to-open forward return，并同时评估正常 score direction 与反向 direction。verdict 会写出模型 `label_horizon`、profile `holding_days` 和 `model_profile_horizon_mismatch`。如果正常方向所有 horizon 都失败，即使存在模型/profile horizon mismatch，也不能把失败简单归因于持有期错配；下一步应审查训练标签、预测符号、样本切分和特征稳定性。

`quant_raw_model_walkforward_diagnosis.py` 是模型层重诊断：它重新构造 H=8/H=10 open-to-open 标签，并在 raw universe 上按滚动窗口训练诊断模型，只输出证据，不保存 production model。它同时输出 label sample、fold summary、horizon summary、feature drift 和 verdict。通过标准不是 pooled 指标单独好看，而是 pooled top bucket、top-minus-all、top-minus-bottom、RankIC 和 fold pass rate 同时达标；默认不写全量 OOS predictions，避免生成巨型 artifact。默认启用 `--feature-cache-file auto`，把 raw feature frame 缓存到 `output/cache/raw_model_frames/`；缓存 metadata 绑定数据文件 mtime/size、feature list、horizon、日期范围和 BJ/9-code 过滤口径，不能作为 promotion 证据，只用于降低重复诊断成本。

`quant_raw_model_instability_attribution.py` 是 walk-forward 失败后的解释层：它可以重跑指定失败 fold，也可以跑全 7-fold model-family 对照。变体包括 baseline、recency-weighted、lambdarank、L1/Huber objective、rank-normalized、cross-sectional-only、high-drift-feature-drop、ex-ante regime-specific、逐日标签去均值/排序目标、`rank_norm_*` 组合变体、rank-normalized ensemble，以及 residual treatment variants。当前 residual treatment 覆盖 `abs_calibrated_*`、`pos52w_beta_*`、`day_veto_*`、`conditional_pos52w_beta_*`、`day_calibrated_*`、`day_opportunity_pos52w_beta_*`、diagnosis-only engineered raw features、market-context features、positive daily-ranked / tail-positive ranked labels、two-stage positive-hit blend、`downside_*` 弱日样本加权、context/downside-context 的 day-state calibration、`weak_positive_daily_ranked` 弱市正收益目标，`strict_positive_daily_ranked` / `margin_positive_daily_ranked` 绝对正收益标签，以及 `abstain_*` / `validated_abstain_*` / `hit_abstain_*` deployability head。day-state treatment 使用 signal-date kNN：`day_calibrated_*` 用训练期相似日的全市场 forward return 估计弱日风险，并在弱日内偏向低 beta/低波动候选而不是直接 veto；`validated_abstain_*` 用验证窗校准 deployability 阈值；`hit_abstain_*` 用二阶段 positive-hit 概率的逐日 top 候选强度判断是否部署。engineered variants 只用信号日已有指标的确定性组合，如 momentum/relative-strength 差分、pos_52w 交互、volume stress 与 risk-adjusted momentum；context variants 进一步加入信号日 OHLCV 形态、gap/intraday/range、成交 log、相对市场收益、market-stress 交互；downside variants 不改变标签和部署覆盖率，只在训练时提高弱日幸存赢家与严重亏损样本的权重；weak-positive label 在训练弱日把负收益股票压到很低标签，只强奖励正收益股票；strict/margin positive label 则在所有训练日强制区分绝对正收益和负收益。输出会拆成 variant summary、variant family summary、regime summary、ex-ante regime summary、deployment/treatment activation、positive-hit probability、deployability expectation、feature drift / importance、top-bucket exposure 和 fold attribution；`--sample-mode date_stratified` 用于确定性交易日分层抽样，避免把随机训练样本差异误读成模型修复；默认共用 raw feature-frame cache。

`quant_raw_model_seed_stability_report.py` 是 raw model 进入下一层前的 hard gate。它不重训模型，只消费多次 `variant_family_summary`，检查每个 variant 是否跨 seed / sample-mode 都通过 `variant_model_gate_pass`、critical fold、fold pass-rate 和 pooled alpha 下限。最新 `h10_ranknorm_seed_stability` 汇总显示没有任何 variant 通过：`rank_norm_drop_high_drift` 只有 `2/4` 个运行通过，最差 fold7 top bucket 约 `-0.87%`；`blend_rank_norm_huber` 和 `blend_rank_norm_l1` 都在 seed2 的 critical fold 转负。因此当前仍禁止 profile/P2。

`quant_raw_model_fold_failure_matrix.py` 是 critical fold 失败解释层。它同样不重训模型，而是消费多次 instability attribution 的 `variant_summary`、`regime_summary`、`selected_feature_exposure` 和 `feature_importance_drift`。最新 fold7 matrix 显示：baseline 是 `absolute_failure_with_drifted_exposure`，负 top bucket 和负 spread 同时存在；rank-normalized / rank_norm_drop_high_drift 是 `absolute_failure_regime_sensitive`，多种 regime 内反复失败；rank-normalized ensemble 主要是 `absolute_top_bucket_failure`，即相对 spread 偶尔为正，但 top bucket 仍可能为负。这个报告用于决定下一轮模型研究问题，不能作为 profile/P2 放行证据。

`quant_raw_model_residual_fold_diagnosis.py` 是 label-objective 之后的残差解释层。最新 `h10_label_objective_fold2_fold6_residuals` 显示：fold2 属于 `absolute_loss_but_beats_pool`，`rank_norm_regime_label_ranked` top bucket 约 `-0.95%`，但跑赢全池约 `+0.96pct`，主要失败在 signal-date `neutral` / `risk_on`；这不是 alpha pass，只是弱市相对防守。fold6 属于 `positive_top_but_pool_and_bottom_lag`，top bucket 约 `+1.09%`，但跑输全池约 `-0.24pct`、跑输 bottom 约 `-0.83pct`，并伴随 `pos_52w` 漂移重要特征。这说明后续模型不能用单一“rank-normalized + daily-ranked label”补丁解决所有窗口，必须分别处理弱市绝对收益和强/中性市 beta 捕捉不足。

`quant_raw_model_residual_treatment_probe.py` 是 residual diagnosis 后的实验边界层。它把 fold2 标记为 `weak_market_absolute_return_calibration`：当前模型有相对防守但 top bucket 仍为负，下一轮必须测试 signal-date 可知的绝对收益校准或弱市部署 veto，并要求 fold2/弱窗口 top bucket 转正。它把 fold6 标记为 `beta_capture_pos52w_drift_repair`：当前 top bucket 为正但跑输全池和 bottom bucket，且 `pos_52w` 是漂移重要特征，下一轮应测试 `pos_52w` rank/winsor/分 regime 校准、beta/机会捕捉 head，并要求 neutral/broad-up 下 top-minus-all 与 top-minus-bottom 不再为负。该脚本只输出 hypothesis/report，不训练模型、不创建 profile、不进入 P2。

最新 `h10_residual_treatments_7fold_date_stratified` 已经把 treatment 真正放进 full 7-fold raw-universe gate。结论仍是失败：`rank_norm_regime_label_ranked` 通过 `2/7` folds，critical folds `2/6/7` 未全过；`abs_calibrated_rank_norm_regime_label_ranked` 也只过 `2/7`，且 fold2 top bucket 从约 `-0.79%` 恶化到约 `-2.27%`；`pos52w_beta_rank_norm_regime_label_ranked` 把 fold6 的 top-minus-all 从约 `-0.675pct` 改到约 `-0.090pct`，但仍未转正，并把 fold7 top bucket 打到约 `-0.29%`；组合 treatment 虽让 fold7 通过，但 fold2/fold6 仍失败。该结果明确禁止回到 capacity/P2，下一步应研究更严格的弱市 day-level absolute-return calibrator，以及不会破坏 fold7 的 conditional pos_52w/beta 捕捉。

最新 `h10_residual_strict_treatments_7fold_date_stratified` 对上述方向做了更严格复核，仍失败。`day_veto_rank_norm_regime_label_ranked` 的均值看起来更好，但 mean deployment day rate 只有约 `54.7%`，最低 fold 只有约 `18.3%`，fold2/fold6 都因 `deployment_day_rate_below_floor` 失败；它更像风险关闭而不是可部署 alpha。`conditional_pos52w_beta_rank_norm_regime_label_ranked` 在训练期没有找到可放行的 pos_52w/beta regime，实际没有解决 fold6，fold6 top-minus-all 反而约 `-0.968pct`。组合 variant 同样失败，fold6 仍跑输全池约 `-0.411pct`，fold7 top bucket 又转负约 `-0.231%`。因此 raw-model 层仍不能放行 capacity/P2/profile。

最新 `h10_day_state_calibration_opportunity_critical_folds_date_stratified` 进一步测试了更细的 signal-date day-state 版本，仍没有放行。`day_calibrated_rank_norm_regime_label_ranked` 不再直接降低部署率，fold2 激活约 `72.6%` 交易日，但 top bucket 从 base 的约 `-0.79%` 恶化到约 `-1.49%`；fold6 top 改到约 `+0.95%`，但 top-minus-all 仍约 `-0.382pct`、top-minus-bottom 仍为负；fold7 被打到约 `-0.057%`。`day_opportunity_pos52w_beta_rank_norm_regime_label_ranked` 在 fold6 的 train-time day-state opportunity edge 为负，激活率 `0%`，说明训练期相似日不支持 pos_52w/beta 机会窗口；它在 fold7 激活约 `97.5%` 并仍通过，但不能解决 fold2/fold6。组合 variant 也只通过 fold7，critical folds 仍失败。该证据说明当前 day-state features 还不足以形成可部署校准或机会 detector；下一步应研究新原始特征/标签目标或更强的二阶段模型，而不是建 profile。

最新 `h10_engineered_positive_two_stage_7fold_date_stratified` 已经把新原始特征、positive daily-ranked label 和 two-stage positive-hit blend 放进 full 7-fold raw-universe gate。结果仍不允许回到 capacity/P2：最佳 `engineered_two_stage_hit_rank_norm_regime_label_positive_ranked` 只通过 `2/7` folds，critical folds `2/6/7` 未全过；fold2 仍是 absolute top-bucket failure，top 约 `-1.80%`；fold6 top 约 `+1.17%` 但仍跑输全池约 `-0.16pct` 且跑输 bottom；fold7 top 约 `-0.002%`，只接近零而未转正。它相对 base 改善了 fold4/fold5 和部分 fold6 spread，但不是稳定 alpha。当前 raw-model 结论保持：不能建新 profile、不能跑 P2；下一步应从“特征族和标签目标设计”继续，而不是把局部改善推到执行层。

最新 `h10_context_tail_two_stage_7fold_date_stratified` 说明 market-context feature family 是目前最有用的 raw-model 方向，但仍未放行。`context_rank_norm_regime_label_ranked` 通过 `3/7` folds，明显优于 base 和 engineered two-stage；它把 fold6 修到 top 约 `+1.75%`、top-minus-all 约 `+0.42pct`，也把 fold7 修到 top 约 `+0.47%`、top-minus-all 约 `+0.85pct`。但 fold2 仍失败，top 约 `-1.72%`，只是跑赢全池约 `+0.19pct`。tail-positive label 和 context two-stage 没有解决 fold2，还会打坏 fold7 或 fold6 spread。因此当前问题已进一步收敛：fold6/fold7 可由 signal-date market-context 特征部分修复，真正卡口变成 fold2 的弱市绝对收益为负。下一步仍只能在 raw-model 层做 fold2-specific absolute-return objective / downside-aware model，不得建 profile 或跑 P2。

最新 `h10_downside_context_7fold_date_stratified` 修复了 ex-ante regime 字段清洗口径，并加入 `downside_context_*` 样本权重实验。修复后 regime-specific 训练不再退化成全 neutral，证据也更严格：`downside_context_rank_norm_regime_label_ranked` 能同时通过 fold6（top 约 `+1.35%`、top-minus-all 约 `+0.01pct`）和 fold7（top 约 `+0.35%`、top-minus-all 约 `+0.73pct`），但 fold2 仍为负 top bucket（约 `-1.85%`）；`downside_context_rank_norm_regime_label_tail_ranked` 通过 `3/7` folds，是本轮 family best，但 critical folds 仍未全过，fold2 约 `-2.24%`。因此 downside weighting 不是可部署修复，只证明 fold6/fold7 可被 context + weighting 稳住，fold2 weak-window absolute-return problem 仍是唯一硬卡口。

最新 `h10_context_day_calibration_7fold_date_stratified` 把 day-state calibration 接到 context/downside-context 线，并让 day-state 使用 gap、intraday、range、成交 log、相对市场收益和 market-stress 等 signal-date 特征。结论仍是不放行：`day_calibrated_context_rank_norm_regime_label_ranked` 是本轮 best，过 `3/7` folds，fold6/fold7 都通过，fold2 从 context 的约 `-2.54%` 改善到约 `-1.66%`，但仍是负 top bucket；downside + day calibration 还会打坏 fold6 spread。这个结果说明 richer day-state 防守倾斜能改善 fold2 但无法转正，下一步不能再靠弱日防守 overlay，应考虑新的 fold2 day-level target 或二阶段 deployability/ranking 模型。

最新 `h10_weak_positive_context_7fold_date_stratified` 是目前最接近的 raw-model 线，但仍不允许回到 capacity/P2。`day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked` 通过 `5/7` folds，fold pass rate 约 `71.4%`，fold6 top 约 `+1.37%`、top-minus-all 约 `+0.04pct`，fold7 top 约 `+0.75%`、top-minus-all 约 `+1.13pct`；但 critical fold pass 仍为 false，因为 fold2 仍是负 top bucket，约 `-1.88%`。本轮 fold2 最好的是 `downside_context_rank_norm_regime_label_weak_positive_ranked`，约 `-1.54%`，仍未转正。结论：weak-positive target 和 positive-hit head 是真实的模型层进展，但 fold2 绝对收益硬门槛未过，不能建 profile、不能跑 P2。

最新 fold2-only deployability probe 进一步否定了简单 abstention 方向。`h10_validated_abstention_fold2_probe` 中，验证窗校准的 day-state abstention 把部署日降到 `40/84`、约 `47.6%`，但 top bucket 仍约 `-1.60%`，且低于部署率地板。`h10_hit_abstention_fold2_probe` 中，stock-level positive-hit deployability head 的验证窗阈值没有触发弃权，`84/84` 天全部部署，top bucket 约 `-2.75%`。这说明 fold2 不是靠粗弃权头或验证窗乐观阈值能修复；当前 day-state / hit-prob deployability 预期在 fold2 测试窗失准。下一步仍停留在 raw-model 层，应研究更强的弱市标签/损失函数、样本状态切分或 fold2 专用特征，而不是回到 capacity/P2/profile。

最新 `h10_strict_positive_fold2_probe` 进一步否定了“只把标签改得更绝对正收益化”这一简单方向。`context_rank_norm_regime_label_margin_positive_ranked` 是本轮最好 strict/margin variant，但 fold2 top bucket 仍约 `-2.09%`，比 baseline `-1.92%` 更差；`strict_positive` 约 `-2.18%`，two-stage strict/margin 分别约 `-2.39%/-2.85%`。因此 fold2 不是靠单纯加大正收益标签奖惩能解决；下一步需要解释 fold2 测试窗相对训练/验证窗的状态迁移，或引入更能识别弱市机会窗口的新特征/模型结构。

`quant_raw_model_state_migration_diagnosis.py` 用于 fold2 这类弱窗的 fit/valid/test 状态迁移诊断。它不训练 production model、不建 profile、不进入 P2，只复用 raw feature-frame cache 与 walk-forward fold 切分，比较 signal-date day-state 分布、KNN deployability 预期、ex-ante regime 收益迁移和漂移特征。标准命令如下：

```bash
python scripts/quant_raw_model_state_migration_diagnosis.py \
  --horizon 10 --folds 2 \
  --start 2022-01-01 --end 2026-04-14 \
  --train-months 24 --test-months 4 --step-months 4 \
  --valid-months 3 --neighbor-days 20 \
  --label h10_fold2_state_migration --write-latest
```

最新 `h10_fold2_state_migration` verdict 是 `state_distribution_shift`，不是简单的 `optimistic_deployability_miscalibration`。test expected return mean 约 `-1.26%`，actual 约 `-1.91%`，expected deploy rate 仅约 `29.8%`，说明当前 day-state 头并不是过度部署；真正异常在 test state drift，max PSI 约 `6.51`，漂移集中在 `market_vol_20d`、`volatility_ratio_day_std`、`amount_day_mean/std`、`pos_52w_day_mean`、`pv_corr_20_day_mean` 等信号日状态特征。test 中 `risk_on` / `neutral` day mean return 分别约 `-6.10%` / `-2.85%`，而 valid 期 `risk_off` day mean return 约 `+9.80%`，说明验证窗不是 fold2 测试窗的好代理。下一步应优先做状态迁移鲁棒的弱市特征/样本切分/模型结构，而不是继续收紧正收益标签、粗 abstention，或回到 capacity/P2/profile。

最新 `h10_fold2_state_robust_probe` 和 `h10_fold2_state_weak_target_probe` 已把状态迁移鲁棒处理放进 fold2-only 诊断。新增 `state_weighted_*` 使用测试窗 signal-date 状态给相似训练日更高权重，`matched_state_*` 只保留与测试窗状态更相近的训练日，`state_weak_positive_daily_ranked` 则用信号日弱状态而不是未来 day mean 触发弱市正收益目标。结论仍是不放行：`matched_state_context_rank_norm_regime_label_weak_positive_ranked` 是最好结果，keep 45% 时 fold2 top 约 `-1.54%`、top-minus-all 约 `+0.37pct`，但绝对 top bucket 仍为负；keep 25% 约 `-1.93%`，keep 65% 约 `-2.84%`；`state_weighted_*` 和 `state_weak_positive_daily_ranked` 均更差。这个结果说明“找相似历史状态”有一点相对防守价值，但当前状态特征/目标设计里没有足够的弱市绝对 alpha，仍不能建 profile、不能跑 P2。

从 `h10_fold7_exante_regime_probe` 起，instability attribution 同时输出 `exante_regime_summary`。它使用信号日可知的 `market_regime_exante`，不是按未来收益事后分层。最新 fold7 ex-ante probe 显示：rank-normalized 线在 `neutral` regime 下仍是负 top bucket，`risk_on/risk_off` top bucket 为正但 RankIC 方向不稳定；baseline 在 `risk_on` 下严重反向。后续 `h10_fold7_regime_specific_probe` 说明 regime-conditioned modeling 能把 fold7 从灾难性反向拉回接近零，但还没有让 absolute top bucket 转正。这说明 fold7 不是只能事后解释，已有部分可事前识别的 regime 条件，但它还不是可交易规则，下一步只能用于 raw-model objective/feature treatment 设计。

holiday-gap guard 支持按触发原因覆盖 cap：profile 可设置 `holiday_gap_reason_overrides`，键为 `signal_to_trade_gap`、`post_trade_gap` 或 `signal_to_trade_gap+post_trade_gap`，值可包含 `total_position_cap` / `single_pos_cap`。这只应用于 shadow/诊断档；不要直接修改默认档，也不要因为单一窗口的 cash-drag 改善就关闭整体 holiday 风控。

当前条件化 guard 实验档 `quality_regime_candidate_v24_conditional_holiday_gap_guard` 已证明一条重要负结果：它能干净生成 profile-isolated daily 并通过 signal coverage，但 final `target_weight` / `portfolio_rank_score` score-alpha gate 失败，因此不应继续消耗 60/90/120 P2 长窗。下一步应诊断 stage-to-target alpha decay，而不是继续调 holiday cap。

当需要拆解 score-alpha 失败来自哪一层时，先打开 research stage snapshots 重建对应 profile daily，再跑：

```bash
MFTS_WRITE_RESEARCH_STAGE_SNAPSHOTS=true python scripts/quant_rebuild_profile_daily_signals.py \
  --profiles quality_regime_candidate_v24_conditional_holiday_gap_guard \
  --end 2026-04-14 --days 70 --replayable-only \
  --max-metadata-staleness-days 999 --force --execution-mode inprocess

python scripts/quant_stage_transition_diagnosis.py \
  --stage-glob 'output/research_stage_profiles/quality_regime_candidate_v24_conditional_holiday_gap_guard/research_stages_*.csv' \
  --label v24_stage_transition --end 2026-04-14 \
  --forward-days 10 --top-n 5 --write-latest
```

v24 的最新 stage-transition 结论是：`filtered_signal_pool -> ranking_pool_pre_pretrade` 保留下来的候选 forward return 均值为负，而被丢弃候选为正；最终池内 `liquidity_score` 与 `exit_trap_safe_score` 有正向 spread，但 `portfolio_rank_score` / `target_weight` 没有稳定通过。这说明下一步应修 final ranking / target-score 口径，而不是再调 holiday-gap cap。

v25/v26/v27 是这个方向的负结果边界：`quality_regime_candidate_v25_liquidity_target_score` 使用 `liquidity_score` 做最终 target score，score-alpha 相对通过但 60 日 P2 主要靠低仓少亏，target-weight mean 只有约 `14.7%`；`quality_regime_candidate_v26_liquidity_nav_style` 加入 NAV-weighted style exposure 后能消除 style halt，但更真实地暴露亏损。修复 capacity-aware optimizer 的无约束 fallback 后，v26 出现 `13/70` 个 zero-target days、last-60 target-weight mean 约 `26.9%`，并被加硬后的 score-alpha gate 拒绝。v27 进一步测试 primary/reserve isolation：`target_score_col=portfolio_rank_score`、`target_max_reserve_weight=0.02`，70 个 replayable daily 重建无失败，coverage 通过，last-60 target-weight mean 约 `35.27%`、zero-target `0%`，但 ungrouped score-alpha 失败：`target_weight` top bucket forward return 约 `-0.563%`，`portfolio_rank_score` 约 `-0.942%`，因此停止在 cheap precheck，不跑 60/90/120 P2。当前结论：不要对 v25/v26/v27 跑 90/120；后续 target-score 实验必须同时满足正的 top-bucket forward return、仓位利用率和 P2 NAV/MDD parity。

v27 的 stage-transition 诊断生成 `quant_stage_transition_diagnosis_latest_v27_stage_transition_alpha_decay_summary.csv`，总体 verdict 为 `ranking_alpha_decay_before_p2`：`filtered_signal_pool -> ranking_pool_pre_pretrade` 是主要损耗点，被丢弃股票均值比保留股票高约 `1.09pct`，而 late-stage 里 `liquidity_score` 与 `exit_trap_safe_score` 仍有局部正 spread。为验证这个单一假设，系统新增了两个 shadow-only 配置能力：`score_quantile_normal/choppy/panic` 可覆盖 ranking quantile gate，`target_score_blend` 可生成 `target_blend_score`。v28 `quality_regime_candidate_v28_ranking_gate_relief` 使用更宽松的 quantile gate 和 liquidity/exit-trap target blend，但 cheap precheck 失败：score-alpha gate 为 `no_gate_score_passed`，last-60 target-weight mean 约 `21.27%`，zero-target rate `35%`。随后 capacity-feasible 诊断发现 v28 的正向 component 名单主要被困在 reserve 标签后，`score_topn` 诊断能通过。为验证这一个狭窄假设，v29 `quality_regime_candidate_v29_capacity_feasible_alpha` 增加 `capacity_safe_primary_rank_mode=target_score_topn`，按 `target_blend_score` 生成 primary/reserve 标签；它通过 score-alpha、coverage、target utilization 和 capacity-feasible 诊断，但 60 日 P2 smoke 失败：主档 NAV/MDD 约 `+4.73%/-5.84%`，v29 约 `+0.10%/-7.54%`，且 exit-not-tradable orders `5` 多于主档 `3`。静态到 P2 穿透诊断显示 `target_blend_score` 同窗 `60` 日里只有 `24` 天静态 selected forward return 为正，其中 `15` 天在 P2 相对主档跑输，relative gap 合计约 `-4.59pct`，verdict 为 `static_alpha_not_p2_passed`。v29 raw-alpha/P2-residual 决策表显示 raw `ml_score` 全市场 top bucket 约 `-2.35%`、RankIC 约 `-0.057`，raw 层没有通过任一主 score；final `portfolio_rank_score` / `target_weight` 静态通过，但 P2 pass-through 失败，overall verdict 为 `final_static_alpha_not_p2_executed_raw_alpha_weak`。进一步的 raw ML horizon 诊断显示最新模型是 `open_to_open`、`label_horizon=3`，而 `quality_regime` 是 `holding_days=8`、v29 是 `holding_days=10`，确实存在模型/profile horizon mismatch；但正常方向的 `ml_score` 在 1/3/5/8/10/15 日 open-to-open horizon 均未通过，H=3 top bucket 约 `-0.51%`，H=8 top bucket 约 `-2.18%`，反向 score 只有 H=1 弱通过。H=8/H=10 raw-universe walk-forward 对照进一步显示：H=10 pooled 指标有线索，top bucket 约 `+1.38%`、top-minus-all 约 `+0.33pct`、RankIC 约 `0.054`，但 7 个 fold 只有 3 个通过，fold pass rate 约 `42.9%`，整体 verdict 仍为 `raw_walkforward_alpha_failed`；H=8 pooled top bucket 约 `+0.73%`，但低于全市场均值约 `+0.84%`。当前结论：primary relabel 修复了研究口径，但 alpha 仍没有执行穿透；raw ML 问题不能只解释为持有期错配，H=10 有弱线索但 split 稳定性不足，必须继续审查特征漂移、训练样本权重、市场 regime 分层和模型家族；不要跑 v29 的 90/120 或 promotion。

capacity-aware daily 不允许在 optimizer 选不出组合时退回无约束 score weights。空 daily / zero target 是 no-entry 或 capacity shortfall evidence，应进入 coverage、P2 和 promotion 口径；不能用 `optimizer_fallback` 小权重摊满候选池来制造仓位。

`quant_score_alpha_diagnosis.py --group-col ...` 只能作为子样本研究线索。某个 reserve / constraint / holiday 子组通过，不能等同于 profile 级 score-alpha gate 通过；脚本会把 grouped run 标记为 `grouped_diagnostic_not_profile_gate`，防止把局部亮点误当成 promotion 证据。

### 4. 单独 MFTS 选股
```bash
python core/mfts_screener.py
```
- 功能: 运行 MFTS 规则策略选股
- 输出: `output/scan/mfts_scan_YYYYMMDD.csv`（兼容旧路径 `output/mfts_scan_YYYYMMDD.csv`）
- 指定日期复盘:
```bash
python core/mfts_screener.py --date 20260320
```
- 说明: 策略已加入“大盘环境过滤”，系统性恐慌日会自动收紧 L1 触发。

### 5. 单独 ML 预测
```bash
python scripts/daily_ml_select.py
```
- 功能: 使用 LightGBM 模型预测
- 模型: `models/mfts_lgbm_*.pkl`
- 输出: `output/daily/daily_YYYYMMDD.csv`（兼容旧路径 `output/daily_YYYYMMDD.csv`）
- 风控输出: `output/risk/signal_pretrade_gates_YYYYMMDD.csv`（信号端前置风控拦截明细）
- 风控汇总: `output/risk/signal_pretrade_summary_YYYYMMDD.json`（前置风控阶段统计 + gate_trade_date）
- 同层复核: 汇总内含 `topn_pretrade_eval`（对最终出榜 TopN 复跑同口径风控，便于和 P2 逐日对齐）
- 新增列: `市场状态`、`建议仓位`、`单票上限`（正常/震荡/恐慌三挡）
- 说明: 推理阶段已加入两层过滤：
- 第一层：可交易性过滤（涨停触发/过热/量能异常）
- 第二层：信号端前置风控（复用 `core/risk/pretrade.py`，参数读取 `MFTS_RISK_*`，与 P2 口径对齐）
- 若前置风控过滤后不足 TopN，默认进入 fallback 并告警（可用 `MFTS_SIGNAL_PRETRADE_STRICT=true` 改为强失败）
- 候选池默认采用“自适应扩池”：
- 基准池：`max(top_n * MFTS_SIGNAL_PRETRADE_POOL_MULT, MFTS_SIGNAL_PRETRADE_POOL_MIN_N)`（默认 `1.0x`, 最小 `0`）
- 默认 `MFTS_SIGNAL_PRETRADE_ALLOW_EXPAND=false`（不自动扩池，优先同层口径）
- 若显式开启扩池（`MFTS_SIGNAL_PRETRADE_ALLOW_EXPAND=true`），则按 `MFTS_SIGNAL_PRETRADE_POOL_STEP_N` 逐步扩到 `MFTS_SIGNAL_PRETRADE_POOL_MAX_N`
- 可用 `MFTS_SIGNAL_PRETRADE_POOL_N` 固定池大小（关闭自适应）
- 节假日/长周末防错位：当前默认启用 `MFTS_SIGNAL_PRETRADE_FORWARD_BUFFER_DAYS=10` 下限，避免“信号日无下一交易日样本”导致口径漂移
- 低覆盖日（`MFTS_STAGE_MIN_STOCKS`）直接拒绝出榜
- 防复发: `daily_all.py` 在 `--rebuild-days` 模式会自动放大 ML 回看窗口（注入 `MFTS_ML_LOOKBACK_DAYS`），避免历史重算时出现“指标清洗后为空”

---

## 📁 目录结构

```
stock_screener/
├── archive/                 # 归档的旧版本文件
│   ├── mfts_screener_lite.py
│   └── mfts_screener_v62.py
├── core/                    # 核心算法
│   ├── mfts_screener.py     # MFTS 规则选股引擎
│   └── mfts_screener_v62.py # 历史 v6.2 对照引擎
├── core/data/               # 共享只读 ODS 适配层
│   └── market_data_gateway.py
├── models/                  # ML模型
│   └── mfts_lgbm_*.pkl      # LightGBM 模型
├── output/                  # 输出结果（分层）
│   ├── scan/                # 扫描结果
│   ├── daily/               # ML 每日结果
│   ├── verify/              # T+N 验证结果
│   ├── backtest/            # 回测与统计
│   ├── risk/                # P1 风险暴露/归因/容量报告
│   ├── execution/           # P2 纸面 OMS 订单/成交/账本
│   └── audit/               # P2 审计日志
├── scripts/                 # 脚本工具 (22个)
│   ├── daily_all.py         # ⭐ 一键全流程 (推荐)
│   ├── project_doctor.py     # ODS 覆盖检查
│   ├── daily_ml_select.py   # ML 选股
│   ├── daily_verify.py      # T+N 验证
│   ├── train_mfts_lgbm.py   # 模型训练
│   └── backtest_*.py        # 回测脚本 (多个)
├── web/                     # Web 界面
│   ├── app.py               # Flask 应用
│   └── templates/           # HTML 模板
└── docs/                    # 文档
    ├── LOCAL_GUIDE.md       # 本地运行指南
    └── WORKFLOW.md          # 本文件
```

---

## ⚠️ 常见问题

### Q1: Web 页面显示空白
**原因**: Web 服务未运行或数据未更新
**解决**: 
```bash
python web/app.py  # 启动服务
python scripts/daily_all.py  # 更新数据
```

### Q2: 共享 ODS 数据未覆盖
**原因**: 外部数据供应链尚未发布目标交易日快照。
**解决**: 本项目不下载或补数；先检查 ODS，待供应链恢复后续跑全流程。
```bash
python scripts/project_doctor.py
python scripts/daily_all.py --mode catchup --catchup-days 2 --stage-min-stocks 3000 --verify-min-stocks 3000
```

### Q3: ML 选股无结果
**原因**: 模型文件缺失
**解决**: 确认 `models/` 目录下有 `.pkl` 文件

---

## 📅 推荐时间表

| 时间 | 操作 | 命令 |
|------|------|------|
| 08:30 | 启动 Web 服务 (如未运行) | `python web/app.py` |
| 18:00 | 运行日更新 | `python scripts/daily_all.py` |
| 18:10 | 刷新浏览器查看结果 | - |

---

*最后更新: 2026-04-09*
