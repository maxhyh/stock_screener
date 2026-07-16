# 项目索引

> 更新时间：2026-07-16

## 1. 生产主入口

按优先级只看这几处：

1. `python scripts/daily_all.py`
2. `python scripts/daily_ml_select.py`
3. `python core/mfts_screener.py`
4. `python web/app.py`
5. `python scripts/project_doctor.py`

不确定从哪里开始时，默认从 `daily_all.py` 和 `web/app.py` 入手。

## 2. 目录职责

- `core/`：规则引擎、风控、执行抽象，属于核心业务代码
- `scripts/`：生产编排、训练、回测、修复、研究脚本
- `web/`：Flask 应用、路由、页面展示
- `config/`：统一配置入口
- `utils/`：公共工具函数
- `data/`：待退役的本地旧缓存与历史适配工具；不是生产数据源，见 `docs/LEGACY_DATA_RETIREMENT.md`
- `tests/`：单元测试与链路测试
- `docs/`：流程、策略、部署、维护文档
- `memory/`：项目长期记忆、当前活跃约束、错误陷阱和夜间审查草稿
- `skills/`：Codex 本项目专用 skill 与审计/维护脚本
- `archive/`：归档代码，仅供参考
- `output/`：运行产物，不作为源码维护
- `logs/`：日志产物，不作为源码维护

## 3. 代码主链路

### 数据层

- `core/data/ashare_ods_loader.py` / `core/data/market_data_gateway.py`：共享 A 股 ODS 的只读入口；默认读取 `ASHARE_DATA_ROOT` 或 `/Users/max/Data/ashare-source-data`，按 `trade_date/snapshot` 选择最新 snapshot，并记录请求窗口、价格口径、BJ/9 过滤和 snapshot digest。
- `scripts/daily_all.py`：只读检查 ODS 是否覆盖目标交易日后运行扫描/ML/验证；它不会下载、补数或写入共享数据源。
- `scripts/quant_raw_model_walkforward_diagnosis.py`：raw-model ODS 诊断入口。默认使用 ODS，向前补齐 252 个交易日特征预热、向后补齐 `max(horizon)+1` 个交易日标签缓冲；缓存和 JSON 产物记录 snapshot 指纹，不能与 legacy 证据混用。

### 策略层

- `core/mfts_screener.py`：MFTS 规则扫描主实现
- `core/mfts_screener_v62.py`：v6.2 实验/对比版本
- `utils/signal_quality.py`：信号质量评分
- `utils/signal_refactor.py`：特征重构评分
- `utils/market_regime.py`：市场状态识别

### 交易与风控层

- `core/risk/pretrade.py`：前置风控硬门禁
- `core/execution/adapter.py`：执行抽象接口
- `core/execution/paper_broker.py`：纸面执行
- `core/execution/live_broker.py`：实盘/影子执行
- `core/platform/portfolio_engine.py`：capacity/crowding-aware 组合权重引擎

### 编排层

