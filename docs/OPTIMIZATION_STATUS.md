# 项目优化进度清单（P1/P2/P3）

> 更新时间：2026-04-24 11:05
> 说明：本清单用于回答两个问题
> 1) 这轮到底完成了什么
> 2) 下一步最需要做什么

## 0. 本轮新增落地（2026-04-14）

### A. P0 数据门禁升级（已完成）
1. `daily_all.py` 新增行业覆盖率硬门禁（默认开启）：
- `--min-industry-coverage-pct`（默认 `80`）
- `--disable-industry-coverage-gate`（可临时关闭）
2. 当门禁不达标时，自动阻断：
- P2 执行（`--with-p2`）
- P3 一致性报告（`--with-p3-consistency`）
3. 价值：
- 防止“行业映射缺失导致风控失真”时继续执行，避免输出伪稳定结果。

### B. P3 一致性诊断升级（已完成）
1. `scripts/quant_exec_consistency_report.py` 新增 run_id 级归因：
- 订单阻塞主因（来自 `paper_orders_*.csv` 的 `status/reason`）
- 风控拦截主因（来自 `paper_risk_gates_*.csv` 的 `reasons`）
- 每日偏差主驱动：`order_blocking / risk_gates / cost / unexplained`
2. 新增一致性阈值门禁：
- `--max-ret-gap-mae-pct`
- `--min-match-coverage-pct`
- `--max-order-block-rate-pct`
- `--max-risk-block-rate-pct`
- `--min-matched-rows`
- `--enforce-thresholds`（不达标返回非零）
3. `daily_all.py` 已打通上述 P3 参数透传，支持编排级硬约束。

### C. P2 回放隔离能力（已完成）
1. `scripts/quant_p2_paper_trade.py` 新增：
- `--channel`（输出通道名）
2. 作用：
- 同一 broker 下可隔离多套账本/订单/审计产物，避免污染主 `paper` 账本。

### D. 滚动回放引擎（已完成）
1. 新增脚本：`scripts/quant_p2_rolling_replay.py`
2. 能力：
- 支持 `--profiles` 多档位、`--windows` 多窗口（如 `60,90,120`）
- 自动逐日调用 P2 执行并输出窗口汇总
- 输出核心指标：`nav_return`、`max_drawdown`、`turnover`、`exec_block_rate`、`risk_block_rate`
- 内置多目标 `objective_score`，用于档位优选
3. 产物：
- `output/backtest/p2_rolling_replay_runs_*.csv`
- `output/backtest/p2_rolling_replay_summary_*.csv`
- `output/backtest/p2_rolling_replay_meta_*.json`

### E. 本轮验证与测试（已完成）
1. 新增测试：
- `tests/test_p2_rolling_replay.py`
- `tests/test_daily_all_orchestration.py` 增加行业门禁阻断用例
2. 回归结果：
- 关键相关测试 `14 + 14 + 2 = 30` 全部通过
3. 冒烟验证：
- `quant_exec_consistency_report.py --enforce-thresholds` 已按阈值返回失败码
- `quant_p2_rolling_replay.py --profiles right_h8_low_turnover --windows 3` 可正常产出回放结果

### F. 编排稳定性补丁（已完成）
1. `daily_all.py` 自动目标日升级：
- 新增收盘时段感知：收盘前（默认 `<18:00`）自动取上一交易日
- 环境变量：`MFTS_AUTO_TARGET_CUTOFF_HOUR`（默认 `18`）
2. `daily_all.py --mode latest` 数据更新优化：
- 当 `latest_data_date >= auto_target` 时直接跳过增量更新，不再触发冗余补数
3. 实测结果：
- 早盘运行不再误拉“当日未落地数据”
- 避免“目标日已覆盖仍全量补数 5500 只”的长耗时问题

### G. 行业覆盖恢复闭环（已完成）
1. `daily_incremental_update.py` 行业回退链路升级：
- 新增新浪板块兜底：`stock_sector_spot(indicator=行业/新浪行业)` + `stock_sector_detail(sector=label)`
- 修复关键参数：`stock_sector_detail` 需传 `label`（非中文板块名）
2. 新增元数据刷新入口：
- `refresh_stock_metadata()`（可独立执行）
- 即使“主数据已最新并跳过增量更新”，也会自动刷新一次 `stock_info.csv`，避免行业覆盖长期卡死
3. 实测验收：
- `data/stock_info.csv` 行业覆盖恢复至 `91.89%`（`5055/5501`）
- `daily_all.py --mode latest --with-p1 --with-p2 --with-p3-consistency` 标准模式 `7/7` 全成功

