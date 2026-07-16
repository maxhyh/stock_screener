# A 股量化选股与纸面执行平台

> 从 MFTS 多因子选股演进而来的 A 股日频量化研究、回测、P2 纸面执行、shadow 诊断和 profile promotion 治理平台。

## 快速导航

- 日常生产入口：`conda run -n stock python scripts/daily_all.py`
- 一键启动前端：`scripts/start_web.sh`
- 数据可用性检查：`conda run -n stock python scripts/project_doctor.py`
- 单独 ML 推荐：`conda run -n stock python scripts/daily_ml_select.py`
- 规则扫描：`conda run -n stock python core/mfts_screener.py`
- Web 查看：`scripts/start_web.sh`

建议配合以下索引一起看：

- 文档导航：`docs/README.md`
- 代码结构索引：`docs/PROJECT_INDEX.md`
- 专家审查简报：`docs/EXPERT_REVIEW_BRIEF.md`
- 专家审查提示词：`docs/EXPERT_REVIEW_PROMPT.md`
- 文档与 Skill 体系审查：`docs/DOCUMENTATION_AND_SKILLS.md`
- 操作流程：`docs/WORKFLOW.md`
- 脚本分层：`scripts/README.md`
- Codex 工程纪律：`skills/audit-a-share-quant-project/references/codex-engineering-discipline.md`

已退出主维护面的旧脚本实现已移入 `archive/scripts/`，避免与当前生产入口混在一起。

## 专家审查入口

如果你是通过 GitHub 审查本项目，请先看：

1. `docs/EXPERT_REVIEW_BRIEF.md`
2. `docs/PROJECT_INDEX.md`
3. `config/quant_live_profiles.json`
4. `core/platform/portfolio_engine.py`
5. `core/execution/paper_broker.py`
6. `scripts/quant_p2_paper_trade.py`
7. `scripts/quant_profile_promotion_review.py`

当前 Git 仓库只跟踪源码、配置、schema、测试、文档和记忆系统。`data/` 大型行情文件、`output/` 回测与 P2 流水、`logs/` 日志、`models/*.pkl` 模型二进制均为本地运行产物，不随审查快照提交。

当前默认档仍是 `quality_regime`。v7-v29 等候选档都只是历史 shadow/diagnostic 档，不代表已通过 promotion。旧 P2、回测和 raw-model 数值来自 ODS 迁移前的数据代际，只能用于理解工程演化，不能用于当前升档或收益判断。当前工作冻结 profile/P2 调参，优先修复复权研究价格、历史 PIT universe、官方涨跌停字段、manifest 强校验和模型 horizon/lineage 等 P0 证据问题。最新状态以 `config/quant_live_profiles.json`、同代际 artifacts、`memory/actives.md` 和 `memory/errors.md` 为准。

## 📖 项目简介

本项目起源于 TradingView MFTS v6.1 指标的 Python 复刻，但当前重点已经扩展为 A 股日频量化平台：研究信号、组合构建、回测、P2 纸面执行、执行一致性诊断、promotion gate 和自我记忆演化。

## 当前建议认知方式

- 把 `core/` 看成“策略和执行内核”
- 把 `scripts/` 看成“编排、训练、回测和修复入口”
- 把 `web/` 看成“查看结果和操作界面”
- 把 `output/`、`logs/` 看成运行产物，不参与源码维护

## 🗂️ 项目结构

```
stock_screener/
├── README.md                      # 项目说明
├── CHANGELOG.md                   # 更新日志
├── requirements.txt               # 依赖
│
├── config/                        # 🆕 统一配置管理
│   ├── __init__.py
│   └── settings.py               # MFTS/训练/部署配置
│
├── utils/                         # 🆕 工具模块
│   ├── __init__.py
│   └── logger.py                 # 统一日志系统
│
├── tests/                         # 🆕 单元测试
│   ├── conftest.py               # 测试夹具
│   ├── test_mfts_screener.py     # 核心算法测试
│   └── test_indicators.py        # 技术指标测试
│
├── core/                          # 核心算法
│   ├── mfts_screener.py          # 主选股引擎
│   └── mfts_screener_v62.py      # v6.2 优化版
│
├── scripts/                       # 自动化脚本
│   ├── daily_all.py              # 每日更新 (数据+选股+验证)
│   ├── daily_mfts_select.py      # 纯MFTS选股
│   ├── daily_ml_select.py        # ML增强选股
│   ├── train_mfts_lgbm.py        # LightGBM训练
│   └── ...                       # 更多脚本
│
├── core/data/                     # 共享只读 ODS 数据入口
│   ├── ashare_ods_loader.py      # 分区/快照适配器
│   └── market_data_gateway.py    # 市场数据与执行窗口
│
├── web/                           # Web 服务
│   ├── app.py                    # Flask API
│   └── templates/                # Flask 模板
│
├── docs/                          # 文档
│   ├── SIGNAL_LOGIC.md           # 信号逻辑详解
│   ├── ML_TRAINING.md            # ML训练指南
│   └── DEPLOYMENT.md             # 部署指南
│
├── models/                        # 训练好的模型
│   └── mfts_lgbm_*.pkl           # LightGBM模型
│
├── logs/                          # 日志目录
│   └── mfts.log                  # 运行日志
│
└── output/                        # 输出结果
    ├── scan/                     # 扫描结果 (mfts_scan_*.csv / mfts_latest.csv)
    ├── daily/                    # ML 每日结果 (daily_*.csv)
    ├── verify/                   # 验证结果 (verification_*.csv / historical_summary.csv)
    ├── backtest/                 # 回测与统计 (backtest_*.csv/png 等)
    ├── risk/                     # P1 风险暴露/归因/容量报告
    ├── execution/                # P2 纸面 OMS 订单/成交/账本
    └── audit/                    # P2 审计日志
```

