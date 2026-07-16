# 脚本分层说明

## 使用原则

- 优先使用“生产主链路”脚本
- 研究/分析脚本按需运行，不要混入日常生产
- 修复/维护脚本仅在排障时使用

## A. 生产主链路

- `daily_all.py`：生产编排总入口
- `project_doctor.py`：共享 ODS 可用性和项目健康检查
- `daily_ml_select.py`：ML 每日推荐
- `daily_verify.py`：推荐验证
- `daily_mfts_select.py`：规则扫描的单独入口
- `quant_p1_analytics.py`：P1 风险暴露/归因/容量报告
- `quant_p2_paper_trade.py`：P2 纸面交易执行
- `quant_p2_rolling_replay.py`：P2 长窗滚动回放；会排除没有下一交易日的尾端信号，也会排除 signal date 不存在于主数据行情的 stale/orphan daily 文件，避免旧推荐文件污染执行证据
- `quant_exec_consistency_report.py`：P3 回测/执行一致性报告
- `quant_memory_evolve.py`：项目记忆系统刷新；从长期记忆提取可复用条目到 `memory/actives.md`

## B. 回测与参数研究

- `quant_portfolio_backtest.py`：组合回测主入口
- `quant_optimize.py`：参数优化
- `quant_walk_forward.py`：Walk-forward 稳健性评估
- `quant_anti_overfit_pipeline.py`：抗过拟合流水线
- `run_quant_profile.py`：档位回测入口
- `quant_profile_ab_compare.py`：不同档位对比
- `quant_signal_refactor_compare.py`：特征重构前后对比
- `quant_signal_pretrade_alignment_report.py`：信号与前置风控对齐分析
- `quant_score_alpha_diagnosis.py`：profile daily 推荐文件的 score-level alpha smoke；可用 `--enforce-alpha-gate` 在 `target_weight` / `portfolio_rank_score` top bucket 非正、未跑赢候选池均值/底部桶或 RankIC 不为正时直接失败；带 `--group-col` 的分组诊断只用于发现子样本线索，不能产生 profile 级 alpha gate pass
- `quant_capacity_feasible_alpha_diagnosis.py`：vNext 前置诊断；读取 profile research stage snapshots 或 profile daily 文件，用现有 profile 的 ADV、行业、reserve、exit-trap、单票和总仓位约束重排候选 score，判断 alpha 是否能在容量约束后仍保持正的 selected forward return。报告同时拆解 unconstrained top 到 capacity-selected basket 的 overlap、top dropped、replacement return、selection loss 和约束原因；可用 `--primary-promotion-modes keep,score_topn` 诊断正向 top 名单是否被 primary/reserve 标签困在 reserve cap 后。它只决定是否值得创建新的 shadow profile，不是 promotion evidence
- `quant_static_to_p2_pass_through_diagnosis.py`：连接 capacity-feasible daily 证据和同窗 P2 ledger，检查静态 selected forward return 为正的交易日是否在 P2 中跑赢主档，并按 holiday cash drag、sell trap、entry block、underdeployment 和 path return loss 归因。它用于解释“静态容量内 alpha 通过但 P2 smoke 失败”的候选，不创建 profile，也不作为 promotion pass
- `quant_p2_smoke_failure_diagnosis.py`：解释“score-alpha/coverage 通过但 60 日 P2 smoke 失败”的候选，按同日历对齐主档和候选的 P2 ledger，输出 NAV/MDD/target-weight/entry-exit block 差异、最差相对收益日和失败标签
- `quant_p2_failure_day_attribution.py`：对 P2 smoke 失败的最差相对日做订单/风控下钻，输出 holiday-gap 降仓、blocked sell、entry-not-tradable、risk gate 和订单明细
- `quant_p2_holiday_gap_guard_attribution.py`：对 holiday-gap guard 做独立归因，比较 guard 触发日与非触发日、主档与候选相对收益、缩仓 cash drag proxy、sell-trap/downside proxy，并按触发原因标记 `effective_protection` / `false_positive_cash_drag` / `mixed_needs_review`
- `quant_stage_transition_diagnosis.py`：读取 research stage snapshots，诊断 raw / filter / ranking / pretrade / optimizer / final target 各阶段的 alpha 衰减；同时输出阶段内 score spread 与 RankIC，定位是候选池、排序方向、风控门禁还是 target weight 造成 alpha 损耗
- `quant_raw_alpha_p2_residual_diagnosis.py`：决策层诊断；消费 stage-transition 的 score/transition 输出和 static-to-P2 pass-through summary，合成 raw universe alpha、final target 静态 alpha、P2 路径 residual 的一行 verdict。用于判断下一步该回到 raw model/label、修 ranking pipeline，还是诊断执行路径；不创建 profile，不参与 promotion
- `quant_raw_ml_horizon_diagnosis.py`：raw 模型/标签/horizon 审查；在 `raw_scored_post_indicator` 全市场 stage 上用同一个 `ml_score` 测试多个 open-to-open horizon，并同时输出模型 `label_horizon`、profile `holding_days`、正常/反向 score direction 的 top-bucket return、RankIC 和 horizon verdict。用于判断 raw ML 是整体失效、符号反向，还是只和当前持有期不匹配；不创建 profile，不参与 promotion
- `quant_raw_model_walkforward_diagnosis.py`：模型层 H=8/H=10 raw-universe walk-forward 对照；默认经只读 ODS loader 读取 `ASHARE_DATA_ROOT`，向前扩展 252 个交易日计算长窗口特征，并向后扩展 `max(horizon)+1` 个交易日生成 open-to-open 标签。source、根目录、最新快照规则、实际 snapshot 摘要和 source-panel 覆盖摘要会写入缓存/JSON 证据。显式 legacy 文件输入仅用于历史比较，不能作为新的 promotion 证据。
- `quant_raw_model_instability_attribution.py`：模型层 fold 失效归因；针对 walk-forward 中失败或不稳定的 fold 重跑 baseline、recency-weighted、lambdarank、L1/Huber objective、rank-normalized、cross-sectional-only、high-drift-feature-drop、ex-ante regime-specific、逐日标签去均值/排序目标、`rank_norm_*` 组合变体、若干 rank-normalized ensemble，以及 residual treatment variants：`abs_calibrated_rank_norm_regime_label_ranked`、`pos52w_beta_rank_norm_regime_label_ranked`、`abs_pos52w_beta_rank_norm_regime_label_ranked`、`day_veto_rank_norm_regime_label_ranked`、`conditional_pos52w_beta_rank_norm_regime_label_ranked`、`day_veto_conditional_pos52w_beta_rank_norm_regime_label_ranked`、`day_calibrated_rank_norm_regime_label_ranked`、`day_opportunity_pos52w_beta_rank_norm_regime_label_ranked`、`day_calibrated_opportunity_rank_norm_regime_label_ranked`、`engineered_rank_norm_regime_label_positive_ranked`、`two_stage_hit_rank_norm_regime_label_ranked`、`engineered_two_stage_hit_rank_norm_regime_label_positive_ranked`、`context_rank_norm_regime_label_ranked`、`context_rank_norm_regime_label_tail_ranked`、`context_two_stage_hit_rank_norm_regime_label_tail_ranked`、`downside_context_rank_norm_regime_label_ranked`、`downside_context_rank_norm_regime_label_tail_ranked`、`day_calibrated_context_rank_norm_regime_label_ranked`、`day_calibrated_downside_context_rank_norm_regime_label_ranked`、`context_rank_norm_regime_label_weak_positive_ranked`、`context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked`、`day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked`，diagnosis-only abstention variants：`abstain_*`、`validated_abstain_*`、`hit_abstain_*`，stricter absolute-positive label variants：`strict_positive_daily_ranked` / `margin_positive_daily_ranked`，以及 fold2 state-migration variants：`state_weighted_*`、`matched_state_*`、`state_weak_positive_daily_ranked`。`state_weighted_*` 和 `matched_state_*` 只用 held-out 窗口的 signal-date 状态分布做诊断，不用 held-out 标签，不能直接作为生产部署逻辑。它会输出 ex-post regime、ex-ante signal-date regime、部署日覆盖率、treatment 激活率、positive-hit probability、deployability expectation、重要特征漂移、top bucket 特征暴露、variant family summary 和 fold attribution。支持 `--sample-mode date_stratified` 做确定性交易日分层抽样，并共用 raw feature-frame cache。当前用于解释 2025Q4 与 2026Q1/Q2 的 H=10 top bucket 失效；fold7 regime-specific / label-objective / day-state calibration / engineered two-stage / context feature-family / downside-aware weighting / weak-positive target / deployability abstention / strict-positive target / state-matched training 探针可用于验证 ex-ante regime-conditioned objective、signal-date day-state treatment、新原始特征、弱日样本权重、弱市正收益标签、状态迁移鲁棒训练或弃权头是否把失败拉回正 top bucket。它只做诊断，不创建 profile，不进入 P2
- `quant_raw_model_state_migration_diagnosis.py`：模型层 fold 状态迁移诊断；不重训模型，只复用 raw feature-frame cache 和 walk-forward fold 切分，比较 fit/valid/test 的 signal-date day-state 分布、KNN deployability 预期校准误差、ex-ante regime 收益迁移和漂移特征。用于解释 fold2 这类“训练/验证窗口可识别，测试窗口失真”的问题，不创建 profile，不进入 P2
- `quant_raw_model_seed_stability_report.py`：模型层 seed/sample 稳定性 gate；消费多次 `quant_raw_model_instability_attribution` 的 `variant_family_summary`，汇总每个 variant 的跨 seed / sample-mode 通过率、critical fold 稳定性、最差 fold7 top bucket 和推荐动作。它不重训模型，不创建 profile，不进入 P2；任何 raw 模型线若只在单次随机抽样中过关，应在这里被拦截
- `quant_raw_model_fold_failure_matrix.py`：模型层 critical-fold 失效矩阵；消费多次 instability attribution 的 variant/regime/exante-regime/exposure/importance artifacts，聚合指定 fold 的 top bucket、spread、RankIC、事后/事前 regime failure、top-bucket feature exposure 和 drifted important features。用于解释某个 critical fold 为什么反复失败；不重训模型，不创建 profile，不进入 P2
- `quant_raw_model_residual_fold_diagnosis.py`：模型层残差 fold 解释；当某个变体救回 critical fold 但全 7-fold 仍 split-unstable 时，按 fold 输出 residual failure label、ex-ante/ex-post regime 失败、top-bucket feature exposure 和 drifted important features。默认用于解释 `rank_norm_regime_label_ranked` 在 fold2/fold6 的残余失败；不重训模型，不创建 profile，不进入 P2
- `quant_raw_model_residual_treatment_probe.py`：模型层残差处理探针；消费 residual-fold diagnosis，把 fold2 的弱市绝对收益保护/校准问题和 fold6 的强/中性市 beta + `pos_52w` 漂移机会捕捉问题拆成不同 treatment hypothesis、实验建议和 raw-model gate。它只用于定义下一轮模型实验，不重训模型，不创建 profile，不进入 P2，也不是 promotion evidence
- `daily_ml_select.py` 支持 shadow profile 用 `score_quantile_normal` / `score_quantile_choppy` / `score_quantile_panic` 或 `score_quantile_q` 覆盖 ranking-pool 分位数 gate，并支持 `target_score_blend` 将多个现有分数归一化混合为 `target_blend_score`；`capacity_safe_primary_rank_mode=target_score_topn` 可让 primary/reserve 标签按目标分数 topN 生成，用于验证 reserve-trapped alpha 假设。这些字段只应用于新候选实验，默认档不变
- `quant_profile_promotion_review.py`：档位升档门禁；可用 `--score-alpha-diagnosis` 接入 score-alpha JSON，候选最终排序 alpha gate 失败时不得升档
- `quant_refresh_promotion_gate.py`：一键刷新 rolling / P2 / shadow / funnel / promotion；可用 `--refresh-score-alpha` 先刷新 profile-isolated score-alpha latest，并用 `--precheck-score-alpha` 在 P2 前剔除 final-ranking alpha smoke 失败的候选，同时写出 `quant_score_alpha_precheck_latest.json/csv`；可用 `--precheck-signal-coverage` 在 P2 前剔除 profile daily 覆盖不足或缺少主档同一批 replayable signal dates 的候选；reference calendar 只使用同时存在 shared daily 和主数据行情的日期，同时写出 `quant_signal_coverage_precheck_latest.json/csv`；`--precheck-signal-coverage` 会同步运行 daily target utilization 预检，也可显式用 `--precheck-target-utilization`，输出 `target_weight_sum_mean_60`、`target_weight_sum_p10_60`、`zero_target_days_60` 和 `zero_target_rate_pct_60`，低仓位或高零仓位候选会在 P2 前跳过；可用 `--fail-fast-p2-smoke-window 60` 先跑执行烟测，候选若 NAV/MDD/有效仓位/买卖阻塞弱于主档则跳过后续 90/120 和 promotion 刷新，同时写出 `quant_p2_smoke_precheck_latest.json/csv` 并自动触发 P2 smoke failure diagnosis latest、P2 failure day attribution latest、holiday-gap guard attribution latest；若候选存在 capacity-feasible daily latest，还会自动触发 static-to-P2 pass-through diagnosis latest；可用 `--p2-execution-mode inprocess` 复用同进程回放加速；可用 `--precheck-only` 只做便宜预筛后退出；可用 `--reuse-rolling-latest` 显式复用已有 rolling summary 并跳过 rolling compare 刷新