### H. P3 一致性口径对齐（已完成）
1. `quant_exec_consistency_report.py` 对齐增强：
- 自动择优 `quant_trades`：按与 `ledger` 交易日重叠度自动选择最匹配回测文件（可关闭）
- `ledger` 默认按交易日去重：同日保留最后一次 run，避免重复实验污染覆盖率
- 默认按 `expected` 时间窗过滤 `ledger`，避免窗口外样本稀释覆盖率
- 兼容旧版 `quant_trades`（缺少 `excess_ret` 字段）参与自动择优
2. 阈值计算窗口优化：
- 新增 `--rate-eval-rows`（默认 `10`）：订单/风控阻塞率门槛按最近 N 个匹配样本评估（收益偏差与覆盖率仍按全匹配样本）
- `daily_all.py` 新增透传参数 `--p3-rate-eval-rows`
3. 实测验收（严格模式）：
- `daily_all.py --mode latest --with-p1 --with-p2 --with-p3-consistency --p3-enforce-thresholds ...` 已 `7/7` 全成功
- 关键指标：`matched=20/22`、`coverage=90.91%`、`mae=0.9443%`、`pass=True`

### I. 信号端前置风控闭环（已完成）
1. `scripts/daily_ml_select.py` 新增前置风控联动：
- 复用 `core/risk/pretrade.py`（与 P2 同一套硬门禁逻辑）
- 新增环境变量开关：
  - `MFTS_SIGNAL_PRETRADE_GATE`（默认开启）
  - `MFTS_SIGNAL_PRETRADE_USE_NEXT_TRADE_DAY`（当前默认关闭；开启后仅用于 P2 对齐或事后执行诊断，避免研究路径泄露下一交易日可交易状态）
  - `MFTS_SIGNAL_PRETRADE_STRICT`（默认关闭；开启后不足 TopN 直接失败）
  - `MFTS_SIGNAL_PRETRADE_POOL_N`（默认 `0`，由 `top_n/pool_mult` 动态决定）
2. `scripts/daily_all.py` Step3(ML) 已自动透传 P2 风控参数：
- `MFTS_RISK_MAX_INDUSTRY_WEIGHT`
- `MFTS_RISK_MAX_ADV_PARTICIPATION`
- `MFTS_RISK_MIN_PRICE`
- `MFTS_RISK_MAX_STYLE_*_EXPOSURE_ABS`
- `MFTS_RISK_STYLE_LB_SHORT/BETA`
3. 新增产物：
- `output/risk/signal_pretrade_gates_YYYYMMDD.csv`
- `output/risk/signal_pretrade_gates_latest.csv`
4. 验收结果（2026-04-14 实跑）：
- `daily_ml_select --date 20260413 --top 30`
- 前置风控统计：`stage=pretrade_gate_on`、`pool=120`、`kept=119`、`blocked=1(0.83%)`、`top_reason=min_price`
5. 新增回归测试：
- `tests/test_daily_ml_select_pretrade.py`（命中/兜底/strict）
- `tests/test_daily_all_orchestration.py` 扩展：校验 P2 风控阈值已透传到 ML
- 关键回归：`33 passed`

### J. 前置风控对齐诊断（已完成）
1. 新增脚本：`scripts/quant_signal_pretrade_alignment_report.py`
- 输入：`output/execution/<channel>_ledger.csv` + `output/risk/signal_pretrade_summary_*.json`
- 输出：
  - `output/risk/pretrade_alignment_<channel>_*.csv`
  - `output/risk/pretrade_alignment_summary_<channel>_*.json`
2. 修复跨节假日口径错位：
- `daily_ml_select.py` 新增前瞻窗口下限 `MFTS_SIGNAL_PRETRADE_FORWARD_BUFFER_DAYS`（默认 `10`）
- 解决“前置风控未拿到下一交易日，导致与P2 trade_date错位”的问题
3. 实测窗口（`20260401~20260410`, channel=`paper_pretrade_diag`）：
- 修复前：`mae_blocked_rate_pct=19.94%`
- 修复 trade_date 后：`13.04%`
- 参数完全对齐后：`12.56%`
 - 统一权重口径（ML评分）+ 分数舍入对齐后：`9.29%`
 - 新增同层指标：`mae_topn_blocked_rate_pct=12.14%`（TopN 对 TopN）
4. 当前残余差异主因：
- 高参与率日（`adv_participation`）仍偏高，属于“候选池口径(pool_n) vs 执行输入(top_n)”差异，非同层分母比较误差
5. 同版本重跑验收（channel=`paper_pretrade_diag_v2`）：
- 重新按当前版本重跑 ML 与 P2 后：
  - `mae_blocked_rate_pct=9.17%`
  - `mae_topn_blocked_rate_pct=0.00%`（TopN 层面前置风控与P2风控完全一致）
- 结论：剩余偏差主要集中在“pool筛选层 vs 执行输入层”的分母差异，不再是同层规则不一致