- `scripts/daily_all.py`：生产总编排
- `scripts/daily_ml_select.py`：每日推荐
- `scripts/daily_verify.py`：收益验证
- `scripts/quant_p1_analytics.py`：P1 风险分析
- `scripts/quant_p2_paper_trade.py`：P2 执行
- `scripts/quant_p2_rolling_replay.py`：P2 长窗滚动回放；排除缺下一交易日的尾端信号和 signal date 不存在于 ODS 行情的 stale/orphan daily 文件
- `scripts/quant_p2_shadow_diagnosis.py`：P2 shadow 诊断
- `scripts/quant_score_alpha_diagnosis.py`：profile daily 推荐文件的 score-level alpha smoke，先判断 final score/target-weight 排序是否有正的 top-bucket forward return，并跑赢候选池均值与底部桶
- `scripts/quant_p2_smoke_failure_diagnosis.py`：P2 smoke 失败归因，连接 score-alpha gate、P2 precheck、主档/候选同日历 ledger，区分 sell trap、cash drag、calendar mismatch 和 score-alpha 未穿透
- `scripts/quant_p2_failure_day_attribution.py`：P2 失败日订单/风控下钻，解释最差相对收益日是否来自 holiday-gap 降仓、blocked sell、entry-not-tradable 或 risk gate collapse
- `scripts/quant_p2_holiday_gap_guard_attribution.py`：holiday-gap guard 归因，比较 guard / non-guard 交易日、主档/候选相对收益、cash drag proxy、sell-trap/downside proxy，并按触发原因判断保护有效还是错杀收益
- `scripts/quant_stage_transition_diagnosis.py`：research stage alpha 衰减诊断；在 stage summary / transition summary 之外，输出 score-stage summary 和 alpha-decay summary，用 top/bottom spread、RankIC、kept/dropped return 定位最终排序或 target weight 是否反向选股
- `scripts/quant_capacity_feasible_alpha_diagnosis.py`：capacity-feasible alpha 前置诊断；在创建 vNext shadow profile 前，用当前 profile 约束重排候选 score，检查容量、行业、reserve、exit-trap 约束后是否仍有正的 selected forward return 和足够 target utilization，并拆解 top 候选被约束替换后的 selection loss。`--primary-promotion-modes keep,score_topn` 可验证正向 top 名单是否被 primary/reserve 标签困在 reserve cap 后。通过只代表“值得建 shadow 假设”，不代表可升档
- `scripts/quant_static_to_p2_pass_through_diagnosis.py`：静态 alpha 到 P2 路径穿透诊断；把 capacity-feasible daily selected forward return 与同窗主档/候选 P2 ledger 对齐，统计静态正收益日是否在 P2 相对主档跑输，并拆分 holiday cash drag、sell trap、entry block、underdeployment 与 path return loss
- `scripts/quant_raw_alpha_p2_residual_diagnosis.py`：raw alpha / final alpha / P2 residual 决策表；消费 stage-transition 和 static-to-P2 诊断，判断瓶颈是 raw ML alpha 弱、pipeline 排名损耗，还是 final 静态 alpha 无法穿透到 P2 路径
- `scripts/quant_raw_ml_horizon_diagnosis.py`：raw 模型/标签/horizon 审查；在全市场 raw stage 上测试 `ml_score` 对 1/3/5/8/10/15 等 open-to-open horizon 的预测力，并把模型 `label_horizon` 与 profile `holding_days` 写入 verdict，用于判断是 raw ML 整体失效、符号反向，还是和当前持有期不匹配
- `scripts/quant_raw_model_walkforward_diagnosis.py`：模型层 raw-universe walk-forward 对照；重新训练诊断模型检查 H=8/H=10 是否通过 top bucket、spread、RankIC 和 fold 稳定性，不创建 production model，不进入 daily/P2；支持 metadata-validated raw feature-frame cache，避免每轮实验重复重算全市场指标
- `scripts/quant_raw_model_instability_attribution.py`：模型层 fold 失效归因；针对重点失败 fold 或全 7-fold 对比 baseline、样本 recency weighting、lambdarank、L1/Huber objective、rank-normalized、cross-sectional-only、高漂移特征剔除、ex-ante regime-specific、逐日标签去均值/排序目标、`rank_norm_*` 组合变体、rank-normalized ensemble，以及 fold2/fold6 residual treatment variants，输出 ex-post regime summary、ex-ante signal-date regime summary、deployment day coverage、treatment activation、positive-hit probability、deployability expectation、feature drift / importance、top bucket exposure、variant family summary 和 fold attribution。支持 `--sample-mode date_stratified` 做确定性交易日分层抽样，避免把随机训练样本差异误读成模型修复。近期新增 signal-date day-state treatments、diagnosis-only engineered raw features、market-context features、positive/tail-ranked labels、two-stage positive-hit blend、downside-aware sample weighting、context day-state calibration、weak-positive / strict-positive / margin-positive training target 和 abstention/deployability heads。该脚本用于解释 split 不稳定，不创建 production model，不进入 daily/P2；最新证据显示 weak-positive context two-stage 线达到 `5/7` folds，但 critical fold2 仍是弱市绝对收益失败，fold2-only abstention 和 strict-positive 标签探针也未能转正
- `scripts/quant_raw_model_state_migration_diagnosis.py`：模型层 fold 状态迁移诊断；不重训模型，只比较 fit/valid/test 的 signal-date day-state 分布、KNN deployability 校准误差、ex-ante regime 收益迁移和漂移特征。用于解释 fold2 这类训练/验证窗口和测试窗口状态断裂的问题，不创建 production model，不进入 daily/P2
- `scripts/quant_raw_model_seed_stability_report.py`：模型层 seed/sample 稳定性 gate；汇总多次 instability attribution 的 `variant_family_summary`，要求 raw model variant 跨 seed / sample-mode 稳定通过 critical fold 和 fold pass-rate，防止挑单次随机抽样结果进入 profile/P2
- `scripts/quant_raw_model_fold_failure_matrix.py`：模型层 critical-fold 失效矩阵；把多次 instability attribution 的 fold metrics、ex-post / ex-ante regime failures、top-bucket feature exposure 和 drifted feature importance 聚合到同一张表，解释 2026Q1/Q2 fold 7 等关键窗口到底是 absolute top bucket failure、pool-relative failure、可事前识别的 regime failure 还是 drifted exposure
- `scripts/quant_raw_model_residual_fold_diagnosis.py`：模型层 residual fold 解释；当某个变体救回 fold7 但全 7-fold 仍失败时，对 fold2/fold6 等残差 fold 输出 absolute-loss、pool-relative miss、bottom-lag、ex-ante regime、ex-post regime、top feature exposure 和 drifted important features，避免把局部修复误读成可部署模型
- `scripts/quant_raw_model_residual_treatment_probe.py`：模型层 residual treatment 探针；消费 residual-fold diagnosis，把 fold2 定义为弱市 absolute-return calibration 问题，把 fold6 定义为 strong/neutral beta capture + `pos_52w` drift 问题，并输出后续 raw-model 实验和 gate。它只给模型实验定边界，不重训模型、不建 profile、不进入 P2
- `scripts/quant_profile_promotion_review.py`：档位升档门禁；可接入 score-alpha JSON，把最终排序 alpha gate 失败纳入硬否决
- `scripts/quant_refresh_promotion_gate.py`：刷新 rolling / P2 / shadow / funnel / promotion latest 工件；可主动刷新 profile-isolated score-alpha latest JSON，并在 P2 前裁剪 score-alpha gate 失败、profile daily 覆盖不足、缺少主档同一批 replayable signal dates、daily target utilization 不足、或 60 日执行烟测弱于主档的候选；reference calendar 会排除没有主数据行情的 stale/orphan shared daily 文件，输出 score-alpha / signal-coverage / target-utilization / P2-smoke precheck latest 证据；60 日 smoke 跳过候选时自动生成 P2 smoke failure diagnosis latest、P2 failure day attribution latest 和 holiday-gap guard attribution latest；若候选存在 capacity-feasible daily latest，还会自动生成 static-to-P2 pass-through diagnosis latest；支持 `--precheck-only` 只做便宜预筛，`--fail-fast-p2-smoke-window 60` 避免对执行失败候选继续跑 90/120，或用 `--reuse-rolling-latest` 显式复用已有 rolling summary
- `scripts/quant_rebuild_profile_daily_signals.py`：重建 profile-isolated daily 信号；用于候选长窗 P2 前补齐覆盖率。做 promotion 证据时优先使用 `--replayable-only`，并显式记录历史元数据新鲜度参数，避免把无下一交易日或元数据陈旧误判成候选失败
- `scripts/quant_exec_consistency_report.py`：P3 一致性