## 🚀 快速开始

### 1. 进入默认虚拟环境

本项目默认使用 Conda 环境 `stock`，所有运行、测试和证据生成应使用同一环境：

```bash
conda activate stock
python --version
```

非交互命令可使用：

```bash
conda run -n stock python scripts/project_doctor.py
```

当前工作站的默认解释器路径为 `/opt/homebrew/Caskroom/miniforge/base/envs/stock/bin/python`，前端启动脚本会默认使用该路径，也可通过 `MFTS_PYTHON` 显式覆盖。

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置共享只读数据源

```bash
export ASHARE_DATA_ROOT=/Users/max/Data/ashare-source-data
python scripts/project_doctor.py
```

项目不会下载、补数、修复或写入该数据源。旧本地缓存的退役边界见
`docs/LEGACY_DATA_RETIREMENT.md`。

### 4. 运行选股

```bash
python core/mfts_screener.py
# 指定日期复盘
python core/mfts_screener.py --date 20260320
```

### 4.1 一键更新模式（支持隔几天更新）

```bash
# 默认：补齐最近缺口（推荐）
python scripts/daily_all.py --mode catchup --catchup-days 10

# 建议：开启覆盖率门槛，跳过低覆盖异常交易日
python scripts/daily_all.py --mode catchup --catchup-days 10 --stage-min-stocks 3000 --verify-min-stocks 3000

# 策略升级后：重算最近N个交易日（覆盖已有scan/daily/verify）
python scripts/daily_all.py --mode catchup --rebuild-days 20 --stage-min-stocks 3000 --verify-min-stocks 3000

# 只跑最新交易日
python scripts/daily_all.py --mode latest

# 收盘前自动回退上一交易日（默认阈值 18:00，可调）
MFTS_AUTO_TARGET_CUTOFF_HOUR=18 python scripts/daily_all.py --mode latest

# 说明：若共享 ODS 未覆盖目标日，latest 模式会停止并报告 data_availability

# 只做验证补齐
python scripts/daily_all.py --mode verify-only --catchup-days 10

# 单独验证可执行口径（默认 open_to_close_t1）
python scripts/daily_verify.py --date 20260320 --label-mode open_to_close_t1

# 与交易系统一致的验证口径（推荐，当前 default_profile=quality_regime，holding_days=8）
python scripts/daily_verify.py --date 20260320 --label-mode open_to_open --label-horizon 8

# 数据覆盖由外部供应链维护；本项目只校验并读取 ODS
python scripts/project_doctor.py
```

### 4. 查看结果

**方式一**: 启动 Flask 服务
```bash
scripts/start_web.sh
# 访问 http://127.0.0.1:5001
```

或手动启动：
```bash
python web/app.py
# 访问 http://localhost:5001
```
说明：
- 默认仅本机监听（`MFTS_LOCAL_ONLY=true`），默认 host 为 `127.0.0.1`
- 若需远程触发“执行类 API”（如运行扫描/触发补数），建议设置：
  - `MFTS_API_WRITE_TOKEN=your_token`
  - 请求头携带 `X-API-Token: your_token`（或 `Authorization: Bearer your_token`）