### K. pool层偏差压缩（已完成）
1. `daily_ml_select.py` 新增自适应 `pool_n` 机制：
- 默认 `pool_mult=1.0`、`pool_min_n=0`、`pool_step_n=10`、`pool_max_n=top_n*3`
- 新增 `MFTS_SIGNAL_PRETRADE_ALLOW_EXPAND`（默认 `false`）：默认不扩池，优先同层口径一致性；需要时可显式开启扩池
- 支持 `MFTS_SIGNAL_PRETRADE_POOL_N` 固定池大小
2. 同版本重跑验收（channel=`paper_pretrade_diag_v3`）：
- `mae_blocked_rate_pct=6.54%`（已达到 `<8%` 目标）
- `mae_topn_blocked_rate_pct=0.00%`（保持同层一致）
3. 关键产物：
- `output/risk/pretrade_alignment_summary_paper_pretrade_diag_v3_20260415_081008.json`
4. 最新验收（channel=`paper_pretrade_diag_v7`，P2 `top_n=30`）：
- `mae_blocked_rate_pct=1.11%`
- `mae_topn_blocked_rate_pct=1.43%`
- 关键产物：`output/risk/pretrade_alignment_summary_paper_pretrade_diag_v7_20260415_120348.json`

### L. style阈值网格回放（已完成）
1. 执行：
- `scripts/quant_p2_rolling_replay.py`
- profile=`right_h8_low_turnover`，window=`7`，style 4维网格 + lookback 网格
- 本轮全量组合：`162`（非经验拍脑袋）
2. 最优组合（objective）：
- `size=1.1`、`beta=1.1`、`momentum=1.2`、`vol=1.3`、`lb_short=20`、`lb_beta=60`
- channel：`paper_replay_right_h8_low_turnover_7_g155_20260415_082956`
3. 关键结果：
- `ret=0.2084%`、`mdd=-0.8365%`、`risk_block_rate=26.67%`、`style_hit_rate=11.67%`
4. 参数回灌：
- `config/quant_live_profiles.json` 的 `right_h8_low_turnover` 风格阈值已更新为 `1.1/1.1/1.2/1.3`
5. 产物：
- `output/backtest/p2_rolling_replay_summary_20260415_082956.csv`
- `output/backtest/p2_rolling_replay_meta_20260415_082956.json`

### M. style分层归因 + 逐笔一致性回放（已完成）
1. 执行：
- `scripts/quant_exec_consistency_report.py`
- broker/channel：`paper_replay_right_h8_low_turnover_7_g155_20260415_082956`
- 输出已包含：
  - style 分层归因
  - 逐笔（订单级）一致性回放
2. 关键诊断（窗口内匹配样本）：
- `ret_gap_mae_pct=1.0093%`
- `risk_block_rate_mean_pct=3.33%`
- `style_hit_vs_abs_gap corr=-0.403`（样本内“style命中更高并未放大偏差”）
- 逐笔阻塞主因：`entry_not_tradable`
3. 产物：
- `output/risk/exec_consistency_style_attribution_paper_replay_right_h8_low_turnover_7_g155_20260415_082956_20260415_115621.csv`
- `output/risk/exec_tick_replay_paper_replay_right_h8_low_turnover_7_g155_20260415_082956_20260415_115621.csv`
- `output/risk/exec_tick_replay_layer_paper_replay_right_h8_low_turnover_7_g155_20260415_082956_20260415_115621.csv`

## 0. 最新策略收敛结果（2026-04-10）

### 严格门槛优化（已复跑验证）
1. 复跑参数网格（`engine-mode=right`）：
- `top_n=6,8,10`
- `holding_days=8`
- `max_single_pos=0.03,0.04`
- `use_regime_position=on/off`（共 12 组）
2. 硬门槛通过：`6/12`
- 通过组合集中在 `TopN=6/8`
- 主要失效原因为 `excess_annual` 与 `sharpe`（主要出现在 `TopN=10`）

### 当前推荐参数（rank=1）
1. 参数：
- `top_n=8`
- `holding_days=8`
- `max_single_pos=0.04`
- `use_regime_position=True`
2. 指标：
- `annual_return_pct=24.16`
- `excess_annual_return_pct=9.22`
- `max_drawdown_pct=-10.69`
- `sharpe=1.54`
- `annual_turnover_pct=3388.23`
- `oos_excess_total_median=1.79`
- `oos_mdd_worst=-7.78`
- `oos_pass_rate=0.75`

### 低换手策略版本（本轮新增）
1. 目标：
- 在不显著破坏 OOS 稳健性的前提下，把年化换手从 `~3388%` 压到 `~3000%`
2. 做法：
- 保持 `Hold=8`
- 使用 `engine_mode=right`
- 放宽分市场动态退出参数：
  - `tp_normal/choppy/panic=0.25/0.20/0.15`
  - `sl_normal/choppy/panic=0.10/0.08/0.06`
  - `trail_normal/choppy/panic=0.14/0.12/0.10`