holiday-gap guard 支持 shadow profile 通过 `holiday_gap_reason_overrides` 按触发原因覆盖 cap，但默认档仍不得绕过 promotion gate 直接改变。

当前 profile 治理基线：`quality_regime` 仍为默认档；v7-v29 等候选均为 shadow/diagnostic 档，不能绕过 promotion gate。近期重点已经从单纯 ADV 转向 target-weight lineage、sell-trap 状态机、style gate 口径、post-filter alpha 质量和现金拖累识别。v24 条件化 holiday-gap cap 覆盖率通过但 score-alpha gate 失败；v25 的 liquidity target score 60 日 P2 主要靠低仓少亏；v26 修复 style 口径和 capacity fallback 后被加硬 score-alpha gate 拒绝；v27 把 primary/reserve 隔离并把 active reserve weight 压到 2%，但 ungrouped `target_weight` / `portfolio_rank_score` score-alpha 仍为负；v28 测试 softened ranking quantile + liquidity/exit-trap target blend，coverage 通过但 score-alpha 和 target utilization 均失败；v29 进一步按 `target_blend_score` relabel primary/reserve，cheap gates 和 capacity-feasible 诊断通过，但 60 日 P2 smoke 输给主档，NAV 约 `+0.10%` vs 主档 `+4.73%`，MDD 更差且 exit blocks 更多。静态到 P2 穿透诊断显示 v29 只有 `24/60` 个同窗日静态 selected forward return 为正，其中 `15` 天在 P2 相对主档跑输，整体 verdict 为 `static_alpha_not_p2_passed`。raw-alpha/P2-residual 决策表进一步显示 raw `ml_score` 全市场 top bucket 约 `-2.35%`、RankIC 约 `-0.057`，final `portfolio_rank_score` 静态通过但 P2 不穿透，overall verdict 为 `final_static_alpha_not_p2_executed_raw_alpha_weak`。raw ML horizon 审查显示最新模型 `label_horizon=3`，而默认档 `quality_regime` 是 `holding_days=8`、v29 是 `holding_days=10`；但正常方向的 `ml_score` 在 1/3/5/8/10/15 日 open-to-open horizon 均未通过，H=3 top bucket 约 `-0.51%`、H=8 top bucket约 `-2.18%`，反向 score 只在 H=1 有弱通过迹象。H=8/H=10 raw-universe walk-forward 对照显示：H=10 pooled OOS top bucket 约 `+1.38%`、top-minus-all 约 `+0.33pct`、RankIC 约 `0.054`，但 `7` 个 fold 只有 `3` 个通过，fold pass rate 约 `42.9%`，低于稳定性门槛；H=8 pooled top bucket 约 `+0.73%` 但低于全市场均值。H=10 focused instability attribution 显示：2025Q4 fold 6 的 baseline top bucket 虽为正但跑输全市场和 bottom bucket，recency weighting 可局部救回；2026Q1/Q2 fold 7 则是 absolute top bucket failure，baseline top bucket 约 `-1.66%`。后续 H=10 全 7-fold model-family 与 seed 稳健性对照显示：`rank_normalized` 和部分 rank-normalized ensemble 曾在单次随机抽样中修复 fold 7，但跨 seed 不稳；`rank_norm_drop_high_drift` 在 seed1/seed2 通过，但 seed3 与 deterministic `date_stratified` 采样均失败，date-stratified 下 fold 7 top bucket 约 `-0.53%`、top-minus-all 约 `-0.15pct`。最新 fold7 failure matrix 显示：baseline 是 `absolute_failure_with_drifted_exposure`，top bucket 负收益且跑输全市场，并暴露 `pv_corr_20` 等漂移重要特征；rank-normalized / rank_norm_drop_high_drift 是 `absolute_failure_regime_sensitive`，在 broad_down、mild_down、mild_up 等 regime 中反复失败；ensemble L1/Huber 是 `absolute_top_bucket_failure`，相对 spread 偶尔为正但 top bucket 仍会转负。最新 ex-ante regime probe 显示 fold7 的信号日可知状态能定位部分问题：`neutral` 27 天是 rank-normalized 线的主要负区，rank_normalized 在 neutral 下 top 约 `-1.97%`，而 risk_on / risk_off top bucket 为正但 RankIC 方向不稳；baseline 在 risk_on 下也严重反向。最新 fold7 regime-specific 探针显示：`rank_norm_regime_specific` 是当前最好变体，fold7 top 约 `-0.025%`、top-minus-all 约 `+0.36pct`、RankIC 约 `0.030`，但绝对 top bucket 仍为负；raw `regime_specific` 反而明显恶化，top 约 `-3.32%`。进一步的逐日排序标签目标 `rank_norm_regime_label_ranked` 能救 fold7，fold7 top 约 `+0.31%`、top-minus-all 约 `+0.69pct`、RankIC 约 `0.110`，但全 7-fold date-stratified 只通过 `2/7`，fold pass rate 约 `28.6%`。fold2/fold6 residual diagnosis 显示失败类型不同：fold2 是 `absolute_loss_but_beats_pool`，top 约 `-0.95%` 但跑赢全池约 `+0.96pct`，主要失败在 neutral/risk_on；fold6 是 `positive_top_but_pool_and_bottom_lag`，top 约 `+1.09%` 但跑输全池约 `-0.24pct`、跑输 bottom 约 `-0.83pct`，且 `pos_52w` 是漂移重要特征。residual treatment probe 进一步把 fold2 定义为 weak-market absolute-return calibration，硬门槛是 fold2 和弱窗口 top bucket 转正；把 fold6 定义为 beta_capture_pos52w_drift_repair，硬门槛是 neutral/broad-up top-minus-all 与 top-minus-bottom 不再为负。最新 treatment 7-fold 实验显示：absolute-return blend 没有救 fold2，fold2 top 从 `rank_norm_regime_label_ranked` 的约 `-0.79%` 恶化到约 `-2.27%`；pos_52w/beta overlay 把 fold6 spread 从约 `-0.675pct` 改到约 `-0.090pct`，但仍未转正且打坏 fold7；组合 treatment 让 fold7 通过但 fold2/fold6 仍失败。进一步的 strict treatment 实验显示：day-level veto 平均部署日只有约 `54.7%`、最低 fold 约 `18.3%`，fold2/fold6 均因部署覆盖不足失败；conditional pos_52w/beta 没有找到训练期可放行 regime，fold6 spread 仍约 `-0.968pct`；组合 strict variant 也失败并把 fold7 top 打到约 `-0.231%`。day-state calibration/opportunity critical-fold run 显示：更细的 signal-date kNN day-state 仍失败，fold2 calibrated top 约 `-1.49%`，fold6 calibrated top-minus-all 仍约 `-0.382pct`，fold6 opportunity detector activation 为 `0%` 且 expected edge 约 `-0.368pct`。engineered positive two-stage 7-fold 实验也未放行：最佳 variant 只通过 `2/7` folds，fold2 top 仍约 `-1.80%`，fold6 top 约 `+1.17%` 但仍跑输全池约 `-0.16pct`，fold7 top 约 `-0.002%` 未转正。最新 context feature family 实验把问题进一步收敛：`context_rank_norm_regime_label_ranked` 通过 `3/7` folds，修复 fold6（top 约 `+1.75%`、top-minus-all 约 `+0.42pct`）和 fold7（top 约 `+0.47%`、top-minus-all 约 `+0.85pct`），但 fold2 仍是负 top bucket（约 `-1.72%`）。修复 ex-ante regime 字段清洗后，`h10_downside_context_7fold_date_stratified` 证据更严格：`downside_context_rank_norm_regime_label_ranked` 通过 fold6/fold7，但 fold2 仍约 `-1.85%`；`downside_context_rank_norm_regime_label_tail_ranked` 是本轮 family best，仍只有 `3/7` folds 通过且 critical folds 未全过。`h10_context_day_calibration_7fold_date_stratified` 进一步把 richer day-state calibration 接到 context 线，best `day_calibrated_context_rank_norm_regime_label_ranked` 通过 fold6/fold7 并把 fold2 改善到约 `-1.66%`，但仍未转正；downside + day calibration 还会打坏 fold6 spread。最新 `h10_weak_positive_context_7fold_date_stratified` 是目前最接近的模型层线索：`day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked` 通过 `5/7` folds，fold6/fold7 都通过，但 critical fold2 仍约 `-1.88%`；fold2 最好也只有 `downside_context_rank_norm_regime_label_weak_positive_ranked` 的约 `-1.54%`。当前瓶颈不再是 fold6/fold7，而是 fold2 弱市绝对收益无法转正；仍不能回到 capacity/P2，下一步应研究 fold2-specific day-level deployability target、二阶段 day/head 模型，或重新设计弱市标签目标。