- 首页已升级为“交易平台总览”：
  - 同屏展示：交易执行清单、规则扫描 Top、策略参数候选、组合权益曲线、历史验证曲线
  - 支持按交易日切换查看
  - 股票展示统一为“名称（代码）”可点击样式
  - 涨跌与收益统一采用 A 股配色：红涨绿跌
  - 支持点击股票查看个股详情（K线 + 关联交易记录）
  - 支持查看最近组合交易执行记录（入场/出场/收益/权益/代码列表）
  - 支持收益率钻取：年收益率 -> 月收益率 -> 交易日每日收益率（联动图表 + 明细表）
  - UI 风格升级为科技风交易控制台（深色渐变 + 数据卡片 + 图表联动）
- `/ml` 页面也会同步显示分市场状态仓位建议

**方式二**: 直接查看 CSV 结果
```bash
cat output/scan/mfts_latest.csv
```

### 5. 运行测试 (可选)

```bash
# 运行所有测试
pytest tests/ -v

# 运行覆盖率报告
pytest tests/ --cov=core --cov-report=html

# 查看日志
tail -f logs/mfts.log
```

### 6. 量化交易组合回测与参数优化（新增）

```bash
# 先生成沪深300基准文件（首次一次即可）
python scripts/build_benchmark_hs300.py --start-date 20100101

# 先确保已有历史 ML 推荐文件（output/daily/daily_YYYYMMDD.csv）
# 可用一键重算补齐：
python scripts/daily_all.py --mode catchup --rebuild-days 120 --stage-min-stocks 3000 --verify-min-stocks 3000

# 组合交易回测（把“选股”转为“可交易组合”，默认实盘参数）
# 默认参数读取自 config/quant_live_profiles.json 的 default_profile（当前 quality_regime）
# 当前默认（quality_regime）：TopN=13, Hold=8, MaxSinglePos=0.04, fallback_total_position=0.60
# balanced / balanced_regime / balanced_h8 仍保留为历史对照档，不是当前默认档
# 默认排除：北交所 9 开头代码（不参与选股/回测）
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20

# 新增：交易引擎与基准模式（left/right/hybrid + hs300/synthetic/none）
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 --engine-mode hybrid --benchmark-mode hs300

# 新增：信号质量门禁（默认开启，可调阈值与ML融合权重）
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 \
  --min-signal-quality 0.35 --ml-quality-blend 0.85 --max-abs-pct-chg 9.0

# 新增：信号特征重构（稳定性融合 + 重构门禁）
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 \
  --stability-blend 0.20 --min-refactor-score 0.45

# 关闭特征重构（回到旧排序）用于A/B验证
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 \
  --disable-feature-refactor

# 可选：单笔组合止损（例如 -3%）
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 --max-loss-per-trade 0.03

# 新增：组合风控增强（行业分散 + 相关性去重 + 动态退出 + 风险开关）
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 \
  --engine-mode hybrid --benchmark-mode hs300 --max-loss-per-trade 0.03 \
  --max-industry-positions 3 --max-pair-corr 0.85 \
  --take-profit 0.18 --stop-loss 0.08 --trail-drawdown 0.10 \
  --risk-window 5 --risk-cut-win-rate 0.35 --risk-cut-avg-ret -0.005 --risk-cut-factor 0.60

# 新增：分市场参数（正常/震荡/恐慌三挡）示例
python scripts/quant_portfolio_backtest.py --start 2025-01-01 --end 2026-03-20 \
  --tp-normal 0.18 --tp-choppy 0.14 --tp-panic 0.10 \
  --sl-normal 0.08 --sl-choppy 0.06 --sl-panic 0.05 \
  --trail-normal 0.10 --trail-choppy 0.08 --trail-panic 0.06 \
  --corr-normal 0.85 --corr-choppy 0.75 --corr-panic 0.65

# 参数优化（TopN / 持有期 / 单票上限 / 是否启用分市场仓位）
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20

# 新增：多目标评分 + 失效原因 + 模拟盘推荐参数表
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 \
  --robust-mode on \
  --min-annual-return-pct 0 --min-excess-annual-pct 0 --min-sharpe 0 --max-drawdown-limit-pct -15 \
  --turnover-cap-pct 4500 \
  --recommend-top-k 5

# 新增：严格门槛收敛命令（当前推荐参数来源）
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 \
  --topn-grid 6,8,10 --hold-grid 8 --maxpos-grid 0.03,0.04 \
  --engine-mode right --benchmark-mode hs300 --robust-mode on \
  --min-annual-return-pct 0 --min-excess-annual-pct 0 --min-sharpe 0.7 \
  --max-drawdown-limit-pct -12 --turnover-cap-pct 3500 \
  --min-oos-excess-total-median 1.0 --min-oos-mdd-worst -8.0 \
  --min-oos-pass-rate 0.75 --min-oos-valid-window-ratio 1.0 --oos-min-windows 3 \
  --min-signal-quality 0.40 --ml-quality-blend 0.80 --max-abs-pct-chg 8.5 \
  --stability-blend 0.30 --min-refactor-score 0.50

# 新增：优化时启用特征重构参数（与回测/WF保持一致）
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 \
  --stability-blend 0.20 --min-refactor-score 0.45

# 参数优化（同时评估组合风控增强参数）
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 \
  --engine-mode hybrid --benchmark-mode hs300 \
  --max-industry-positions 3 --max-pair-corr 0.85 \
  --take-profit 0.18 --stop-loss 0.08 --trail-drawdown 0.10

# 分市场参数同样可接入优化器（推荐）
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 \
  --engine-mode hybrid --benchmark-mode hs300 \
  --tp-normal 0.18 --tp-choppy 0.14 --tp-panic 0.10 \
  --sl-normal 0.08 --sl-choppy 0.06 --sl-panic 0.05 \
  --trail-normal 0.10 --trail-choppy 0.08 --trail-panic 0.06 \
  --corr-normal 0.85 --corr-choppy 0.75 --corr-panic 0.65

# 新增：可同时指定交易引擎与基准模式
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 --engine-mode hybrid --benchmark-mode hs300

# 新增：稳健评分（默认已开启，可显式指定）- 优先 OOS 超额与回撤稳定
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 --engine-mode hybrid --benchmark-mode hs300 --robust-mode on --oos-warmup-months 6 --oos-test-months 2 --oos-step-months 2

# 新增：Walk-Forward 滚动验证（训练窗选参 + 测试窗验证）
python scripts/quant_walk_forward.py --start 2025-01-01 --end 2026-03-20 --train-months 6 --test-months 2 --step-months 2 --engine-mode hybrid --benchmark-mode hs300

# 新增：Walk-Forward 同步启用特征重构参数
python scripts/quant_walk_forward.py --start 2025-01-01 --end 2026-03-20 \
  --train-months 6 --test-months 2 --step-months 2 \
  --engine-mode hybrid --benchmark-mode hs300 \
  --stability-blend 0.20 --min-refactor-score 0.45

# 新增：Walk-Forward 固定参数模式（覆盖网格）
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

# 新增：反过拟合两阶段流水线（先WF找稳定区，再robust优化）
python scripts/quant_anti_overfit_pipeline.py \
  --start 2025-01-01 --end 2026-03-20 \
  --wf-train-months 6 --wf-test-months 2 --wf-step-months 2 \
  --wf-topn-grid 8,10,12,15,18 --wf-hold-grid 4,5,6,8 --wf-maxpos-grid 0.04,0.05,0.06

# 新增：流水线一键透传信号质量/特征重构参数到 WF + Optimize
python scripts/quant_anti_overfit_pipeline.py \
  --start 2025-01-01 --end 2026-03-20 \
  --wf-train-months 6 --wf-test-months 2 --wf-step-months 2 \
  --wf-topn-grid 8,10,12,15,18 --wf-hold-grid 4,5,6,8 --wf-maxpos-grid 0.04,0.05,0.06 \
  --min-signal-quality 0.35 --ml-quality-blend 0.85 --max-abs-pct-chg 9.0 \
  --stability-blend 0.20 --min-refactor-score 0.45

# 新增：信号特征重构 A/B 对比（baseline vs refactor）
python scripts/quant_signal_refactor_compare.py \
  --start 2026-01-01 --end 2026-03-20 \
  --top-n 10 --holding-days 6 \
  --engine-mode hybrid --benchmark-mode hs300 \
  --stability-blend 0.20 --min-refactor-score 0.45

# 新增：按配置档位一键运行（配置文件: config/quant_live_profiles.json）
python scripts/run_quant_profile.py --profile quality_regime --start 2025-01-01 --end 2026-03-20
python scripts/run_quant_profile.py --profile quality_regime_candidate_v18_balanced_trap_guard --start 2025-01-01 --end 2026-03-20
python scripts/run_quant_profile.py --profile quality_regime_candidate_v23_nav_weighted_style_gate --start 2025-01-01 --end 2026-03-20

# 历史对照档仍可运行，但不能视为当前默认档
python scripts/run_quant_profile.py --profile balanced_h8 --start 2025-01-01 --end 2026-03-20
python scripts/run_quant_profile.py --profile right_h8_low_turnover --start 2025-01-01 --end 2026-03-20

# 新增：A/B 对比（示例：主档 vs shadow 诊断档）
python scripts/quant_profile_ab_compare.py --start 2025-01-01 --end 2026-03-20

# 新增：一次输出多组对比
python scripts/quant_profile_ab_compare.py --base-profile quality_regime --compare-profile quality_regime_candidate_v18_balanced_trap_guard --extra-profiles quality_regime_candidate_v23_nav_weighted_style_gate --start 2025-01-01 --end 2026-03-20
```