3. 收敛结果（低换手门槛版硬通过 `1/8`）：
- 推荐参数：`top_n=10`、`holding_days=8`、`max_single_pos=0.04`、`use_regime_position=False`
- 指标：`annual_return_pct=16.17`、`excess_annual_return_pct=-2.50`、`max_drawdown_pct=-9.87`、`sharpe=0.99`
- 稳健：`oos_excess_total_median=2.37`、`oos_mdd_worst=-9.91`、`oos_pass_rate=0.75`
- 换手：`annual_turnover_pct=3009.85`
4. 一键 profile：
- `config/quant_live_profiles.json` 新增 `right_h8_low_turnover`

### 20交易日双档执行回放（本轮新增）
1. 对比对象：
- `alpha_high`：`top_n=8`、`max_single_pos=0.04`（沿用信号仓位）
- `low_turnover`：`top_n=10`、`max_single_pos=0.04`、`target_total_pos=0.60`
2. 样本区间：
- 最近 20 个信号日（`output/daily/daily_*.csv`）
- 有效运行日：`17`（`20260319/20260320/20260409` 因空信号或无下一交易日被跳过）
3. 有效样本汇总（P2纸面执行口径）：
- `alpha_high`：`nav_return=-1.9500%`、`exec_block_rate=29.41%`、`risk_block_rate=38.46%`
- `low_turnover`：`nav_return=-0.9422%`、`exec_block_rate=28.66%`、`risk_block_rate=40.74%`
4. 结论：
- 低换手档在该样本下净值回撤更小（相对提升约 `+1.0078pct`）
- 执行阻塞率略优（`-0.75pct`），但风控拦截率略高（`+2.28pct`）
5. 产物：
- `output/risk/p2_profile_compare_runs_latest.csv`
- `output/risk/p2_profile_compare_summary_latest.csv`
- `output/risk/p2_profile_compare_summary_valid_latest.csv`
- `output/risk/p2_profile_compare_report_latest.md`

### 40交易日回放 + 风控网格（本轮新增）
1. 双档回放（最近 40 个信号日）：
- `alpha_high`：`runs_valid=36`、`runs_invalid=4`（`20260212/20260319/20260320/20260409`）
- `low_turnover`：`runs_valid=37`、`runs_invalid=3`（`20260319/20260320/20260409`）
2. 40日有效样本汇总（P2 纸面执行口径）：
- `alpha_high`：`nav_return=-3.2224%`、`exec_block_rate=17.53%`、`risk_block_rate=30.03%`
- `low_turnover`：`nav_return=-2.4882%`、`exec_block_rate=17.60%`、`risk_block_rate=32.94%`
3. 风控参数网格（针对 `low_turnover`，40日）：
- 备选：
  - `base_35_05_20`：`industry=0.35`、`adv=0.05`、`min_price=2.0`
  - `ind40_05_20`：`industry=0.40`、`adv=0.05`、`min_price=2.0`
  - `base_35_06_20`：`industry=0.35`、`adv=0.06`、`min_price=2.0`
  - `ind40_06_20`：`industry=0.40`、`adv=0.06`、`min_price=2.0`
- 最优：`base_35_06_20`（与 `ind40_06_20` 指标等效，优先保守行业上限）
- 相对基线（`base_35_05_20`）改进：
  - `nav_return`：`+1.4137pct`（`-2.4882% -> -1.0745%`）
  - `exec_block_rate`：`-0.31pct`（`17.60% -> 17.29%`）
  - `risk_block_rate`：`-1.27pct`（`32.94% -> 31.67%`）
4. 结论：
- `right_h8_low_turnover` 在 40 日样本下更抗回撤，且 `adv=0.06` 显著改善净值与拦截率。
- 行业上限 `0.35 -> 0.40` 在当前样本无增益，维持 `0.35` 更稳健。
5. 产物：
- `output/risk/p2_profile_compare40_runs_latest.csv`
- `output/risk/p2_profile_compare40_summary_latest.csv`
- `output/risk/p2_risk_tune40_runs_latest.csv`
- `output/risk/p2_risk_tune40_summary_latest.csv`

### P2 执行链路验证（dry-run）
1. 命令：
- `python scripts/quant_p2_paper_trade.py --signal-file output/daily_mfts_20260320.csv --top-n 8 --max-single-pos 0.04 --default-total-pos 0.60 --broker paper --dry-run --write-latest`
2. 结果：
- `filled=6`
- `blocked=0`
- `risk_blocked=2`
- `nav=999535.96`
- `cash=642691.96`