最新 fold2-only abstention probe 进一步显示：验证窗 day-state deployability abstention 只能把 fold2 top bucket 改到约 `-1.60%`，同时部署率降到约 `47.6%` 并低于地板；stock-level positive-hit deployability head 没有触发弃权，仍 `84/84` 天部署，top bucket 约 `-2.75%`。这说明当前 signal-date day-state / hit-prob deployability 预期在 fold2 测试窗失准，粗弃权不是修复方向。

最新 fold2-only strict-positive 标签探针也失败：`margin_positive` 最好仍约 `-2.09%`，`strict_positive` 约 `-2.18%`，two-stage strict/margin 更差，均弱于 baseline 约 `-1.92%`。这说明单纯强化绝对正收益标签奖惩不会修复 fold2。

最新 fold2 state-migration 诊断显示，fold2 更像状态分布迁移而不是简单 deployability 乐观误判：test expected return mean 约 `-1.26%`，actual 约 `-1.91%`，expected deploy rate 仅约 `29.8%`；但 test state drift max PSI 约 `6.51`，`market_vol_20d`、`volatility_ratio_day_std`、`amount_day_mean/std`、`pos_52w_day_mean`、`pv_corr_20_day_mean` 等 day-state 特征显著漂移。test 中 `risk_on`/`neutral` regime 的实际 day mean return 分别约 `-6.10%` / `-2.85%`，而 valid 期 risk_off 却极强，说明验证窗不是 fold2 测试窗的好代理。进一步的 state-robust probe 显示：matched-state training 有一点相对改善，最好 fold2 top 约 `-1.54%`、top-minus-all 约 `+0.37pct`，但仍未转正；state-weighted training 和 state-aware weak target 更差。因此当前仍停留在 raw-model 层，不能建 profile 或跑 P2。