输出文件：
- `output/backtest/quant_trades_*.csv`：交易明细
- `output/backtest/quant_backtest_summary.csv`：回测汇总
- `output/backtest/quant_optimization_results.csv`：参数优化结果
- `output/backtest/quant_strategy_paper_recommendations.csv`：可直接用于模拟盘的推荐参数表
- `output/backtest/quant_strategy_paper_recommendations.json`：推荐参数 JSON
- `output/backtest/quant_walk_forward_windows_*.csv`：Walk-Forward 每窗结果
- `output/backtest/quant_walk_forward_oos_trades_*.csv`：Walk-Forward OOS 交易明细
- `output/backtest/quant_anti_overfit_report_*.json`：反过拟合流水线结构化报告
- `output/backtest/quant_anti_overfit_report_*.md`：反过拟合流水线可读报告
- `output/backtest/quant_profile_ab_*.csv`：profile A/B 指标对比

### 7. P1/P2 平台化扩展（新增）

```bash
# 在一键流程中追加 P1 + P2（建议先 dry-run）
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --p2-broker paper --p2-dry-run

# 追加 P3：回测 vs 执行一致性偏差报告
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --with-p3-consistency --p2-broker paper --p3-broker paper --p2-dry-run

# P3 阈值门禁（不达标直接失败，推荐在自动化任务使用）
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --with-p3-consistency \
  --p2-broker paper --p3-broker paper --p2-dry-run \
  --p3-max-ret-gap-mae-pct 2.0 --p3-min-match-coverage-pct 60 \
  --p3-max-order-block-rate-pct 35 --p3-max-risk-block-rate-pct 35 \
  --p3-min-matched-rows 20 --p3-rate-eval-rows 10 --p3-enforce-thresholds

# 说明：开启 --p3-enforce-thresholds 后，失败通常表示“指标未达阈值”，不是流程错误
# 说明：P3 默认会自动择优 trades 文件、按交易日去重 ledger，并在 expected 时间窗内对齐比较

# 行业覆盖率门禁（默认 80）；仅排障时可临时关闭
python scripts/daily_all.py --mode latest --with-p2 --with-p3-consistency --min-industry-coverage-pct 80
python scripts/daily_all.py --mode latest --with-p2 --with-p3-consistency --disable-industry-coverage-gate

# 元数据行业覆盖检查（排障）
python scripts/project_doctor.py

# 单独执行 P1（风险暴露/归因/容量）
python scripts/quant_p1_analytics.py --write-latest

# 单独执行 P2（执行引擎，按本轮推荐参数复现）
python scripts/quant_p2_paper_trade.py --signal-file output/daily_mfts_20260320.csv --top-n 8 --max-single-pos 0.04 --default-total-pos 0.60 --broker paper --dry-run --write-latest
python scripts/quant_p2_paper_trade.py --broker live --live-mode shadow --signal-file output/daily_mfts_20260320.csv --use-recommendation --recommend-rank 1 --write-latest

# 单独执行 P2（优先使用优化推荐参数，适合“先优化策略再模拟”）
python scripts/quant_p2_paper_trade.py --broker paper --signal-file output/daily_mfts_20260320.csv --use-recommendation --recommend-rank 1 --dry-run --write-latest

# 单独执行 P2（channel 隔离，不污染主 paper 账本）
python scripts/quant_p2_paper_trade.py --broker paper --channel paper_exp_a --signal-file output/daily_mfts_20260320.csv --use-recommendation --recommend-rank 1 --write-latest

# 单独执行 P2（低换手档 + 40日风控网格最优参数）
MFTS_P2_PROFILE=right_h8_low_turnover python scripts/quant_p2_paper_trade.py \
  --broker paper --signal-file output/daily_mfts_20260320.csv --top-n 10 --max-single-pos 0.04 \
  --target-total-pos 0.60 --risk-max-industry-weight 0.35 --risk-max-adv-participation 0.06 --risk-min-price 2.0 \
  --risk-max-style-size-exposure-abs 1.1 --risk-max-style-beta-exposure-abs 1.1 \
  --risk-max-style-momentum-exposure-abs 1.2 --risk-max-style-vol-exposure-abs 1.3 \
  --risk-style-lb-short 20 --risk-style-lb-beta 60 \
  --dry-run --write-latest

# 一键流程中使用推荐参数（P2）
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --p2-broker paper --p2-dry-run --p2-use-recommendation --p2-recommend-rank 1

# 一键流程（P2）显式透传风控参数（建议用于低换手档）
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --p2-broker paper --p2-dry-run \
  --p2-risk-max-industry-weight 0.35 --p2-risk-max-adv-participation 0.06 --p2-risk-min-price 2.0 \
  --p2-risk-max-style-size-exposure-abs 1.1 --p2-risk-max-style-beta-exposure-abs 1.1 \
  --p2-risk-max-style-momentum-exposure-abs 1.2 --p2-risk-max-style-vol-exposure-abs 1.3 \
  --p2-risk-style-lb-short 20 --p2-risk-style-lb-beta 60

# 说明：上述 P2 风控参数会自动透传到 Step3(ML) 的“信号端前置风控”
# 目标：减少“信号端可选但 P2 下单被拦截”的口径漂移

# 推荐：以低换手档位作为 active profile 运行全流程（验证缺样本默认按跳过）
MFTS_P2_PROFILE=right_h8_low_turnover python scripts/daily_all.py \
  --mode latest --with-p1 --with-p2 --with-p3-consistency \
  --p2-broker paper --p2-dry-run \
  --p2-risk-max-industry-weight 0.35 --p2-risk-max-adv-participation 0.06 --p2-risk-min-price 2.0 \
  --p2-risk-max-style-size-exposure-abs 1.1 --p2-risk-max-style-beta-exposure-abs 1.1 \
  --p2-risk-max-style-momentum-exposure-abs 1.2 --p2-risk-max-style-vol-exposure-abs 1.3 \
  --p2-risk-style-lb-short 20 --p2-risk-style-lb-beta 60

# 单独执行 P3（一致性报告）
python scripts/quant_exec_consistency_report.py --broker paper --write-latest

# 单独执行 P3（一致性阈值门禁强制）
python scripts/quant_exec_consistency_report.py --broker paper --rate-eval-rows 10 --write-latest --enforce-thresholds

# P2 多窗口滚动回放（策略优化评估）
python scripts/quant_p2_rolling_replay.py --profiles right_h8_low_turnover --windows 60,90,120 --broker paper --write-latest

# P2 style 阈值网格回放（避免拍脑袋阈值）
python scripts/quant_p2_rolling_replay.py \
  --profiles right_h8_low_turnover --windows 7 --broker paper \
  --risk-max-industry-weight 0.35 --risk-max-adv-participation 0.06 --risk-min-price 2.0 \
  --style-size-grid 0.7,0.9,1.1 --style-beta-grid 0.7,0.9,1.1 \
  --style-momentum-grid 1.0,1.2,1.4 --style-vol-grid 0.9,1.1,1.3 \
  --style-lb-short-grid 20 --style-lb-beta-grid 60 \
  --write-latest

# P3 一致性报告（自动输出 style_hit 分层归因 + 逐笔一致性回放）
python scripts/quant_exec_consistency_report.py --broker paper --rate-eval-rows 10 --write-latest

# 信号端前置风控 vs P2 风控对齐报告（逐日差值）
python scripts/quant_signal_pretrade_alignment_report.py \
  --broker paper --channel paper_pretrade_diag \
  --min-date 20260401 --max-date 20260410 --write-latest

# 推荐：同层对齐诊断时固定 P2 top_n=30，并关闭信号端自动扩池
# MFTS_SIGNAL_PRETRADE_ALLOW_EXPAND=false \
# python scripts/quant_p2_paper_trade.py --broker paper --channel paper_pretrade_diag --top-n 30 --date 20260401 ...
```