### 线上运行稳定性修复（本轮新增）
1. 验证步骤“误失败”修复：
- `daily_all.py` 的验证目标筛选已按 `label_mode/label_horizon` 计算最小未来交易日要求。
- 解决 `open_to_open` 场景下“最新推荐日必然未来交易日不足”导致的红灯。
2. 验证脚本退出码修复：
- `daily_verify.py` 新增 `--strict`。
- 默认无可验证样本时按“跳过”返回成功；仅 strict 模式返回失败码。
3. 档位持有期一致性修复：
- `config/settings.py` 的 `resolve_default_label_horizon` 支持 `MFTS_ACTIVE_PROFILE`（并兼容 `MFTS_P2_PROFILE`）。
- 解决 ML 输出中的 `model_horizon != default_profile_horizon` 偏差告警。
4. P2 风控可交易性修复：
- `quant_p2_paper_trade.py` 已按 profile 默认值支持 `exclude_st`，默认过滤 `ST/*ST`。
5. 元数据行业恢复增强：
- `daily_incremental_update.py` 增加从批量 spot 字段提取行业映射能力（含东方财富 spot 回退）。
- 行业板块接口失败时，提高行业覆盖恢复概率。

## 1. 本轮已完成（Done）

### 策略优化冲刺包（已落地）
1. `scripts/quant_optimize.py` 升级：
- 多目标评分（收益/超额/Sharpe/胜率/回撤/换手，可配置权重）
- 硬门槛原因追踪（`constraint_fail_reasons`）
- 稳健模式门槛可配置（OOS 通过率/最差回撤/有效窗口比）
2. 新增推荐表：
- `output/backtest/quant_strategy_paper_recommendations.csv`
- `output/backtest/quant_strategy_paper_recommendations.json`
3. 价值：
- 能直接看到“为什么某组参数失效”
- 能直接给出可用于模拟盘的参数候选与命令

### A：信号层稳健化（本轮完成）
1. 新增共享模块：`utils/signal_quality.py`
- 基于同日特征（`bias/z_score/rsi/vol_ratio/pct_chg`）计算 `signal_quality`，避免未来信息泄露
- 支持 `hybrid_score = ML排序 + 质量分` 融合排序
2. 回测引擎接入：
- `scripts/quant_portfolio_backtest.py` 新增信号质量门禁与参数
- 新增参数：`--disable-signal-quality-gate`、`--min-signal-quality`、`--ml-quality-blend`、`--max-abs-pct-chg`
3. 选股脚本接入：
- `scripts/daily_ml_select.py` 接入质量分与综合分排序，输出新增列：`质量分`、`综合分`

### C：反过拟合流程固化（本轮完成）
1. 新增脚本：`scripts/quant_anti_overfit_pipeline.py`
- 先跑 Walk-Forward 粗网格
- 自动提取“稳定参数区”
- 在稳定区内跑 `quant_optimize --robust-mode on`
- 自动输出报告与模拟命令
2. 新增报告产物：
- `output/backtest/quant_anti_overfit_report_*.json`
- `output/backtest/quant_anti_overfit_report_*.md`
3. 修复关键兼容性问题：
- `scripts/quant_walk_forward.py` 已升级到新版 `_passes_hard_filters` 接口，避免流水线中断

### B：信号特征重构（Round2，本轮完成）
1. 新增共享模块：`utils/signal_refactor.py`
- 新增 `stability_score`（稳定性评分）
- 新增 `refactor_score`（综合分 + 稳定性融合）
- 新增 `feature_redundancy`（冗余度统计）
2. 回测引擎接入：
- `scripts/quant_portfolio_backtest.py` 已接入特征重构参数与门禁
- 新增参数：`--disable-feature-refactor`、`--stability-blend`、`--disable-feature-refactor-gate`、`--min-refactor-score`
3. 信号脚本接入：
- `scripts/daily_ml_select.py` 已支持重构排序（环境变量开关）
- 新增输出列：`稳定分`、`重构分`
4. 对比验证脚本：
- 新增 `scripts/quant_signal_refactor_compare.py`（baseline vs refactor）
- 已实测产出：`output/backtest/quant_signal_refactor_compare_*.{csv,json,md}`
5. 反过拟合链路参数打通：
- `scripts/quant_walk_forward.py` 与 `scripts/quant_optimize.py` 已接入重构参数
- `scripts/quant_anti_overfit_pipeline.py` 已支持一键透传：
  - `--min-signal-quality`、`--ml-quality-blend`、`--max-abs-pct-chg`
  - `--stability-blend`、`--min-refactor-score`