holiday-gap guard 可以在 profile 中用 `holiday_gap_reason_overrides` 按 `signal_to_trade_gap`、`post_trade_gap`、`signal_to_trade_gap+post_trade_gap` 覆盖 `total_position_cap` / `single_pos_cap`。这个机制用于 shadow 诊断，不是默认档升档捷径。
- `quant_rebuild_profile_daily_signals.py`：为候选档重建 profile-isolated daily 文件；做 60/90/120 证据前优先使用 `--replayable-only` 排除无下一交易日的尾端信号日，历史回放可显式设置 `--max-metadata-staleness-days 999` 避免元数据新鲜度误杀旧证据，但不要伪造无数据日期
- profile-isolated rebuild 会允许空 daily 输出进入证据链。capacity-aware optimizer 选不出组合时应保留 empty / zero-target evidence，而不是用无约束 fallback 权重制造仓位。
- `research/capacity_estimation.py`：容量估计

## C. 历史生成与数据补齐

- `history/generate_historical_scans.py`
- `history/generate_historical_scans_6m.py`
- `history/generate_historical_ml.py`
- `verify_historical.py`
- `build_benchmark_hs300.py`
- `migrate_outputs.py`

## C1. 共享数据源适配

- `core/data/ashare_ods_loader.py`：只读读取共享数据根 `ASHARE_DATA_ROOT`（默认 `/Users/max/Data/ashare-source-data`）下的 `ods/` 分区 Parquet。它按每个 `trade_date` 选择最新 `snapshot`，合并 `daily_bars`、`daily_basic`、`daily_adj_factor`、`daily_limits` 和 `instrument_master`，并输出兼容字段如 `ts_code`、`vol`、`name`、`industry`。默认排除 BJ/9-code；如只是做数据覆盖诊断可显式 `include_bj9=True`。