说明：`daily_ml_select.py` 的信号端前置风控默认采用 research-safe 口径，即
`MFTS_SIGNAL_PRETRADE_USE_NEXT_TRADE_DAY=false`，只使用信号日可观察信息。若要做
P2 对齐或事后执行诊断，可显式设置 `MFTS_SIGNAL_PRETRADE_USE_NEXT_TRADE_DAY=true`，
但该模式不得作为研究选股或 profile promotion 的默认证据。

新增输出：
- `output/risk/risk_exposure_summary_*.csv`：状态层风险暴露汇总
- `output/risk/risk_exposure_industry_*.csv`：行业暴露汇总
- `output/risk/return_attribution_*.csv`：收益归因（状态/退出原因/月度）
- `output/risk/capacity_cost_*.csv`：容量与成本诊断
- `output/execution/paper_orders_*.csv`：纸面订单
- `output/execution/paper_fills_*.csv`：纸面成交
- `output/execution/paper_risk_gates_*.csv`：下单前风控拦截明细
- `output/risk/signal_pretrade_gates_*.csv`：信号端前置风控拦截明细（daily_ml_select 输出）
- `output/risk/signal_pretrade_summary_*.json`：信号端前置风控汇总（含 gate_trade_date/pool_n/top_reason）
- `output/risk/pretrade_alignment_*.csv`：信号端前置风控 vs P2 风控逐日对齐明细
- `output/risk/pretrade_alignment_summary_*.json`：前置风控对齐摘要（pool层MAE + TopN同层MAE）
- `output/execution/paper_ledger.csv`：纸面账户账本
- `output/audit/paper_audit_log.jsonl`：审计日志
- `output/risk/exec_consistency_paper_*.csv`：回测-执行偏差明细
- `output/risk/exec_consistency_style_attribution_*.csv`：style_hit 与收益偏差分层归因
- `output/risk/exec_tick_replay_*.csv`：逐笔（订单级）一致性明细
- `output/risk/exec_tick_replay_layer_*.csv`：逐笔分层汇总（预期成分/方向/状态）
- `output/risk/exec_tick_replay_summary_*.json`：逐笔一致性摘要
- `output/backtest/p2_rolling_replay_summary_*.csv`：P2 滚动回放窗口汇总