### P1：风险与归因（已落地）
1. 新增脚本：`scripts/quant_p1_analytics.py`
2. 能力新增：
- 风险暴露汇总（状态、仓位、集中度、参与率）
- 行业暴露汇总（权重分布与观测覆盖）
- 收益归因（按市场状态/退出原因/月份）
- 容量与成本评估（参与率约束、容量资金估算、回合成本）
3. 产物新增：
- `output/risk/risk_exposure_summary_*.csv`
- `output/risk/risk_exposure_industry_*.csv`
- `output/risk/return_attribution_*.csv`
- `output/risk/capacity_cost_*.csv`
- `output/risk/p1_analytics_summary_*.json`

### P2：纸面执行与审计（已落地）
1. 新增脚本：`scripts/quant_p2_paper_trade.py`
2. 能力新增：
- 读取推荐文件并构建目标仓位
- 下一交易日开盘模拟撮合（含手续费/滑点/印花税）
- A股可交易性约束（停牌/涨停买不到/跌停卖不出）
- 下单前风控硬门禁（行业/参与率/黑名单/最低价 + 风格暴露 Size/Beta/Momentum/Vol）
- 纸面账户状态持久化（现金、持仓、净值）
- 审计日志落地（可追溯每次再平衡）
3. 产物新增：
- `output/execution/paper_orders_*.csv`
- `output/execution/paper_fills_*.csv`
- `output/execution/paper_run_*.json`
- `output/execution/paper_ledger.csv`
- `output/execution/paper_portfolio_state.json`
- `output/audit/paper_audit_log.jsonl`

### 编排接入（已落地）
1. `scripts/daily_all.py` 新增可选步骤：
- `--with-p1`
- `--with-p2`
2. 新增参数：
- P1：`--p1-capital-base`、`--p1-adv-participation`
- P2：`--p2-initial-capital`、`--p2-top-n`、`--p2-max-single-pos`、`--p2-default-total-pos`、`--p2-state-file`、`--p2-dry-run`
- P2 风控透传：`--p2-risk-max-industry-weight`、`--p2-risk-max-adv-participation`、`--p2-risk-min-price`
- P2 风格风控透传：`--p2-risk-max-style-size-exposure-abs`、`--p2-risk-max-style-beta-exposure-abs`、`--p2-risk-max-style-momentum-exposure-abs`、`--p2-risk-max-style-vol-exposure-abs`、`--p2-risk-style-lb-short`、`--p2-risk-style-lb-beta`
- P2 推荐参数透传：`--p2-use-recommendation`、`--p2-recommend-rank`、`--p2-recommend-file`、`--p2-recommend-keep-signal-position`

### P3（本轮新增基础骨架）
1. 执行通道抽象：
- `core/execution/adapter.py`（`BrokerAdapter` / `RebalanceResult`）
- `core/execution/paper_broker.py`（`PaperBroker`）
- `core/execution/live_broker.py`（`LiveBroker`，支持 `shadow/gateway`）
- `core/execution/__init__.py`（`create_broker` 注册入口）
2. P2 脚本改造：
- `scripts/quant_p2_paper_trade.py` 新增 `--broker` / `--live-mode`，主流程改为通过 `BrokerAdapter` 调用
- 新增下单前风控硬门禁（行业上限、参与率、黑名单、最低价），输出 `*_risk_gates_*.csv`
3. 编排通道参数：
- `scripts/daily_all.py` 新增 `--p2-broker`（默认 `paper`）
4. 一致性报告：
- 新增 `scripts/quant_exec_consistency_report.py`（回测 vs 执行偏差拆解）
- `daily_all.py` 新增 `--with-p3-consistency`

### 测试覆盖（已补充）
1. `tests/test_p1_analytics.py`
2. `tests/test_p2_paper_trade.py`
3. `tests/test_daily_all_orchestration.py` 新增 P1/P2/P3 与推荐参数透传用例
4. `tests/test_p2_recommendation.py` 新增推荐参数读取与 rank 选择测试
5. `tests/test_signal_quality.py` 新增信号质量评分测试
6. `tests/test_quant_anti_overfit_pipeline.py` 新增反过拟合流水线核心逻辑测试
7. `tests/test_quant_walk_forward_filters.py` 新增 Walk-Forward 硬门槛接口回归测试
8. `tests/test_signal_refactor.py` 新增特征重构评分回归测试
9. `tests/test_quant_signal_refactor_compare.py` 新增 A/B 对比脚本辅助函数测试
10. `tests/test_quant_backtest_defaults.py` 新增特征重构 CLI 参数注入测试
11. `tests/test_quant_walk_forward_filters.py` 新增重构参数透传测试
12. `tests/test_quant_optimize_multiobjective.py` 新增重构参数透传测试
13. `tests/test_quant_anti_overfit_pipeline.py` 新增流水线命令透传测试
14. `tests/test_pretrade_risk.py` 新增风格暴露门禁回归测试
15. `tests/test_p2_rolling_replay.py` 新增 style 网格解析与 style 指标汇总测试
16. `tests/test_exec_consistency_report.py` 新增 style 分层归因与逐笔回放测试

