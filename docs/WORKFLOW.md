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
│  ├── MFTS v6.1 选股扫描                                  │
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

# 推荐：与交易系统一致（次日开盘买入，持有 default_profile 对应天数；当前 3 天）
python scripts/daily_verify.py --date 20260320 --label-mode open_to_open --label-horizon 3
```

### 3. 单独数据更新
```bash
python scripts/daily_incremental_update.py
```
- 功能: 仅更新当日行情数据
- 数据源: 东方财富 (via AkShare)
- 输出: `data/daily_all_5y.parquet`
- 性能调优: 多日缺口补数可用 `MFTS_RANGE_WORKERS` 调整并发（默认6）
```bash
MFTS_RANGE_WORKERS=8 python scripts/daily_incremental_update.py
```
- 指定日期补数（适合断档修复）：
```bash
python scripts/daily_incremental_update.py --target-date 20260319
```
- 覆盖门禁（默认开启）：若新增交易日覆盖股票数低于 `MFTS_MIN_DAILY_COVERAGE`（默认3000），将拒绝写入主数据
- 行业元数据恢复链路（自动）：`东财行业板块 -> 东财spot行业字段 -> 新浪行业板块(label)`，并带缓存
- 行业兜底触发阈值可调：`MFTS_INDUSTRY_FALLBACK_TARGET_COVERAGE`（默认 `0.80`）
- 即使数据已最新，脚本也会刷新一次元数据，避免 `stock_info.csv` 长期低覆盖
- 手动仅刷新元数据（排障）：
```bash
python -c "import scripts.daily_incremental_update as m; m.refresh_stock_metadata()"
```
- 历史单位修复（单日成交量“股/手”异常时）：
```bash
python scripts/fix_volume_unit_by_date.py --date 20260319 --apply
```

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
- 默认参数来源：`config/quant_live_profiles.json` 的 `default_profile`（当前 `balanced`）
- 当前默认（balanced）：`top_n=10`、`holding_days=3`、`max_single_pos=0.06`、`use_regime_position=False`
- balanced 档位已内置分市场风控参数：`tp/sl/trail/corr(normal/choppy/panic)=0.18/0.08/0.10/0.85, 0.14/0.06/0.08/0.75, 0.08/0.04/0.05/0.60`
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
python scripts/run_quant_profile.py --profile conservative --start 2025-01-01 --end 2026-03-20
python scripts/run_quant_profile.py --profile balanced --start 2025-01-01 --end 2026-03-20
python scripts/run_quant_profile.py --profile balanced_regime --start 2025-01-01 --end 2026-03-20
python scripts/run_quant_profile.py --profile balanced_h8 --start 2025-01-01 --end 2026-03-20
python scripts/run_quant_profile.py --profile aggressive --start 2025-01-01 --end 2026-03-20

# A/B 对比（默认 balanced vs balanced_regime）
python scripts/quant_profile_ab_compare.py --start 2025-01-01 --end 2026-03-20

# 三组对比（H=3、H=3+regime、H=8）
python scripts/quant_profile_ab_compare.py --base-profile balanced --compare-profile balanced_regime --extra-profiles balanced_h8 --start 2025-01-01 --end 2026-03-20
```
- 档位说明：
  - `conservative`: 低单票上限 + 中低总仓，优先回撤控制
  - `balanced`: 均衡档，适合常规运行
  - `balanced_regime`: 与 balanced 相同参数，但启用分市场建议仓位
  - `balanced_h8`: 与 balanced 相同参数，但持有期 8 天（用于持有期 A/B）
  - `aggressive`: 更高交易强度，追求收益弹性

### 4. 单独 MFTS 选股
```bash
python core/mfts_screener.py
```
- 功能: 运行 MFTS v6.1 策略选股
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
│   ├── mfts_screener.py     # MFTS v6.1 选股引擎
│   └── mfts_screener_v62.py # MFTS v6.2 优化引擎
├── data/                    # 数据存储
│   └── daily_all_5y.parquet # 5年历史数据 (东方财富)
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
│   ├── daily_incremental_update.py  # 数据更新
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

### Q2: 数据更新失败
**原因**: 网络问题、数据源限流或 AkShare 上游接口临时异常
**解决**: 先自检接口，再定点补数，最后续跑全流程
```bash
python - <<'PY'
import akshare as ak
for name, fn in [("sina", ak.stock_zh_a_spot), ("eastmoney", ak.stock_zh_a_spot_em)]:
    try:
        print(name, "ok", fn().shape)
    except Exception as e:
        print(name, "fail", str(e)[:120])
PY

python scripts/daily_incremental_update.py --target-date 20260325
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