### 8. 健康检查

```bash
curl http://localhost:5001/health

# 项目级健康检查（文件/数据/模型）
python scripts/project_doctor.py
```

### 9. 数据异常修复（可选）

```bash
# 修复指定日期成交量单位异常（股/手）
python scripts/fix_volume_unit_by_date.py --date 20260319 --apply
```

### 10. 数据源故障排查（实盘常见）

当共享 ODS 未覆盖目标交易日时，通常是外部数据供应链延迟，而不是策略逻辑错误。建议流程：

```bash
# 1) 检查共享只读 ODS
python scripts/project_doctor.py

# 2) 覆盖恢复后再跑一键流程
python scripts/daily_all.py --mode catchup --catchup-days 2 --stage-min-stocks 3000 --verify-min-stocks 3000
```

## 📊 信号类型

| 等级 | 名称 | 含义 | 风险 |
|------|------|------|------|
| L1 | 抢筹 | 极度超跌反弹 | 高 |
| L2 | 建仓 | 中度超跌+趋势确认 | 中 |
| L3 | 加仓 | 趋势回调买点 | 低 |
| 趋势:突破 | 突破买入 | 20日新高+放量 | 中 |
| 趋势:动量 | 动量追踪 | 均线多头排列 | 低 |
| 趋势:底部启动 | 底部突破 | 超跌后突破MA20 | 中 |