## 2. 仍需推进（Next）

### 高优先级（近期必须）
1. 实盘网关“真实接入”
- 当前 `LiveBroker` 已有抽象与 shadow 通道，仍需对接真实券商/柜台 API。

2. 行业覆盖健康监控自动化
- 行业覆盖已恢复到 `91.89%`，下一步从“修复”转为“监控”：加入覆盖率日趋势、失败源（ak/em/sina）分项告警。

3. 风格门禁阈值校准自动化
- 已支持风格因子暴露约束（Size/Beta/Momentum/Vol）；下一步需用滚动窗口做阈值网格校准，避免“拍脑袋阈值”。

4. 逐笔一致性深挖
- 逐笔（订单级）回放已落地，下一步需继续下钻到“分票持仓路径级”与“成交价偏差模拟级”。

### 中优先级（平台可用性）
1. 审计日志可视化
- 在 Web 端增加最近执行 run 的订单状态、阻塞原因分布、账户净值变化。

2. 数据与风控告警
- 覆盖率异常、成交阻塞率过高、净值单日异常波动等自动告警。

3. 文档标准化
- 统一脚本 I/O 契约模板，避免不同脚本的字段命名漂移。

## 2. 最新执行层结论（2026-04-24）

### 已验证状态

- 当前项目级验证通过：`202 passed, 3 skipped`
- 最新执行层对比工件：
  - `output/backtest/quant_p2_shadow_diagnosis_latest.csv`
  - `output/backtest/quant_p2_shadow_diagnosis_latest.json`

### 三档 20 日 P2 shadow 对比

- `quality_regime_candidate`
  - `nav=-0.96%`
  - `mdd=-1.41%`
  - `adv_blocked_rows=17`
  - `mean_top_industry_weight=30.46%`
- `quality_regime_candidate_v2`
  - `nav=-1.05%`
  - `mdd=-1.40%`
  - `adv_blocked_rows=24`
  - `mean_top_industry_weight=37.82%`
- `quality_regime_candidate_v3`
  - `nav=-0.66%`
  - `mdd=-0.94%`
  - `adv_blocked_rows=15`
  - `mean_top_industry_weight=35.69%`

### 当前判断

- `quality_regime_candidate_v3` 已明显优于 `v2`，并且在执行后 NAV、回撤、ADV 拦截三个维度都优于原 `candidate`。
- 但 `v3` 的行业集中仍高于原 `candidate`，还不适合直接升档。
- 下一阶段不应回到盲调收益参数，而应继续压行业拥挤度与行业集中。

## 3. 推荐执行命令