### 展示层

- `web/app.py`：应用工厂与路由注册入口
- `web/routes/`：蓝图路由
- `web/services/`：数据服务层

## 4. scripts 分层

详情看 `scripts/README.md`，这里只保留核心判断：

- 生产运行：`daily_*`, `quant_p1_analytics.py`, `quant_p2_paper_trade.py`, `quant_exec_consistency_report.py`
- 研究回测：`quant_*`, `research/*`, `history/*`, `backtest_mfts_lite.py`, `analyze_signal_performance.py`
- 修复维护：`fix_*`, `repair_*`, `project_doctor.py`
- 兼容历史：`history/backtest_5y.py`, `history/backtest_comparison.py`, `history/backtest_mfts_6m.py`, `history/backtest_v62_compare.py`
- 已归档旧实现：`archive/scripts/backtest.py`, `archive/scripts/optimize.py`, `archive/scripts/qlib_integration.py`

## 5. 当前整理约定

- 根 README 负责导航，不再承担全部细节说明
- `docs/PROJECT_INDEX.md` 是代码入口索引
- `docs/WORKFLOW.md` 负责“怎么跑”
- `scripts/README.md` 负责“脚本能不能用、该不该用”
- `docs/DOCUMENTATION_AND_SKILLS.md` 负责文档职责边界、skill 清单、重复/冲突审查
- `skills/audit-a-share-quant-project/references/codex-engineering-discipline.md` 负责 Codex 工程纪律、验证边界和专家审查升级条件
- 重复主题文档尽量合并，不再平行新增

## 6. Skill 与 Agent 入口

- `AGENTS.md`：agent 操作权威入口。
- `agent.md`：兼容入口，内容应始终指向 `AGENTS.md`。
- `skills/audit-a-share-quant-project/SKILL.md`：当前唯一 repo-specific skill，负责 A 股量化平台审计、维护、执行可信和文档/架构体检。
- `skills/audit-a-share-quant-project/scripts/find_audit_hotspots.py`：静态热点扫描。
- `skills/audit-a-share-quant-project/scripts/build_maintenance_snapshot.py`：维护快照，包含热点和架构规模指标。

除非未来出现稳定、独立、反复执行且触发边界清晰的新工作流，否则不要新增平行 skill；优先扩展现有 repo skill 的 references 或 scripts。

## 7. 维护建议

- 日常只维护生产主链路，研究脚本按需整理
- 新增脚本前，先判断能否合并进现有脚本
- 新增文档前，先判断现有文档是否可以补充
- 临时分析脚本若不复用，应尽快归档或删除
- 一次性调试脚本统一进入 `archive/scripts/`