## 🔧 核心算法

### Alpha 评分因子

| 因子 | 权重来源 | 说明 |
|------|----------|------|
| 动量因子 (Mom_5/20) | LightGBM IC=-0.075 | 最强因子 |
| BIAS 乖离率 | IC=-0.070 | 超跌核心 |
| Z-Score | IC=-0.055 | 对数空间标准化 |
| 量价相关性 | IC=-0.056 | 背离检测 |
| RSI/KDJ/MFI | 振荡指标 | 辅助确认 |
| Wyckoff VPA | 专业量价分析 | Stopping Volume |

### 分层豁免机制

| 超跌等级 | BIAS 条件 | 流动性过滤 | 趋势过滤 |
|----------|----------|------------|----------|
| 极度 | < -15% | ✅ 豁免 | ✅ 豁免 |
| 深度 | < -10% | 放宽至 0.4 | ✅ 豁免 |
| 普通 | >= -10% | 标准 0.6 | 标准 |

## 更多文档

### 核心文档
- [信号逻辑说明](docs/SIGNAL_LOGIC.md) - MFTS 规则与信号逻辑
- [本地运行指南](docs/LOCAL_GUIDE.md) - 本地环境与启动流程
- [部署文档](docs/DEPLOYMENT.md) - 本地部署与服务化
- [项目索引](docs/PROJECT_INDEX.md) - 目录职责、脚本分层与整理建议

### ML增强相关
- [ML训练指南](docs/ML_TRAINING.md) - 模型训练完整流程

### 高级主题
- MFTS优化指南 - 基于IC分析优化策略（见artifacts）
- 每日手动流程 - 完整执行方案（见artifacts）

## 📊 项目结构