```bash
# 日常主流程 + P1 + P2（建议先 dry-run）
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --p2-dry-run

# 日常主流程 + P1 + P2（自动套用优化推荐参数）
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --p2-broker paper --p2-dry-run --p2-use-recommendation --p2-recommend-rank 1

# 日常主流程 + P1 + P2（低换手档风控参数，40日网格最优）
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --p2-broker paper --p2-dry-run \
  --p2-risk-max-industry-weight 0.35 --p2-risk-max-adv-participation 0.06 --p2-risk-min-price 2.0 \
  --p2-risk-max-style-size-exposure-abs 1.1 --p2-risk-max-style-beta-exposure-abs 1.1 \
  --p2-risk-max-style-momentum-exposure-abs 1.2 --p2-risk-max-style-vol-exposure-abs 1.3 \
  --p2-risk-style-lb-short 20 --p2-risk-style-lb-beta 60

# 日常主流程 + P1 + P2 + P3
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --with-p3-consistency --p2-broker paper --p3-broker paper --p2-dry-run

# 日常主流程 + P3 阈值门禁（不达标直接失败）
python scripts/daily_all.py --mode latest --with-p1 --with-p2 --with-p3-consistency \
  --p2-broker paper --p3-broker paper --p2-dry-run \
  --p3-max-ret-gap-mae-pct 2.0 --p3-min-match-coverage-pct 60 \
  --p3-max-order-block-rate-pct 35 --p3-max-risk-block-rate-pct 35 \
  --p3-min-matched-rows 20 --p3-rate-eval-rows 10 --p3-enforce-thresholds

# 行业门禁临时放行（仅排障时用）
python scripts/daily_all.py --mode latest --with-p2 --with-p3-consistency --disable-industry-coverage-gate

# 元数据行业覆盖手动刷新（排障/验收）
python -c "import scripts.daily_incremental_update as m; m.refresh_stock_metadata()"

# 日常主流程（推荐：策略档位对齐 + 验证非严格）
MFTS_P2_PROFILE=right_h8_low_turnover python scripts/daily_all.py \
  --mode latest --with-p1 --with-p2 --with-p3-consistency \
  --p2-broker paper --p3-broker paper --p2-dry-run \
  --p2-risk-max-industry-weight 0.35 --p2-risk-max-adv-participation 0.06 --p2-risk-min-price 2.0 \
  --p2-risk-max-style-size-exposure-abs 1.1 --p2-risk-max-style-beta-exposure-abs 1.1 \
  --p2-risk-max-style-momentum-exposure-abs 1.2 --p2-risk-max-style-vol-exposure-abs 1.3 \
  --p2-risk-style-lb-short 20 --p2-risk-style-lb-beta 60

# 单独跑 P1
python scripts/quant_p1_analytics.py --write-latest

# 单独跑“严格门槛优化”（本轮收敛命令）
python scripts/quant_optimize.py --start 2025-01-01 --end 2026-03-20 \
  --topn-grid 6,8,10 --hold-grid 8 --maxpos-grid 0.03,0.04 \
  --engine-mode right --benchmark-mode hs300 --robust-mode on \
  --min-annual-return-pct 0 --min-excess-annual-pct 0 --min-sharpe 0.7 \
  --max-drawdown-limit-pct -12 --turnover-cap-pct 3500 \
  --min-oos-excess-total-median 1.0 --min-oos-mdd-worst -8.0 \
  --min-oos-pass-rate 0.75 --min-oos-valid-window-ratio 1.0 --oos-min-windows 3 \
  --min-signal-quality 0.40 --ml-quality-blend 0.80 --max-abs-pct-chg 8.5 \
  --stability-blend 0.30 --min-refactor-score 0.50

# 单独跑 P2（纸面OMS，按本轮推荐参数复现）
python scripts/quant_p2_paper_trade.py --signal-file output/daily_mfts_20260320.csv --top-n 8 --max-single-pos 0.04 --default-total-pos 0.60 --broker paper --dry-run --write-latest

# 单独跑 P2（从推荐表自动读取 rank=1）
python scripts/quant_p2_paper_trade.py --signal-file output/daily_mfts_20260320.csv --use-recommendation --recommend-rank 1 --broker paper --dry-run --write-latest

# 单独跑 P2（低换手档 + 40日网格最优风控）
MFTS_P2_PROFILE=right_h8_low_turnover python scripts/quant_p2_paper_trade.py \
  --signal-file output/daily_mfts_20260320.csv --broker paper \
  --top-n 10 --max-single-pos 0.04 --target-total-pos 0.60 \
  --risk-max-industry-weight 0.35 --risk-max-adv-participation 0.06 --risk-min-price 2.0 \
  --risk-max-style-size-exposure-abs 1.1 --risk-max-style-beta-exposure-abs 1.1 \
  --risk-max-style-momentum-exposure-abs 1.2 --risk-max-style-vol-exposure-abs 1.3 \
  --risk-style-lb-short 20 --risk-style-lb-beta 60 \
  --dry-run --write-latest

# 单独跑 P3（一致性偏差）
python scripts/quant_exec_consistency_report.py --broker paper --write-latest

# 单独跑 P3（一致性门禁强制）
python scripts/quant_exec_consistency_report.py --broker paper --rate-eval-rows 10 --write-latest --enforce-thresholds

# 单独跑 P3（自动输出 style_hit 分层归因 + 逐笔一致性回放）
python scripts/quant_exec_consistency_report.py --broker paper --rate-eval-rows 10 --write-latest

# P2 style 阈值网格回放（避免拍脑袋阈值）
python scripts/quant_p2_rolling_replay.py \
  --profiles right_h8_low_turnover --windows 7 --broker paper \
  --risk-max-industry-weight 0.35 --risk-max-adv-participation 0.06 --risk-min-price 2.0 \
  --style-size-grid 0.7,0.9,1.1 --style-beta-grid 0.7,0.9,1.1 \
  --style-momentum-grid 1.0,1.2,1.4 --style-vol-grid 0.9,1.1,1.3 \
  --style-lb-short-grid 20 --style-lb-beta-grid 60 \
  --write-latest

# P2 多窗口滚动回放（隔离 channel，不污染主 paper 账本）
python scripts/quant_p2_rolling_replay.py --profiles right_h8_low_turnover --windows 60,90,120 --broker paper --write-latest

# A+C 路径：反过拟合两阶段流水线
python scripts/quant_anti_overfit_pipeline.py --start 2025-01-01 --end 2026-03-20

# B 路径：特征重构 A/B 对比
python scripts/quant_signal_refactor_compare.py --start 2026-01-01 --end 2026-03-20 --top-n 10 --holding-days 6 --engine-mode hybrid --benchmark-mode hs300 --stability-blend 0.20 --min-refactor-score 0.45
```