## D. 训练与因子分析

- `train_mfts_lgbm.py`
- `research/analyze_factor_ic.py`
- `analyze_signal_performance.py`
- `research/daily_hybrid_select.py`
- `batch_ml_predict.py`
- `auto_retrain.py`
- `research/capacity_estimation.py`

## E. 修复与运维工具

- `project_doctor.py`：项目健康检查
- `quant_memory_evolve.py --check`：检查项目记忆文件是否完整
- `fix_missing_data.py`：历史缺口检测/补数
- `fix_volume_unit_by_date.py`：成交量单位修复
- `repair_missing_volume.py`：成交量缺失修复
- `repair_missing_ohlc.py`：OHLC 缺失修复
- `daily_risk_report.py`：日风险报告
- `setup_local.sh`
- `setup_cron.sh`

## F. 兼容/历史脚本

- `history/backtest_5y.py`
- `history/backtest_comparison.py`
- `backtest_mfts_lite.py`
- `history/backtest_mfts_6m.py`
- `history/backtest_v62_compare.py`

以下脚本实现已迁移到 `archive/scripts/`，不再作为 `scripts/` 主目录入口保留：

- `archive/scripts/backtest.py`
- `archive/scripts/optimize.py`
- `archive/scripts/qlib_integration.py`
- `archive/scripts/debug_download.py`

## 建议约定

- 新增脚本前，先判断能否并入现有主链路脚本
- 新脚本必须在本文件登记用途
- 若脚本只服务一次性分析，完成后应归档或删除，避免长期堆积