```
stock_screener/
├── core/
│   ├── mfts_screener.py         # MFTS核心算法
│   └── mfts_screener_v62.py     # v6.2优化版
├── core/data/
│   ├── ashare_ods_loader.py     # 共享 ODS 分区/快照适配器
│   └── market_data_gateway.py   # 共享 ODS 市场数据入口
├── scripts/
│   ├── daily_mfts_select.py     # 纯MFTS选股
│   ├── daily_ml_select.py       # ML增强选股
│   ├── daily_verify.py          # T+1验证
│   ├── verify_historical.py     # 历史验证(T+1/T+5/T+10)
│   ├── quant_portfolio_backtest.py # 组合交易回测（新增）
│   ├── quant_optimize.py        # 组合参数优化（新增）
│   ├── quant_signal_refactor_compare.py # 信号重构A/B对比（新增）
│   ├── run_quant_profile.py     # 按档位运行回测（新增）
│   ├── quant_profile_ab_compare.py # 档位A/B对比（新增）
│   ├── train_mfts_lgbm.py       # LightGBM训练
│   ├── project_doctor.py       # ODS 健康检查
│   ├── research/                # 研究脚本
│   └── history/                 # 历史生成/旧回测
├── models/
│   └── mfts_lgbm_*.pkl          # 训练好的模型
├── output/
│   ├── scan/                    # 扫描结果
│   ├── daily/                   # 每日选股结果
│   ├── verify/                  # 验证结果与历史汇总
│   └── backtest/                # 回测报告与统计
├── web/
│   ├── app.py                   # Flask后端API
│   └── templates/
│       ├── ml_daily.html        # ML选股页面
│       └── ml_history.html      # 历史验证页面
└── docs/                        # 完整文档
```

## 🆕 ML增强功能

### 双策略对比

系统提供两种选股策略供对比：

**1. 纯MFTS规则版** (`daily_mfts_select.py`)
- 基于Alpha评分排序
- 完全透明的技术指标规则
- 适合理解策略逻辑

**2. ML增强版** (`daily_ml_select.py`)
- LightGBM模型预测
- 自动优化指标权重
- 适应市场环境变化

```bash
# 运行纯MFTS选股
python scripts/daily_mfts_select.py --top 30

# 运行ML增强选股
python scripts/daily_ml_select.py --top 30

# 对比两种策略（需要历史数据）
python scripts/history/backtest_comparison.py --days 30
```

### IC因子分析

理解哪些技术指标最有效：

```bash
# 运行IC分析（10年数据）
python scripts/research/analyze_factor_ic.py

# 查看结果
cat output/factor_ic_analysis_T1.csv
# 若已执行迁移，也可能在 output/backtest/factor_ic_analysis_T1.csv
```

**Top 5因子**（当前结果）：
1. ATR% - IC: -0.051（波动率，最强）
2. Volume Ratio - IC: -0.049（量比）
3. BIAS-20 - IC: -0.047（超跌）
4. RSI-14 - IC: -0.047（超卖）
5. BIAS-13 - IC: -0.047（短期超跌）

### 模型训练

```bash
# 训练LightGBM模型
python scripts/train_mfts_lgbm.py

# 推荐：与实盘执行对齐（默认读取 default_profile.holding_days，当前=8）
python scripts/train_mfts_lgbm.py --label-mode open_to_open

# A/B 对照：同配置下切换 H=3 / H=8
python scripts/train_mfts_lgbm.py --label-mode open_to_open --label-horizon 3
python scripts/train_mfts_lgbm.py --label-mode open_to_open --label-horizon 8

# 模型会自动保存到
# models/mfts_lgbm_YYYYMMDD.pkl
```

### 历史验证分析

追踪T+1、T+5、T+10收益表现：

```bash
# 验证过去30天
python scripts/verify_historical.py --days 30

# 生成output/verify/historical_summary.csv
```

### 5年完整回测

```bash
# 运行5年回测（2020-2025）
python scripts/history/backtest_5y.py

# 生成报告：
# - output/backtest/backtest_report.csv（详细交易记录）
# - output/backtest/backtest_charts.png（可视化图表）
```

**预期输出**：
- 总交易次数、天数
- T+1/T+5/T+10胜率和收益
- 年度表现分析
- 信号类型统计

### MFTS策略优化

基于IC分析和ML结果优化MFTS：

```bash
# 查看优化指南
cat docs/MFTS_OPTIMIZATION.md

# 主要优化方向：
# 1. 根据IC调整因子权重
# 2. 使用Feature Importance优化
# 3. 动态阈值调整
# 4. A/B测试验证
```

### Web API

```python
# 获取最新ML选股
GET /api/ml/latest

# 获取历史验证汇总
GET /api/ml/history/summary

# 获取指定日期详情
GET /api/ml/history/detail/20260109

# 获取验证结果
GET /api/ml/verification/20260108
```

### Web界面

```
http://localhost:5001/ml          - ML每日选股
http://localhost:5001/ml/history  - 历史验证分析
```

## 更新日志

查看 [CHANGELOG.md](CHANGELOG.md) 了解版本历史。

## 许可证

MIT License
