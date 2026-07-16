# Error Memory

Record recurring mistakes and failure modes. Keep this practical: symptom, cause, mitigation, and evidence.

## Error Log

### 2026-07-16 | 删除旧数据后仍需防止代码文本回流为生产依赖
- tags: ods, legacy, retirement, regression
- status: active
- severity: high
- mitigation: 保持 `tests/test_legacy_data_retirement.py`，同时约束本地旧数据文件不存在和所有
  `daily_all_5y` / `stock_info` 路径文本只能出现在登记的退役历史/修复文件中。任何新生产、
  P2、promotion、raw-model 或 Web 入口命中该路径都应使测试失败。
- evidence: 旧行情已删除后，静态审计仍发现历史/修复脚本包含路径文本；将它们显式列入退役
  集合并对集合做精确相等断言，避免“扫描无结果”误把历史代码删失或遗漏新回退。


### 2026-07-16 | 默认 ODS 不等于旧数据已经退出证据链
- tags: ods, legacy, raw_model, evidence_lineage
- status: active
- severity: critical
- mitigation: 禁止 raw-model、P2、promotion 和日常入口保留可执行的 legacy market-file fallback；
  保留历史 artifact 读取不代表允许重新读取旧行情。对可执行入口做静态路径扫描，并用真实 ODS
  health 与全量测试验证。
- evidence: raw-model walk-forward 虽默认 `ashare_ods`，但仍公开 `--data-source legacy` 与旧
  `daily_all_5y` 默认路径。移除该模式并令缓存仅绑定 ODS snapshot digest 后，模型层
  walk-forward/instability/state-migration 测试通过。


### 2026-07-16 | 稀疏 trading_calendar 会吞掉有效历史交易日
- tags: ods, calendar, replay, evidence_lineage
- status: active
- severity: critical
- mitigation: ODS gateway 必须先检查请求区间内 calendar 对 daily-bars session 的覆盖是否完整；不完整时以 `daily_bars` 分区日期作为历史 replay 会话，并在 lineage 中保留该选择。
- evidence: 初版 gateway 用全局稀疏 calendar 过滤时，2026-04-01..2026-04-14 的 20-session warmup 没有展开。检查发现 daily_bars 在 2026-03..04 连续，而 trading_calendar 在该区间没有对应分区。覆盖感知回退后，窗口正确扩展为 2026-03-04..2026-04-15。

不要把供应商日历快照存在理解为完整 PIT 交易日历；会话缺口会直接破坏技术指标、标签和 P2 next-trade-day 语义。

### 2026-07-16 | ODS date-bound loading can erase long-window features and forward labels
- tags: data_source, ods, raw_model, lookback, labels
- status: active
- severity: critical
- mitigation: For raw-model diagnostics, expand ODS reads by at least 252 preceding trading sessions and `max(horizon)+1` following sessions before calculating indicators and open-to-open labels; only then clip to the requested evidence interval.
- evidence: The initial ODS bridge loaded only `2026-04-01..2026-04-14`, yielding zero valid `pos_52w` and `label_h10` rows. Trading-session expansion restored `44,184` valid `pos_52w` rows and `46,503` valid H=10 labels.

Column compatibility is insufficient. Long-window features and forward labels require explicit source-window lineage.

### 2026-07-16 | ODS cache keys can go stale when latest snapshots are backfilled
- tags: data_source, ods, cache, snapshot, evidence_lineage
- status: active
- severity: high
- mitigation: Bind any ODS feature cache to the actual selected partition snapshots over its expanded source window. For raw-model walk-forward, store a digest of `daily_bars` `(trade_date, snapshot)` pairs and invalidate cache on any digest change.
- evidence: The loader chooses latest snapshot per trade date. Before the fix, cache identity had only the root path, policy, features, and requested dates, so a later historical snapshot could change source data without changing an auto-cache key. A focused regression now proves a new same-day snapshot changes the request digest.

An ODS root is not a data version. Treat selected snapshots as part of every reproducible research artifact.

### 2026-07-16 | Legacy OHLC slices can contain date-level duplicated bars
- tags: data_quality, legacy_data, ods, raw_model
- status: active
- severity: high
- mitigation: Before declaring ODS/legacy model divergence, run date-level OHLC overlap checks. Preserve source identity in feature caches and artifacts, and do not treat old legacy artifacts as a clean control when a date slice is corrupted.
- evidence: On `2026-04-03`, `5,157 / 5,181` shared codes had divergent closes; legacy repeated the prior day's OHLC for affected names, while ODS contained the distinct current-day bar. Other nearby days were near-identical.

Raw-model differences can be data repairs rather than model changes. Do not merge or directly rank cross-source evidence without a documented data-quality comparison.

### 2026-04-27 | P2 reserve re-optimization can silently overrun upstream target weights
- tags: p2, target_weight, reserve_pool, promotion
- status: active
- severity: critical
- mitigation: When a daily signal file carries positive `target_weight`, derive P2 `total_target` and `max_single` from the upstream weights before any pretrade/reserve re-optimization. Rolling replay must report `upstream_target_weight_overrun_max`, and promotion must hard-fail positive overrun.
- evidence: v16 profile daily for `2026-04-02` correctly capped upstream target weight to `18%`, but P2 initially re-optimized the next trade day back to about `38.6%` because it dropped target-weight columns before pretrade. After the fix, 2026-04-03 P2 target stayed at `18%`, 2026-04-07 trapped sell weight fell from about `35.7%` to `14.4%`, and `upstream_target_weight_overrun_max=0`.

Do not interpret profile guard failures until target-budget lineage is proven. A reserve pool may replace blocked names, but it must not expand the upstream portfolio budget.

### 2026-04-28 | Score-alpha pass can hide profile daily coverage gaps
- tags: score_gate, p2, coverage, promotion
- status: active
- severity: high
- mitigation: Before long-window P2 or promotion review, require profile-isolated daily signal coverage to be comparable to the requested evidence window. Use `quant_refresh_promotion_gate.py --precheck-signal-coverage`; a candidate with only 10-20 signal days must not be described as 60-day evidence even when replay uses `window=60`.
- evidence: The 2026-04-28 survivor smoke kept v14/v15/v17/v22 after score-alpha precheck, but P2 reported only 10 signal days for v14/v15 and 20 signal days for v17/v22, while main profile had 60 shared signal days. The new signal-coverage precheck later rejected those survivors before P2 spend: v14/v15 `10/60`, v17/v22 `20/60`, leaving only `quality_regime`.

Score-alpha can be valid on the rows it sees but still be too sparse for promotion evidence. Coverage is a separate hard condition.

### 2026-04-27 | Do not convert full-universe risk correlation directly into profile promotion logic
- tags: v15, sell_trap, feature_study, promotion
- status: active
- severity: high
- mitigation: Treat full-universe feature correlation as hypothesis generation only. Require profile-isolated P2 smoke, blocked-sell lineage, predictor recall, and NAV/MDD parity before accepting a new risk score.
- evidence: `vol_ratio_low_risk` had strong full-universe future exit-block correlation, but v15 P2 smoke worsened NAV/MDD and broker exit-not-tradable orders versus v13/v14.

A feature can be statistically related to future sell traps and still fail as a portfolio control when traps come from holding-state, gap risk, or market-wide liquidity shocks.

### 2026-04-27 | Do not trust unvalidated exit-trap risk scores
- tags: sell_trap, predictor, v14, p2
- status: active
- severity: high
- mitigation: Run sell-trap predictor validation before using entry-time risk scores as hard promotion or portfolio logic. Require blocked sells to show higher predicted risk than filled sells across larger samples.
- evidence: v14 10-day sell-trap predictor diagnosis found blocked sell entry exit-trap risk mean `0.127` vs filled sell mean `0.172`, high-risk recall `0%`, and `predictor_direction_ok=False`.

A simple near-limit-down or low-volume score can be anti-predictive. Hard-capping it may improve optics while missing the actual sell-trap mechanism.

### 2026-04-27 | Do not optimize ADV from unnormalized amount/volume data
- tags: data_quality, adv, capacity, p2
- status: active
- severity: critical
- mitigation: Use `utils.market_data_units.normalize_amount_volume_units` through approved loaders before computing ADV, capacity, P2 fills, or promotion evidence. Rerun old ADV-heavy artifacts before citing them.
- evidence: Unit-normalized v9 replay changed executable_pool_halt_days from `10/10/10` to `0/0/0` and ADV halt hits to zero, while NAV worsened under higher exposure.

Mixed date-level amount/volume units can manufacture a fake capacity crisis. This can send optimization toward the wrong problem and make reserve/capacity changes look better or worse for the wrong reason.

### 2026-04-27 | Better target-weight utilization can reveal worse strategy quality
- tags: v9, target_weight, alpha, promotion
- status: active
- severity: high
- mitigation: Promotion must require NAV/MDD parity and sell-trap hard gates after unit-normalized P2 replay; do not reward candidates merely because target-weight utilization improved.
- evidence: Unit-normalized v9 target_weight_sum_mean rose to about `38.5%/38.6%/38.8%`, but 60/90/120 NAV remained negative and promotion review `20260427_153053` rejected v9 for tradability and sell-trap hard gates.

Cash shortfall fixes are not alpha fixes. When exposure increases and NAV gets worse, the next task is alpha/execution risk quality, not looser risk caps.

### 2026-04-27 | Reserve-cap improvements can be cash-drag disguised as execution repair
- tags: v13, reserve_pool, cash_drag, promotion
- status: active
- severity: high
- mitigation: Compare reserve-cap candidates on target-weight floors and NAV/MDD parity, not only lower blocked sells or lower drawdown; keep reserve-sourced sell traps as explicit promotion hard evidence.
- evidence: v13 10-day smoke reduced v12 broker exit-not-tradable orders `44 -> 22` and reserve-entry blocked sell orders `36 -> 15`, but target_weight_sum_mean also dropped `11.60% -> 8.54%` and executable_pool_halt_days stayed at `4`.

Do not claim a reserve-cap profile is better alpha just because trapped exposure and losses fall. If effective exposure collapses, the improvement may be mostly not trading.

### 2026-04-27 | Upstream tradability-safe ranking cannot cure existing trapped exits
- tags: v12, sell_trap, blocked_orders, p2
- status: active
- severity: high
- mitigation: Treat tradability-safe candidate scoring as entry-risk reduction only; pair it with exit-risk policy, trapped-position sizing, and sell-trap unwind logic before expecting P2 NAV improvement.
- evidence: v12 10-day P2 smoke still labeled 2026-04-03 signal / 2026-04-07 trade as `sell_trap`, with 34 blocked sell orders and roughly 33.94% current weight trapped, despite profile-isolated daily files and tradability-safe ranking.

Do not keep adding reserve/ranking penalties when the binding constraint is an already-held position that cannot exit.

### 2026-04-27 | Sell-trap clusters can be hidden by aggregate window metrics
- tags: sell_trap, promotion, p2, a_share
- status: active
- severity: critical
- mitigation: Promotion review must consume halt-cluster attribution and hard-fail severe sell-trap days, not only aggregate blocked order totals.
- evidence: v11 review added `halt_cluster_sell_trap_worse_than_main` and `halt_cluster_severe_sell_trap_failed` for v9 after merging halt attribution; v9 had severe 2026-04-07 style trapped sell exposure despite some windows passing NAV/MDD parity.

Do not rely only on 60/90/120 aggregate NAV and MDD when A-share sell traps cluster on specific trade dates.

### 2026-04-27 | Empty-signal accounting can improve coverage metrics without improving execution alpha
- tags: empty_signal, p2, promotion, alpha
- status: active
- severity: high
- mitigation: After reclassifying no-signal days, rerun long-window P2 and promotion gates before interpreting any profile improvement.
- evidence: v10 converted `quality_regime` 2026-03-19 and 2026-03-20 from replay failures into `empty_after_universe_filter`; formal review still kept v9 in shadow because it failed target-weight, broker tradability, executable-pool halt, and ADV hard gates.

Do not confuse cleaner evidence accounting with strategy improvement. Empty-signal repair removes false P2 failures; it does not create executable alpha or reduce sell traps.

### 2026-04-27 | BJ-only shared daily files can masquerade as repeated P2 failures
- tags: daily_signal, p2, quality_regime, promotion
- status: active
- severity: high
- mitigation: Promotion refresh should classify raw empty files and post-universe empty files as explicit no-signal ledger states with separate coverage metrics.
- evidence: v10 inspection showed `output/daily/daily_20260319.csv` and `daily_20260320.csv` each had 10 raw rows, all `920xxx`; with default BJ/9-code exclusion they became `empty_after_universe_filter`, not physical empty files.

Do not mix BJ-only/empty-after-universe-filter days with executable-pool halt or broker tradability blocks. They are an upstream signal/universe coverage gap and should be audited separately.

### 2026-04-27 | Empty-signal cleanup can expose upstream coverage gaps
- tags: empty_signal, universe_filter, p2, promotion
- status: active
- severity: high
- mitigation: Track `empty_signal_raw`, `empty_after_universe_filter`, `executable_pool_halt`, and broker tradability blocks as separate promotion evidence.
- evidence: v10 quality_regime 20-day in-process replay returned `run_failed_days=0`, but reported `empty_signal_days=2`, `empty_after_universe_filter_days=2`, `empty_signal_rate_pct=10.0`, and `empty_signal_filtered_bj9_rows_sum=20`.

Fixing the P2 failure code is not an alpha improvement. A high empty-signal rate should block candidate promotion and trigger upstream daily/universe diagnostics.

### 2026-04-27 | Zero failed replay days can hide no-entry risk-off behavior
- tags: p2, executable_pool_halt, target_weight, promotion
- status: active
- severity: high
- mitigation: Promotion and shadow diagnosis must report executable-pool halt days, halt rates, halt reasons, and target-weight floors alongside run-success coverage.
- evidence: v9 no-entry replay changed pretrade-empty days from failed runs into explicit risk-off ledger days. 60/90/120 run failures became `0/0/0`, but executable_pool_halt_days were still `10/10/10`, target_weight_sum_mean fell to `25.1%/29.7%/32.1%`, and 90/120 NAV stayed negative.

Do not treat replay coverage cleanup as alpha. A candidate that succeeds operationally by refusing to enter positions still has to pass effective exposure, NAV/MDD, ADV, and halt-rate gates.

### 2026-04-27 | Replay endpoint dates can masquerade as execution failures
- tags: p2, replay, calendar, promotion
- status: active
- severity: medium
- mitigation: Filter signal dates that do not have a next market trade day before selecting 20/60/90/120 replay windows; record excluded dates in replay metadata.
- evidence: v9 60/90/120 replay initially reported one extra failed day in every window because `2026-04-14` was the last available market date and had no next trade day. After filtering the endpoint, v9 failures dropped from `11` to `10` true pretrade-empty days.

Do not let local data coverage endpoints pollute execution coverage or promotion evidence. A skipped tail date is not the same failure mode as ADV, tradability, or pretrade-empty collapse.

### 2026-04-27 | Entry-not-tradable can disappear from broker orders because pretrade catches it first
- tags: entry_not_tradable, pretrade, p2, evidence
- status: active
- severity: high
- mitigation: When diagnosing buy-side tradability, combine pretrade risk hits, failed-day logs, broker orders, and ledger summaries; do not rely only on broker `entry_not_tradable_orders`.
- evidence: v9 60/90/120 no-entry replay had broker `entry_not_tradable_orders = 0`, but executable-pool halt diagnostics still found `8` entry-not-tradable hits in the halted pool of each window, plus `472` ADV hits and `275` style hits.

If pretrade correctly blocks unbuyable candidates, the broker order ledger may show no entry-not-tradable orders. Treat that as earlier interception, not absence of buy-side tradability risk.

### 2026-04-27 | Blocked sells can create false buying power if not stateful
- tags: blocked_orders, p2, cash, a_share
- status: active
- severity: critical
- mitigation: Track active blocked orders in `PaperBroker` and freeze new buys when blocked sell exposure exceeds the configured threshold.
- evidence: v9 added `blocked_order_state`, `blocked_sell_current_weight`, `blocked_exit_buy_freeze`, and rolling replay summaries after v8 showed late-March/early-April `exit_not_tradable` clusters.

A-share sell failures are not just missing fills; they leave trapped risk in the book. Do not allow reserve replacement or new buys to spend risk budget as if a blocked sell had completed.

### 2026-04-27 | Capacity-safe reserves do not help when the executable pool collapses
- tags: v9, reserve_pool, tradability, p2
- status: active
- severity: high
- mitigation: Treat reserve pools as replacement capacity, not a guarantee of fills; add blocked-cluster diagnostics and avoid promotion unless replay shows actual fills and NAV/MDD parity.
- evidence: v9 smoke for `2026-03-30` and `2026-04-07` used profile-isolated 40% target files and v9 P2 profile settings, but all kept buy orders were blocked as `entry_not_tradable` and NAV stayed flat.

When the whole candidate slice is blocked by A-share tradability, better reserve ordering only improves observability. It does not create executable alpha.

### 2026-04-27 | Shared daily fallback contaminates profile replay evidence
- tags: p2, profile, replay, evidence
- status: active
- severity: critical
- mitigation: When profile-specific daily files exist, use that profile's signal calendar and do not select dates from shared `output/daily`.
- evidence: A v8 replay started with profile files but fell back to shared files for missing dates; it was stopped and `quant_p2_rolling_replay.py` was changed to prefer profile calendars.

Do not mix shared daily recommendations into candidate replay. It makes target-weight, reserve-pool, and promotion evidence profile-inconsistent.

### 2026-04-27 | Reserve pool can raise exposure while worsening realized losses
- tags: v8, reserve_pool, alpha, p2
- status: active
- severity: high
- mitigation: Treat target-weight utilization as necessary but not sufficient; require NAV/MDD parity, ADV/tradability block control, and alpha attribution before promotion.
- evidence: v8 target_weight_sum_mean improved to 34.3%/36.1%/37.2% across 60/90/120 P2, but NAV fell -5.33%/-11.74%/-16.09%.

Solving cash drag can expose weak alpha. Do not interpret higher invested weight as a strategy improvement unless post-execution return quality also improves.

### 2026-04-26 | Expanding candidate count without primary-topN semantics creates micro-position drift
- tags: reserve_pool, optimizer, target_weight
- status: active
- severity: high
- mitigation: Use `max_names` so the first topN receives initial score weights and reserve candidates start at zero, becoming active only through clip redistribution or pretrade replacement.
- evidence: v8 reserve-pool implementation added `PortfolioConstraints.max_names` and pretrade `max_names`.

Do not simply pass 4x candidates into score weighting; that turns reserve candidates into tiny active positions and hides the actual cash/replacement problem.

### 2026-04-26 | Promotion can pass strict gates over inconsistent target-weight evidence
- tags: promotion, checksum, target_weight
- status: active
- severity: critical
- mitigation: Require P2 summaries to report external target-weight source rate and checksum coverage, and hard-fail candidates below 100%.
- evidence: Expert review emphasized that strict promotion logic is insufficient if daily, optimizer, and P2 requested weights are not provably the same evidence chain.

Do not accept a candidate whose execution artifacts cannot prove target-weight lineage.

### 2026-04-26 | P2 replay can become invalid if a script-level rebalance path recomputes target weights
- tags: p2, target_weight, promotion
- status: active
- severity: critical
- mitigation: Use `core.execution.paper_broker.PaperBroker` as the canonical rebalance path and require tests proving external `target_weight` is preserved.
- evidence: External expert review found that legacy `_rebalance` code in `scripts/quant_p2_paper_trade.py` could overwrite optimizer weights and double-apply total position.

Rolling replay and promotion gates become unreliable if P2 requested weights are not the same weights produced by the portfolio layer.

### 2026-04-26 | Next-day pretrade gates can leak execution outcomes into research selection
- tags: lookahead, pretrade, research_safe
- status: active
- severity: critical
- mitigation: Default daily selection to signal-day pretrade checks; require explicit opt-in for next-trade-day replay diagnostics.
- evidence: External expert review flagged `MFTS_SIGNAL_PRETRADE_USE_NEXT_TRADE_DAY` default behavior and forward buffers as a possible ex-post tradability leak.

A-share next-day buy/sell availability must be modeled as execution outcome unless explicitly labeled as replay evidence.

### 2026-04-26 | Low-invested candidates can look safer than they are
- tags: promotion, target_weight, cash_drag
- status: active
- severity: high
- mitigation: Require `target_weight_sum_mean` floors and compare NAV/MDD against the main profile across 60/90/120 P2 windows.
- evidence: v7 60/90-day target weight means were 21.03% and 27.03%, below promotion floors.

Lower drawdown from high cash is not a valid improvement unless NAV parity and effective exposure both pass.

### 2026-04-26 | Industry ranking penalties alone do not guarantee portfolio-level diversification
- tags: industry, optimizer, execution
- status: active
- severity: medium
- mitigation: Keep industry crowding light in ranking and enforce hard caps in portfolio/pretrade, including post-trade holdings.
- evidence: v3/v6/v7 evolution showed ranking penalties can improve one metric while leaving concentration or cash shortfall elsewhere.

Ranking should prioritize candidate quality; final portfolio constraints must live in the portfolio and pretrade layers.

### 2026-04-26 | Research strong, execution weak is often a capacity/portfolio issue, not just a signal issue
- tags: p2, capacity, turnover
- status: active
- severity: high
- mitigation: Diagnose ADV blocked rows, target weight utilization, order blocked rate, and industry concentration before changing alpha parameters.
- evidence: v6/v7 reduced some execution friction but still failed promotion gates.

Avoid blindly tuning signal blends when the bottleneck is execution pass-through.

### 2026-04-27 | Explicit zero target-weight files can be accidentally re-expanded
- tags: p2, target_weight, risk_off, holiday_gap
- status: fixed
- severity: critical
- mitigation: Treat the existence of a `target_weight` column as authoritative even if all values are zero. P2 should mark `target_weight_source=external_target_weight`, use zero target budget, and only attempt exits.
- evidence: While designing v17 pre-holiday risk-off behavior, the old `PaperBroker` path would only use external target weights when their sum was positive. An all-zero target-weight daily file could therefore fall back to score weights and create new buys.

A zero target budget is a valid portfolio instruction. Do not interpret it as "no external weights available."

### 2026-04-27 | Sell-trap reduction can be manufactured by excessive cash
- tags: v17, cash_drag, sell_trap, promotion
- status: active
- severity: high
- mitigation: Compare sell-trap improvements against target-weight floors and executable-pool halt days. Reject profiles that lower trapped exposure mainly by suppressing invested weight below promotion floors.
- evidence: v17 10/20-day smoke reduced max blocked-sell current weight to about `4.3%`, but average target weight fell to about `9.0%/5.8%` and executable-pool halt days rose to `2/8`.

Extreme holiday/exit-trap guards are useful diagnostics, not promotion-quality alpha, when they mostly turn the strategy into cash.

### 2026-04-27 | Missing volume with positive amount can manufacture false suspension clusters
- tags: data_quality, suspension, p2, sell_trap
- status: fixed
- severity: critical
- mitigation: In all tradability and suspension checks, accept either positive `amount` or positive `vol` as evidence that the stock traded, provided the execution price is valid. Missing `vol` alone must not create `entry_not_tradable`, `exit_not_tradable`, or sell-trap labels.
- evidence: v18 P2 initially showed late-March broker `entry_not_tradable` clusters and max blocked-sell current weight around `8.6%`. The affected bars had valid open prices and positive `amount` but missing `vol`; after the fix, broker entry blocks fell to zero and trapped sell weight fell to about `0.16%`.

Do not optimize profiles around blocked-order clusters until the market data fields used by suspension logic are validated. False non-execution can make NAV look better by preventing bad buys.

### 2026-04-27 | Failed profile daily rebuilds can leave stale signals in replay
- tags: daily_signal, profile_rebuild, replay, promotion
- status: fixed
- severity: critical
- mitigation: `quant_rebuild_profile_daily_signals.py --force` must delete the target profile daily file before generation and delete it again after failure. Rolling replay should report `profile_signal_days_available`, `signal_calendar_shortfall_days`, and `signal_calendar_coverage_pct`; promotion must reject candidate shortfall.
- evidence: A v18 121-day rebuild failed on five dates due to empty post-cleaning data. Without stale-output cleanup, old profile daily files could remain and make the replay calendar appear complete.

Profile replay evidence must never be assembled from stale files left by previous failed generations.

### 2026-04-27 | Calendar-complete replay is a hard evidence requirement
- tags: promotion, replay, signal_calendar
- status: active
- severity: high
- mitigation: Treat signal calendar shortfall as a separate evidence failure, not as NAV/MDD noise. Promotion hard gates must reject candidates with nonzero `p2_signal_calendar_shortfall_days_total` or positive `p2_signal_calendar_shortfall_days_max`.
- evidence: v18 replay now records requested window days, available profile signal days, shortfall days, and coverage percentage so 60/90/120 windows cannot silently run on fewer or stale signals.

A clean P2 result needs both successful broker execution and a complete, current signal calendar.

### 2026-04-27 | Do not compare fixed candidates against stale main evidence
- tags: promotion, baseline, p2, data_quality
- status: active
- severity: high
- mitigation: When a data-quality or execution口径 bug is fixed, rerun the main profile under the corrected口径 before judging any candidate. Promotion review should consume same-generation P2 summaries for main and candidate.
- evidence: The missing-volume suspension fix materially changed blocked-order evidence. v18 could only be judged after refreshing `quality_regime` 60/90/120 P2, after which formal review `20260427_210319` kept the main profile and rejected v18 for MDD parity and blocked-order hard gates.

A stale baseline can make a candidate look better or worse for the wrong reason. Rebaseline first, then compare.

### 2026-04-28 | Do not escalate reserve-safe scores into primary ranking without a score-alpha smoke test
- tags: alpha_diagnosis, reserve_pool, ranking, profile
- status: active
- severity: high
- mitigation: Before running expensive 60/90/120 P2 for a new ranking profile, run `quant_score_alpha_diagnosis.py` on the profile-isolated daily files and require `target_weight` or `portfolio_rank_score` top buckets to beat the candidate-pool average. If the score-level smoke fails, stop before P2 long windows.
- evidence: v20 allowed `reserve_safe_score` to drive full-pool primary ranking, but recent-window diagnostics showed `target_weight/portfolio_rank_score` top forward return around `-3.31%` versus candidate-pool average around `-2.40%`. v19 also failed 20-day P2 after a weaker score-level warning.

Better execution mechanics are not a substitute for positive post-filter score ordering.

### 2026-04-28 | Raw liquidity alpha can be a crowded theme rather than usable diversified alpha
- tags: alpha_diagnosis, liquidity, industry_crowding, promotion
- status: active
- severity: high
- mitigation: When a score looks strong in raw-stage diagnostics, require top-industry label/concentration, post-filter alpha, and final target-weight alpha before using it in profile promotion. Do not relax industry caps to capture a single crowded theme.
- evidence: v18 stage diagnostics over 2026-03-12 to 2026-04-13 showed raw liquidity top-20 forward return around `+2.87%`, but about `73%` of the top bucket came from `计算机、通信和其他电子设备制造业`; final target-weight ranking remained negative.

A raw score can find the winning theme and still be unusable as a professional A-share portfolio signal under industry caps.

### 2026-04-28 | Target-score overrides can reduce losses by starving deployment
- tags: target_score_col, cash_drag, p2, promotion
- status: active
- severity: high
- mitigation: Treat target-score experiments as failed unless they pass both score-alpha smoke and target-weight utilization floors. Compare objective, target_weight_sum_mean, risk block rate, and executable-pool halt days before celebrating NAV/MDD improvement.
- evidence: v21 used `ml_score` for target weights and improved 20-day NAV/MDD versus v18, but target_weight_sum_mean fell to about `18.3%`, risk block rate rose to about `76.6%`, executable-pool halt days rose to `3`, and objective remained weak.

If a profile loses less because it invests less, it has not solved the alpha problem.

### 2026-04-28 | Do not broadly relax low-volume hard filters without downstream proof
- tags: vol_ratio, tradability_filter, v22, cash_drag
- status: active
- severity: high
- mitigation: Split low-volume and high-volume anomaly diagnostics, then require final target-weight alpha and P2 target utilization before accepting a relaxed volume gate. Keep ADV, liquidity, pretrade, industry, and blocked-state constraints active.
- evidence: v18 transition diagnostics showed `vol_anomaly_low_flag` dominated raw -> tradability drops and dropped rows had better forward returns than kept rows. However v22, which disabled the low-volume hard filter, had final target forward return around `-1.20%` and 20-day P2 target-weight mean only about `1.56%` with `15` executable-pool halt days.

Finding an overzealous filter is only a diagnosis. A relaxed filter still fails if the added pool cannot survive pretrade and produce positive executed returns.

### 2026-04-28 | Invested-average style gates can manufacture low-risk cash exposure
- tags: pretrade, style_exposure, p2, cash_drag
- status: active
- severity: critical
- mitigation: Use NAV-weighted style exposure for execution-credibility diagnostics, and require target-weight utilization plus NAV/MDD parity before treating a profile as better. If using invested-average style exposure, label it as a defensive risk-off guard rather than alpha evidence.
- evidence: v18's invested-average style gate blocked nearly all candidates as `style_single_gate_collapse`, with 20-day target-weight mean about `2.24%` and `16` executable-pool halt days. v23's NAV-weighted style basis reduced halt days to `0` and target-weight mean rose to about `36.65%`, but NAV/MDD worsened to about `-3.14%/-4.15%`.

An execution gate that prevents most entries can hide weak alpha. Lower loss from this mechanism is cash drag, not strategy quality.

### 2026-04-28 | Score-alpha and coverage pass can still fail P2 execution smoke
- tags: score_gate, signal_coverage, p2, promotion
- status: active
- severity: high
- mitigation: Treat score-alpha and signal-calendar coverage as prerequisites only. Run a same-generation 60-day P2 smoke before 90/120 refresh, and skip candidates whose NAV, MDD, target-weight utilization, or broker tradability blocks are worse than the main profile.
- evidence: After rebuilding v22 profile daily files to 65 replayable days, v22 passed score-alpha and signal-coverage prechecks. Its 60-day in-process P2 smoke still lost to the main profile: `quality_regime` NAV/MDD `+1.18%/-5.89%`, while `quality_regime_candidate_v22_relaxed_low_volume_gate` was `-1.91%/-7.71%`; v22 also had `7` exit-not-tradable orders versus main `3`. The new P2 smoke precheck correctly skipped v22 before 90/120 spend.

Do not mistake final-ranking alpha smoke or signal coverage for execution pass-through. They decide whether P2 is worth trying, not whether a candidate is good.

### 2026-04-28 | Historical profile rebuilds can be blocked by metadata freshness defaults
- tags: profile_rebuild, metadata, signal_calendar, p2
- status: active
- severity: medium
- mitigation: For historical evidence rebuilds, pass an explicit `--max-metadata-staleness-days` appropriate to the replay date and record it in the command. Use `--replayable-only` and extend the lookback window rather than forcing no-data dates through.
- evidence: A v22 60-day profile daily rebuild initially failed 40 dates because `daily_ml_select.py` used the default metadata freshness threshold of `3.0` days while `stock_info.csv` age was about `4.83` days. Re-running with `--max-metadata-staleness-days 999` removed the metadata failures, leaving five genuine no-data post-cleaning dates that were handled by extending the replayable rebuild window.

Do not let metadata recency checks masquerade as strategy failure during historical rebuilds; also do not bypass genuine no-data days by writing fake daily files.

### 2026-04-28 | Same row count can hide mismatched P2 evidence calendars
- tags: signal_calendar, p2, promotion, evidence_lineage
- status: active
- severity: high
- mitigation: Promotion refresh must require candidate profile daily files to cover the main profile's replayable reference signal dates, not just any N replayable files. Use the signal-coverage precheck's `missing_reference_signal_days` and `profile_signal_calendar_mismatch` reason before running P2 smoke or long windows.
- evidence: v22 had 65 replayable profile daily files and passed the count-based 60-day coverage check, but the candidate's 60-day P2 window started at `20251216` while the main profile started at `20251223`. The candidate was missing the main reference dates `20260126,20260127,20260128,20260203,20260205`; after calendar parity was added, it was rejected before P2 spend.

Do not compare candidates that fill missing dates by shifting the window backward. Same number of signal days is not the same evidence window.

### 2026-04-28 | Shared daily files can be stale/orphan artifacts when market bars are missing
- tags: daily_signal, data_quality, p2, promotion
- status: active
- severity: high
- mitigation: Rolling replay and promotion reference calendars must require signal dates to exist in the canonical manifest-backed ODS `daily_bars` session set selected for that evidence generation. Exclude signal files without matching ODS bars, persist the snapshot/manifest digest, and record the exclusion as stale/orphan signal handling rather than candidate failure.
- evidence: Under the retired pre-ODS generation, `output/daily` had files for `20260126`, `20260127`, `20260128`, `20260203`, and `20260205`, while the then-local market parquet had zero rows for those dates. This historical incident established the invariant; the current implementation must enforce it against ODS sessions, not restore the deleted parquet.

Do not use `output/daily` as the market calendar. It can contain recommendations from dates absent in the selected ODS generation.

### 2026-04-29 | P2 ledger nav_pre/nav_post is not always the full daily NAV path
- tags: p2, attribution, nav_path, evidence_lineage
- status: active
- severity: high
- mitigation: For profile-vs-main daily attribution, compute the continuous path return from consecutive `nav_post` values, using the first row's `nav_pre` only as the initial base. Keep `nav_pre -> nav_post` as execution-segment return, not as the full daily NAV return.
- evidence: The first v22 smoke failure diagnosis version summed `nav_pre -> nav_post` gaps and incorrectly showed a positive relative gap despite the candidate ending `-6.64pct` behind the main profile. Switching to the continuous `nav_post` path aligned the daily gap sum to about `-6.65pct` and identified 2026-01-19 as the worst relative day.

Do not attribute P2 underperformance from row-local execution returns when the ledger has mark-to-market movement between rows. Use the equity path for NAV parity diagnostics.

### 2026-04-29 | Aggregate sell-trap labels can hide holiday-gap cash drag
- tags: p2, sell_trap, cash_drag, holiday_gap, attribution
- status: active
- severity: high
- mitigation: After P2 smoke failure diagnosis, run day-level attribution on the worst relative days. Check `holiday_gap_guard`, target-weight gaps, blocked sells, and risk-gate rows together before designing a new profile.
- evidence: v22's 60-day smoke failure was correctly skipped for NAV/MDD and worse exit blocks, but the worst relative day `2026-01-19` was not a pure sell-trap day. Day attribution found `holiday_gap_cash_drag+sell_trap`: candidate target weight was scaled down to about `12%` versus main `48%` by `holiday_gap_target_scale=0.3`, with one blocked sell (`600415`) and four entry-not-tradable risk rows.

Do not fix a mixed failure by only tightening sell-trap controls. If holiday-gap guards suppress exposure on a day when the main profile earns the spread, the next hypothesis must separate timing/cash-drag policy from sell-trap policy.

### 2026-04-29 | Holiday-gap guard effectiveness is reason-specific
- tags: holiday_gap, cash_drag, p2, attribution
- status: active
- severity: high
- mitigation: Run `scripts/quant_p2_holiday_gap_guard_attribution.py` before modifying holiday-gap guard parameters. Compare guard versus non-guard days by reason and require both cash-drag and sell-trap/downside proxy evidence before calling a trigger protective.
- evidence: Latest v22 60-day attribution classified `post_trade_gap` and `signal_to_trade_gap` as `effective_protection`, but the combined `signal_to_trade_gap+post_trade_gap` reason had only one sample, `2026-01-19`, and showed `holiday_gap_cash_drag+sell_trap` with about `-36pct` target-weight gap and `0.705pct` cash-drag proxy.

Do not switch holiday-gap protection on/off from aggregate guard-day results. A single combined-gap event can dominate missed upside while simpler gap reasons may still reduce downside or blocks.

### 2026-04-29 | Do not reuse an old profile name after changing holiday-gap cap policy
- tags: holiday_gap, profile, evidence_lineage, p2
- status: active
- severity: high
- mitigation: If testing `holiday_gap_reason_overrides`, create or label a new shadow profile and rebuild profile-isolated daily files. Do not overwrite v22/v16 evidence with changed cap semantics under the same profile name.
- evidence: `holiday_gap_reason_overrides` now allows reason-specific caps and writes `holiday_gap_reason_override_applied` into daily/P2 evidence. This is a semantic change to target weights on guard days.

Profile names are evidence contracts. Changing guard cap behavior under an existing candidate name makes old P2 smoke, attribution, and promotion artifacts ambiguous.

### 2026-04-29 | Conditional guard relief can expose final-ranking alpha decay
- tags: v24, holiday_gap, score_gate, alpha, cash_drag
- status: active
- severity: high
- mitigation: Before spending P2 on a holiday/cash-drag tweak, rebuild profile-isolated daily files and require `target_weight` or `portfolio_rank_score` to pass the score-alpha gate. If the final ranking fails, diagnose stage-to-target alpha decay instead of changing guard caps again.
- evidence: v24 relaxed only the combined `signal_to_trade_gap+post_trade_gap` cap and produced clean coverage, but score-alpha precheck skipped it for `no_gate_score_passed`: `target_weight` had negative RankIC, and `portfolio_rank_score` selected a top bucket below the candidate-pool and bottom-bucket returns.

Do not confuse a better exposure rule with a better stock selector. If final target weights point to weak names, reducing cash drag will usually transmit more bad alpha into P2.

### 2026-04-29 | High-score quantile gates can anti-select in a regime window
- tags: ranking, score_gate, alpha_decay, v24
- status: active
- severity: high
- mitigation: Before changing execution guards or running long-window P2, run stage-transition diagnosis with score-stage summaries. If `filtered_signal_pool -> ranking_pool_pre_pretrade` keeps a lower-return subset than it drops, the next fix belongs in ranking/target-score logic, not execution or holiday policy.
- evidence: v24 stage-transition over 70 replayable days showed the filtered signal pool averaging about `+0.656%`, but the high-score ranking pool averaging about `-0.150%`; dropped names averaged about `+1.052%`. Inside the final pool, `liquidity_score` and `exit_trap_safe_score` had positive spread, while `portfolio_rank_score` and `target_weight` remained weak.

Do not assume "higher ML/refactor/execution score" means better in every regime. A quantile gate can turn a broad positive pool into a concentrated negative subset.

### 2026-05-07 | Capacity-aware daily fallback can fake deployment
- tags: portfolio_engine, daily_signal, target_weight, capacity
- status: active
- severity: high
- mitigation: Capacity-aware profiles must preserve empty optimizer output as no-entry / capacity-shortfall evidence. Do not use unconstrained score-weight fallback when capacity, industry, ADV, exit-trap, or min-name constraints make the target portfolio infeasible.
- evidence: v26 initially produced days with over 100 tiny target weights and `optimizer_fallback`, bypassing participation/cost diagnostics after the constrained optimizer selected nothing. After disabling capacity-mode fallback and allowing empty profile daily outputs, v26 had `13/70` zero-target days and failed the hardened score-alpha gate instead of generating misleading P2 exposure.

An infeasible constrained portfolio is information. Replacing it with unconstrained weights turns a risk failure into pseudo-alpha.

### 2026-05-07 | Relative score spread can hide negative long-only alpha
- tags: score_gate, alpha_quality, p2_efficiency
- status: active
- severity: high
- mitigation: Score-alpha smoke must require a positive absolute top-bucket forward return, not just top-minus-pool or top-minus-bottom spread. Candidates with negative top buckets should be treated as research diagnostics unless a separate benchmark/excess-return gate explicitly approves them.
- evidence: After capacity fallback repair, v26 target-weight top bucket had about `-0.033%` mean forward return but still beat the very weak candidate-pool average by about `+0.985pp`. The old gate would spend P2 on that relative spread; the hardened gate rejects it with `top_mean_not_positive`.

For long-only A-share deployment, "losing less than the pool" is not sufficient evidence of a deployable profile.

### 2026-05-07 | Grouped score diagnostics can masquerade as promotion evidence
- tags: score_gate, grouped_diagnostic, promotion
- status: active
- severity: high
- mitigation: Treat `quant_score_alpha_diagnosis.py --group-col ...` as hypothesis generation only. The script now marks grouped runs with `grouped_diagnostic_not_profile_gate` and does not emit a profile-level pass.
- evidence: v26 grouped diagnostics showed some positive subgroups, including primary-only and non-holiday slices, even though the ungrouped profile failed the hardened score-alpha gate. Before the fix, a grouped run could print `alpha_quality_gate_pass=True` if any subgroup passed.

Never spend long-window P2 or argue promotion from a passing subgroup. Rebuild a full profile hypothesis and require ungrouped score-alpha, coverage, P2 smoke, and promotion gates.

### 2026-05-07 | Do not let early precheck pruning erase other cheap evidence
- tags: promotion, precheck, evidence_lineage, target_utilization
- status: active
- severity: medium
- mitigation: Coverage and target-utilization prechecks must evaluate the original requested profiles, even if score-alpha has already pruned a candidate. Only the final P2 run list should be the intersection of all precheck keep sets.
- evidence: In the first v27 cheap run, score-alpha skipped `quality_regime_candidate_v27_primary_reserve_isolation`, so the subsequent latest coverage and utilization artifacts only contained `quality_regime`. After fixing the refresh flow, the latest artifacts show v27 coverage passed with `70` replayable files and utilization passed with `target_weight_sum_mean_60≈35.27%`, while final effective profiles still correctly kept only `quality_regime`.

Compute-saving gates should not hide failure attribution. A skipped candidate still needs enough cheap evidence to guide the next hypothesis.

### 2026-05-07 | P2 profile cap bugs make old reserve/exit-trap artifacts legacy evidence
- tags: p2, reserve_pool, exit_trap, promotion
- status: active
- severity: high
- mitigation: Treat P2 artifacts generated before the reserve/exit-trap cap fix as old-cap evidence. Before using a reserve-cap or exit-trap-cap profile for promotion arguments, rerun P2 with tests proving `_assign_profile_target_weights` consumes `target_max_reserve_weight`, `target_exit_trap_risk_threshold`, `target_max_exit_trap_weight`, and `target_max_exit_trap_single_weight`.
- evidence: v27 work added focused tests proving a positive 2% reserve cap constrains active reserve target weight and that exit-trap threshold/total/single caps flow from profile config into the P2 target-weight path. This closes a risk where P2 replacement could silently ignore or zero-clamp profile caps.

Do not compare cap-sensitive profiles across a cap-lineage break. The artifacts may look like strategy results while actually reflecting execution config drift.

### 2026-05-07 | Ranking-gate relief can turn alpha diagnosis into capacity failure
- tags: ranking_gate, target_score_blend, capacity, cash_drag
- status: active
- severity: high
- mitigation: When a stage-transition report says a ranking gate is damaging, do not assume widening the gate is enough. Rebuild profile daily files and require both score-alpha and target-utilization prechecks before P2. If zero-target days rise or target-weight mean falls below 30%, stop the candidate.
- evidence: v28 softened the pre-pretrade score quantile and used a `liquidity_score` / `exit_trap_safe_score` target blend after v27's stage summary found positive late-stage component scores. It generated 70 daily files cleanly and passed coverage, but the last-60 target-weight mean was only about `21.27%`, zero-target rate was `35%`, and score-alpha still failed.

Fixing an anti-selective ranking gate can expose a larger infeasible-capacity pool. That is not a deployable alpha improvement.

### 2026-05-07 | Positive component score can fail after capacity-feasible selection
- tags: capacity_feasible_alpha, target_score_blend, v28, promotion
- status: active
- severity: high
- mitigation: Before creating another shadow profile from a positive component score, run `scripts/quant_capacity_feasible_alpha_diagnosis.py` on the profile stage snapshots. Require positive selected weighted forward return after portfolio constraints, not only positive unconstrained top return or component RankIC.
- evidence: v28's `target_blend_score` over `optimizer_ranked_pool` had positive unconstrained top mean forward return around `+0.95%` and positive top-minus-pool around `+1.23pct`, but the keep-mode capacity-selected basket returned about `-0.51%` and failed as `capacity_ok_alpha_failed`. A later `score_topn` primary-label diagnostic showed the positive names could be promoted into primary without loosening reserve caps, allowing a narrow v29 shadow test; that v29 still failed 60-day P2 smoke.

If the constrained portfolio turns a positive component slice into a negative selected basket, the issue is not solved by another profile name. The alpha must survive the actual portfolio contract first.

### 2026-05-07 | Do not fix reserve-trapped alpha by simply raising reserve exposure
- tags: reserve_pool, target_score_blend, capacity_feasible_alpha, promotion
- status: active
- severity: high
- mitigation: If capacity-feasible attribution labels a score as `reserve_cap_replaced_alpha`, first test whether the positive names can be promoted into the primary ranking path under the same reserve/exit-trap caps. Do not raise `target_max_reserve_weight` as a shortcut unless P2 evidence proves sell-trap and replacement risk do not worsen.
- evidence: v28 `target_blend_score` lost about `1.46pct` from unconstrained top to capacity-selected basket. Top overlap was only about `25.5%`; top dropped names averaged about `+0.90%`, replacements averaged about `-1.06%`, and the dominant label was `reserve_cap_replaced_alpha`.

Reserve is a replacement budget, not a hidden alpha sleeve. If the alpha only works after relaxing reserve exposure, it may be buying the same sell-trap and governance risk the cap was designed to prevent.

### 2026-05-07 | Static capacity-feasible alpha can still fail P2 path execution
- tags: capacity_feasible_alpha, p2_smoke, v29, execution_pass_through
- status: active
- severity: high
- mitigation: Treat capacity-feasible alpha as a shadow-profile permission gate only. After a pass, rebuild profile daily files and require 60-day P2 smoke NAV/MDD/blocked-order parity before spending 90/120 windows. If P2 fails, analyze path-level causes instead of creating another score-only profile.
- evidence: v29 used `capacity_safe_primary_rank_mode=target_score_topn` to align primary/reserve labels with `target_blend_score`. It passed capacity-feasible alpha, score-alpha, coverage, and target utilization (`target_weight_sum_mean_60≈35.43%`, zero-target `0%`), but 60-day P2 smoke lost badly to the main profile: candidate NAV/MDD about `+0.10%/-7.54%` versus main `+4.73%/-5.84%`, with worse exit-not-tradable orders (`5` vs `3`). Worst relative days included `2026-01-19` holiday-gap cash drag + sell trap and `2026-03-30` underdeployment. The static-to-P2 pass-through diagnostic later showed only `24/60` same-calendar days had positive selected forward return and `15/24` of those still underperformed the main profile in P2; total relative return gap was about `-4.59pct` with verdict `static_alpha_not_p2_passed`.

Forward-return basket quality is not the same as executable equity-path quality. P2 state, T+1 timing, holiday caps, blocked exits, and daily target gaps can destroy a score that looked valid in static capacity diagnostics.

### 2026-05-07 | Final-pool static alpha can hide weak raw model alpha
- tags: raw_alpha, model_quality, score_gate, p2
- status: active
- severity: high
- mitigation: Before creating another profile from final-pool score strength, run stage-transition plus raw-alpha/P2-residual diagnosis. Require raw-universe model or component scores to pass top bucket, spread, and RankIC checks, or explicitly mark the experiment as pipeline/local-pool only.
- evidence: v29 passed final-pool static score gates for `portfolio_rank_score` and `target_weight`, but raw full-universe `ml_score` had top bucket mean forward return about `-2.35%` and RankIC about `-0.057`; the combined raw-alpha/P2-residual verdict was `final_static_alpha_not_p2_executed_raw_alpha_weak`.

Do not let a late-stage or final-pool score pass become proof of model alpha. It may be a local selection artifact that fails once the full universe and P2 path are considered.

### 2026-05-07 | Label/profile horizon mismatch can distract from score-direction failure
- tags: raw_alpha, label_horizon, model_quality, profile
- status: active
- severity: high
- mitigation: When raw ML alpha is weak, run `scripts/quant_raw_ml_horizon_diagnosis.py` before blaming the holding period. Check normal and inverted score directions across several open-to-open horizons, and report both model `label_horizon` and profile `holding_days`.
- evidence: v29 raw horizon diagnosis verdict `raw_ml_alpha_failed_profile_horizons` found the latest model trained with `open_to_open label_horizon=3`, while `quality_regime` holds `8` days and v29 holds `10`; however normal descending `ml_score` failed H=1/3/5/8/10/15. The trained H=3 top bucket was about `-0.51%`, H=8 about `-2.18%`, and all normal-direction RankIC values were negative. Inverting the score only weakly passed H=1, not the profile horizons.

Do not create a new profile or retrain horizon experiment on the assumption that the only bug is H=3 versus H=8/10. First verify label sign, target construction, split integrity, and feature drift.

### 2026-05-07 | Pooled raw-model alpha can hide fold instability
- tags: raw_model, walk_forward, split_stability, promotion
- status: active
- severity: high
- mitigation: Raw-universe model gates must require fold-level stability, not only pooled OOS top bucket, spread, and RankIC. A horizon/model line should not proceed to capacity/P2 unless pooled metrics pass and enough walk-forward folds pass the same alpha gate.
- evidence: The H=10 raw-universe walk-forward diagnostic had pooled OOS top bucket about `+1.38%`, top-minus-all about `+0.33pct`, top-minus-bottom about `+3.56pct`, and RankIC about `0.054`, but only 3 of 7 folds passed. Failing windows included 2024-05 to 2024-08 due to negative top bucket, 2025-09 to 2025-12 due to weak/negative spread, and 2026-01 to 2026-04 due to negative top bucket despite positive IC.

Do not use a pooled H=10 result as permission to build vNext. Split instability is exactly the kind of pseudo-alpha that later disappears in P2.

### 2026-05-08 | A one-fold rescue is not a model-stability fix
- tags: raw_model, fold_instability, walk_forward, promotion
- status: active
- severity: high
- mitigation: When focused fold attribution covers multiple critical windows, require all focused folds to pass before labeling a variant as a local fix. If a variant rescues only one fold, record it as `instability_variant_partial_fix_only` and keep profile/P2 work blocked.
- evidence: H=10 focused instability attribution over folds 6/7 found recency weighting rescued 2025Q4 fold 6 but did not rescue 2026Q1/Q2 fold 7. The verdict logic was tightened so 50% focus-fold pass rate is no longer treated as a local fix; latest verdict is `instability_variant_partial_fix_only`.

Do not let a partial rescue become a new profile narrative. In this project, Q1/Q2 2026 top-bucket failure is the binding raw-model problem.

### 2026-05-08 | Fixing the critical fold is not enough if split stability fails
- tags: raw_model, rank_normalization, split_stability, profile_gate
- status: active
- severity: high
- mitigation: A raw model variant must pass the critical fold and the full-fold stability floor before capacity/P2 resumes. If a variant fixes fold 7 but passes fewer than 50% of folds, keep it in model diagnosis and do not create a profile.
- evidence: H=10 `rank_normalized` fixed 2026Q1/Q2 fold 7 (`top≈+0.44%`, `top-minus-all≈+0.83pct`, RankIC≈`0.054`) but passed only `3/7` folds. The variant family verdict is `split_unstable`, not model pass. `cross_sectional_only` had a better `4/7` pass rate but failed fold 7, so it is also not a deployable line.

Do not move to profile engineering just because the latest painful fold is repaired. A fold-7 fix without full split stability is still a research clue, not executable alpha.

### 2026-05-08 | Random training subsamples can manufacture a model-family pass
- tags: raw_model, sample_stability, split_stability, profile_gate
- status: active
- severity: high
- mitigation: Before promoting a raw model variant from diagnosis to any profile/P2 work, rerun the 7-fold family test under at least one independent seed and a deterministic sampling mode such as `--sample-mode date_stratified`. A variant that passes only under selected random samples must be labeled sample-unstable, even if it fixes the critical fold once.
- evidence: H=10 `rank_norm_drop_high_drift` passed seed1/seed2 and looked like a possible fold7 repair, but seed3 failed (`2/7` folds, fold7 top about `-0.87%`) and deterministic date-stratified sampling also failed (`3/7`, fold7 top about `-0.53%`, top-minus-all about `-0.15pct`). `blend_rank_norm_huber` similarly passed seed1 but failed seed2 fold7.

Do not cherry-pick the random seed that makes a raw model line pass. Seed/sample robustness is a model gate, not an optional comfort check.

### 2026-05-08 | Positive spread with a negative top bucket is not a raw alpha pass
- tags: raw_model, alpha_gate, fold7, regime_conditioning
- status: active
- severity: high
- mitigation: Keep the raw model gate conjunctive: top bucket must be positive, top-minus-pool and top-minus-bottom must be positive, and RankIC must be positive. If a variant only improves relative spread while the absolute top bucket remains negative, keep it in model diagnosis and do not create a profile or run P2.
- evidence: The H=10 `h10_fold7_regime_specific_probe` found `rank_norm_regime_specific` improved fold7 materially versus baseline, with top-minus-all about `+0.358pct` and RankIC about `0.030`, but the absolute top bucket was still about `-0.025%`. The verdict remained `instability_not_fixed_by_basic_variants`, and `alpha_gate_pass=False` due to `top_mean_non_positive`.

Do not let a near-zero rescue become a promotion narrative. A-share execution costs, capacity, T+1, holiday guards, and blocked-order path effects will not rescue a raw top bucket that is still negative before execution.

### 2026-05-08 | A residual fold can look improved while still failing for a different reason
- tags: raw_model, residual_fold, split_stability, profile_gate
- status: active
- severity: high
- mitigation: After a model variant rescues the latest critical fold, run residual fold diagnosis on the remaining failures. Do not advance to profile/P2 if the remaining folds are only relative risk-off defense or positive top buckets that still lag the pool/bottom bucket.
- evidence: `rank_norm_regime_label_ranked` rescued fold7, but residual fold diagnosis showed fold2 as `absolute_loss_but_beats_pool` (`top≈-0.95%`, spread `+0.96pct`) and fold6 as `positive_top_but_pool_and_bottom_lag` (`top≈+1.09%`, top-minus-all `-0.24pct`, top-minus-bottom `-0.83pct`).

Do not treat "better than baseline" as "deployable alpha." The gate is absolute top, pool spread, bottom spread, RankIC, full split stability, and sample stability together.

### 2026-05-08 | Do not merge fold2 and fold6 residual repairs into one profile tweak
- tags: raw_model, residual_treatment, fold2, fold6, profile_gate
- status: active
- severity: high
- mitigation: Treat fold2 and fold6 as separate raw-model treatment problems. Fold2 requires weak-window absolute-return protection/calibration; fold6 requires strong/neutral market beta and `pos_52w` drift opportunity capture. A future variant must prove both repairs in a full 7-fold raw-universe run before any capacity/P2/profile work.
- evidence: `quant_raw_model_residual_treatment_probe.py` labels fold2 as `weak_market_absolute_return_calibration` and fold6 as `beta_capture_pos52w_drift_repair`. The output verdict explicitly sets `allow_profile_build=false` and `allow_p2=false`.

Do not create a new shadow profile from treatment hypotheses. A treatment probe tells the next model experiment what to test; it is not alpha evidence.

### 2026-05-08 | Unconditional residual treatment overlays can move one fold while breaking another
- tags: raw_model, residual_treatment, pos_52w, fold_stability
- status: active
- severity: high
- mitigation: Any fold-specific treatment must be validated across all seven folds and critical folds `2,6,7`. Do not accept an unconditional absolute-return blend or pos_52w/beta boost because it improves one residual metric. Require fold2 top bucket to be positive, fold6 spread/bottom spread to be non-negative, and fold7 to remain passed in the same run.
- evidence: The `h10_residual_treatments_7fold_date_stratified` run showed `pos52w_beta_rank_norm_regime_label_ranked` improved fold6 top-minus-all from about `-0.675pct` to `-0.090pct`, but still failed fold6 and broke fold7 top bucket to about `-0.294%`. The absolute-return blend worsened fold2 from about `-0.790%` to about `-2.273%`.

Do not call a treatment useful until it clears the complete raw-model gate. Small directional improvements in a residual fold can still be pseudo-progress.

### 2026-05-08 | Deployment veto can manufacture raw-model improvement by starving signal coverage
- tags: raw_model, deployment_veto, cash_drag, split_stability
- status: active
- severity: high
- mitigation: Any day-level absolute-return calibrator or deployment veto must report `deployment_day_rate_pct`, `vetoed_days`, and raw day counts, and must fail the alpha gate below the deployment floor. Do not compare top-bucket returns without coverage.
- evidence: The `h10_residual_strict_treatments_7fold_date_stratified` run showed `day_veto_rank_norm_regime_label_ranked` with mean deployment about `54.7%` and minimum fold deployment about `18.3%`. Fold2 deployed only about `21.4%` of days and still had a negative top bucket; fold6 deployed only about `18.3%` and still lagged the pool.

A veto that mostly avoids trading can make average diagnostics look cleaner while failing the deployable-alpha question. Treat low-deployment model variants like cash-drag candidates until they prove coverage, positive top bucket, spread, RankIC, and split stability together.

### 2026-05-08 | Conditional overlays are no-op evidence if training regimes do not authorize activation
- tags: raw_model, residual_treatment, pos_52w, regime_conditioning
- status: active
- severity: high
- mitigation: A regime-aware overlay must report the train-time activation allowlist and activation rate. If the train allowlist is empty or activation is sparse, label the run as diagnostic/no-op rather than a model repair.
- evidence: The strict `conditional_pos52w_beta_rank_norm_regime_label_ranked` run mostly emitted `conditional_pos52w_beta_overlay=no_allowed_regime`, passed only `2/7` folds, and worsened fold6 top-minus-all to about `-0.968pct` versus the base `rank_norm_regime_label_ranked` fold6 top-minus-all around `-0.675pct`.

Do not use the word "conditional" as a credibility upgrade by itself. The conditioning rule must be learned from training data, activate in the intended opportunity window, and avoid re-breaking folds that already passed.

### 2026-05-08 | Train-time opportunity detector vetoes should not be overridden by narrative pressure
- tags: raw_model, opportunity_detector, pos_52w, fold6
- status: active
- severity: high
- mitigation: When a train-only day-state opportunity detector reports negative expected edge or zero activation for a target fold, treat that as evidence against the overlay under the current feature set. Do not force activation just to repair one residual fold.
- evidence: In `h10_day_state_calibration_opportunity_critical_folds_date_stratified`, the fold6 day-state pos_52w/beta detector had `0%` activation and mean expected top-minus-all edge about `-0.368pct`; forcing an unconditional overlay had previously only partially improved fold6 while breaking fold7.

If the detector cannot identify the opportunity from signal-date training evidence, the correct next step is better features or model structure, not a lower activation threshold that turns conditional logic back into an unconditional overlay.

### 2026-05-08 | Day-state calibration can preserve coverage and still worsen absolute top returns
- tags: raw_model, day_state_calibration, fold2, alpha_gate
- status: active
- severity: high
- mitigation: Require day-state calibrators to improve absolute top bucket, pool spread, bottom spread, and critical-fold stability. Coverage preservation alone is not enough.
- evidence: `day_calibrated_rank_norm_regime_label_ranked` kept `100%` deployment and activated on about `72.6%` of fold2 days, but fold2 top bucket worsened to about `-1.491%` from the base `rank_norm_regime_label_ranked` at about `-0.790%`.

A more sophisticated-looking calibrator can still be anti-selective. Treat it as failed unless it turns weak-window top buckets positive without damaging other critical folds.

### 2026-05-08 | Engineered two-stage raw-model variants can look closer while still failing critical folds
- tags: raw_model, engineered_features, two_stage_model, profile_gate
- status: active
- severity: high
- mitigation: Require engineered-feature and two-stage model variants to pass the full raw-model gate across all critical folds before any capacity/P2/profile work. Do not accept "near-zero fold7" or "smaller fold6 pool lag" as a model pass.
- evidence: The full `h10_engineered_positive_two_stage_7fold_date_stratified` run showed the best engineered two-stage variant passed only `2/7` folds. Fold2 remained an absolute top-bucket failure around `-1.80%`; fold6 top bucket was positive around `+1.17%` but still lagged the pool by about `-0.16pct`; fold7 was approximately `-0.002%`, close to zero but still not positive.

Do not let a better-looking partial fix reopen capacity/P2. The raw gate remains conjunctive: positive top bucket, positive pool spread, positive bottom spread, positive RankIC, critical-fold pass, and split stability.

### 2026-05-08 | Context features can hide the remaining weak-window absolute loss if only aggregate pass rate is watched
- tags: raw_model, context_features, fold2, split_stability
- status: active
- severity: high
- mitigation: When a context-feature model improves fold pass rate or rescues fold6/fold7, still inspect each critical fold. Do not advance unless fold2 absolute top bucket is positive, not merely above the weak pool.
- evidence: `context_rank_norm_regime_label_ranked` improved the H=10 7-fold run to `3/7` pass folds and rescued fold6/fold7, but fold2 top bucket remained about `-1.72%`. Fold2 spread over pool was positive, so aggregate mean/spread could make the variant look promising if the absolute top-bucket gate is weakened.

Do not lower the gate because the bottleneck moved. A weak-market fold that still loses money before costs and execution cannot be fixed downstream by capacity or P2 engineering.

### 2026-05-08 | Ex-ante regime strings can be silently erased by numeric cleaning
- tags: raw_model, regime_specific, evidence_lineage, data_cleaning
- status: active
- severity: high
- mitigation: Keep categorical regime fields such as `market_regime_exante` out of generic numeric coercion loops, and test that `_clean_with_extras` preserves regime labels. If regime-specific model notes collapse to a single regime, inspect cleaning before interpreting the result.
- evidence: `_clean_with_extras` previously iterated over `REGIME_EXTRA_COLS` and coerced `market_regime_exante` to numeric, turning string regimes into NaN and allowing downstream fallback to neutral-like behavior. The fix preserves `market_regime_exante` as a string and the refreshed `h10_downside_context_7fold_date_stratified` run now reports real `high_vol_down` / `neutral` / `risk_off` / `risk_on` regime splits.

Do not trust regime-specific raw-model evidence unless the categorical regime column is explicitly preserved through feature cleaning, sampling, model training, prediction, and attribution artifacts.

### 2026-05-08 | Downside sample weighting can rescue other folds while leaving weak-window absolute loss intact
- tags: raw_model, downside_weighting, fold2, split_stability
- status: active
- severity: high
- mitigation: Treat `downside_*` variants as failed unless fold2 top bucket turns positive and all critical folds pass together. Do not count fold6/fold7 recovery as permission to resume capacity/P2/profile work.
- evidence: In `h10_downside_context_7fold_date_stratified`, `downside_context_rank_norm_regime_label_ranked` passed fold6/fold7 but fold2 remained about `-1.845%`; `downside_context_rank_norm_regime_label_tail_ranked` was the family best at `3/7` folds but fold2 worsened to about `-2.243%`.

The remaining hard problem is not merely sample weighting; it is weak-window absolute-return prediction or deployment-quality day selection.

### 2026-05-08 | Defensive day-state overlays can improve fold2 while still failing absolute-return gates
- tags: raw_model, day_state_calibration, fold2, alpha_gate
- status: active
- severity: high
- mitigation: Treat day-state calibration as failed unless it turns weak-window top bucket positive. Do not accept "less negative" fold2 as a reason to resume capacity/P2/profile work.
- evidence: `h10_context_day_calibration_7fold_date_stratified` showed `day_calibrated_context_rank_norm_regime_label_ranked` improving fold2 top bucket from plain context about `-2.541%` to about `-1.660%`, while still failing `top_mean_non_positive`. It passed fold6/fold7, but the critical-fold gate remained false.

Partial fold2 improvement is useful research signal, not deployable alpha. The next fix must change weak-market target/deployability modeling enough to make selected returns positive before costs.

### 2026-05-09 | A 5/7 raw-model pass rate is still a failure when fold2 stays negative
- tags: raw_model, weak_positive_label, critical_folds, profile_gate
- status: active
- severity: high
- mitigation: Require critical folds `2,6,7` to pass together before capacity/P2/profile work resumes. Do not allow a high overall fold pass rate to override a negative absolute top bucket in fold2.
- evidence: `h10_weak_positive_context_7fold_date_stratified` produced `day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked` with `5/7` fold pass rate and fold6/fold7 passing, but fold2 remained `top≈-1.884%`. The best fold2 variant in that run was still only about `-1.545%`.

The full-fold pass rate improved, but the binding critical fold did not. Treat this as a stronger raw-model research baseline, not a promotion or P2 trigger.

### 2026-05-09 | Abstention heads can hide model failure unless deployment and top-return gates both pass
- tags: raw_model, abstention, fold2, deployment_gate
- status: active
- severity: high
- mitigation: Require abstention/deployability variants to pass both the deployment-day coverage floor and absolute top-bucket return gate. A fold2 abstention variant that deploys too little, or deploys all days despite validation optimism, must remain diagnosis-only.
- evidence: `h10_validated_abstention_fold2_probe` vetoed `44/84` fold2 days but still had top bucket about `-1.60%` and deployment rate only `47.6%`. `h10_hit_abstention_fold2_probe` had validation-deployed mean about `+3.75%`, but deployed all `84/84` fold2 test days and top bucket was about `-2.75%`.

Do not interpret a validation-calibrated abstention head as robust unless it proves out in the held-out fold. Current fold2 evidence points to deployability miscalibration, not a safe risk-off rule.

### 2026-05-09 | Harsher positive-return labels can worsen weak-window selection
- tags: raw_model, fold2, label_objective
- status: active
- severity: high
- mitigation: Do not assume stricter absolute-positive training labels are safer. Require fold2-only top bucket to improve and turn positive before spending full 7-fold compute. If strict/margin positive labels worsen fold2, stop that branch and move to state/feature diagnostics.
- evidence: `h10_strict_positive_fold2_probe` showed baseline fold2 top bucket about `-1.92%`, while `context_rank_norm_regime_label_margin_positive_ranked` was about `-2.09%`, `strict_positive` about `-2.18%`, and two-stage strict/margin variants about `-2.39%/-2.85%`.

Do not keep tightening labels after this result. The fold2 problem is not solved by target harshness alone; it needs train/test state migration or missing feature analysis.

### 2026-05-09 | Validation-window deployability can fail under fold2 state migration
- tags: raw_model, fold2, state_migration, validation
- status: active
- severity: high
- mitigation: Do not use validation-calibrated deployability thresholds, strict labels, or abstention heads as raw-model pass evidence unless the held-out fold has comparable signal-date state distribution and positive absolute top-bucket returns. For fold2-like weak windows, inspect state drift and ex-ante regime migration before designing another label/abstention experiment.
- evidence: `h10_fold2_state_migration` returned `state_distribution_shift`, not simple optimistic deployability. Test expected return was already negative at about `-1.26%`, actual was about `-1.91%`, and expected deploy rate was only about `29.8%`; the main warning was state drift, with max PSI about `6.51` across volatility, amount, `pos_52w`, relative-strength, and price-volume-correlation day-state features. Test `risk_on`/`neutral` days were deeply negative, while validation `risk_off` days were strongly positive, making validation a poor proxy.

Do not keep iterating fold2 by asking the same validation head to abstain harder. If state distribution has moved, the model needs better state representation or split-aware training, not another optics-friendly deployment threshold.

### 2026-05-09 | Matched-state relative improvement is not a fold2 alpha pass
- tags: raw_model, fold2, matched_state, profile_gate
- status: active
- severity: high
- mitigation: Do not advance a matched-state or state-weighted raw-model variant unless it turns the held-out top bucket positive and passes spread/RankIC gates. Treat state-matched training as transductive diagnosis because it uses held-out signal-date state distribution, even though it does not use held-out labels.
- evidence: `h10_fold2_state_robust_probe` found the best matched-state variant improved fold2 relative spread but still had negative absolute top bucket: `matched_state_context_rank_norm_regime_label_weak_positive_ranked` top about `-1.54%` and top-minus-all about `+0.37pct`. Keep-rate sensitivity did not rescue it: 25% keep rate was about `-1.93%`, 65% keep rate was about `-2.84%`. `state_weighted_*` and `state_weak_positive_daily_ranked` were worse.

Do not convert a "less negative and above pool" fold2 result into capacity/P2/profile work. In A-share execution, negative raw top buckets before costs are not alpha.

### 2026-07-16 | Never restore data availability by invoking legacy download/update scripts
- tags: data_source, ods, read_only, pipeline
- status: active
- severity: high
- mitigation: ODS availability failures must be recorded as failures and halt downstream selection/execution. The project may read `/Users/max/Data/ashare-source-data` but must not write it or fall back to legacy download/update scripts.
- evidence: `daily_all.py` previously contained incremental/full-download fallbacks tied to `daily_all_5y.parquet`; the ODS migration replaced them with a read-only coverage gate and regression tests.

### 2026-07-16 | Do not preserve legacy interfaces merely to satisfy stale tests
- tags: data_source, testing, ods, regression
- status: active
- severity: medium
- mitigation: Update tests to assert ODS session/as-of metadata behavior instead of monkeypatching removed local-parquet helpers. Preserve an explicit external-file diagnostic option only where it is intentionally labelled and cannot become the default.
- evidence: Full-suite collection initially exposed stale tests for `nearest_trade_day_on_or_before`, local metadata loading, and the Web downloader after those paths were migrated or disabled.

### 2026-07-16 | Unadjusted research prices can manufacture feature and label discontinuities
- tags: ods, adjusted_price, corporate_action, raw_model
- status: active
- severity: critical
- mitigation: Separate signal-date-safe adjusted research bars from raw execution bars. Rebuild feature caches, labels and models after the split; do not reuse unadjusted raw-model evidence.
- evidence: `AShareMarketDataGateway` declares `price_mode=unadjusted`; `daily_adj_factor` is joined but not applied. A read-only check over 2026-06-01..2026-07-16 found 2,068 rows where the adjustment factor changed.

### 2026-07-16 | Window-end instrument metadata is not historical PIT evidence
- tags: ods, pit, st, industry, survivorship
- status: active
- severity: critical
- mitigation: Require PIT name/ST/industry/listing status or fail closed for historical filters that depend on those fields. Do not join a single window-end master snapshot to all historical rows.
- evidence: `load_daily_panel` joins `instrument_master` as of the requested window end. The partition labelled 2014-12-31 contains stocks listed in 2022/2023 and current `*ST` names, so it cannot support historical ST or industry assertions.

### 2026-07-16 | Execution limits must consume official pre-close and limit prices
- tags: execution, price_limits, corporate_action, a_share
- status: active
- severity: critical
- mitigation: Use ODS `pre_close`, `up_limit`, and `down_limit` for execution tradability. Fixed board/ST ratios are fallback-only when official fields are absent.
- evidence: `load_execution_bars` constructs `prev_close` from prior raw close, while `PaperBroker` infers locked limits from a fixed ratio. This can misclassify ex-rights days and status/board transitions even though ODS already provides official daily limit fields.

### 2026-07-16 | Forward-label outcomes must not cross walk-forward split boundaries
- tags: raw_model, labels, purge, embargo, lookahead
- status: active
- severity: critical
- mitigation: Persist label entry/exit/availability dates and purge every train or validation row whose outcome reaches the next split. Use a preregistered horizon-aware embargo in training and raw-universe diagnostics.
- evidence: Training and `quant_raw_model_walkforward_diagnosis.py` construct future open-to-open labels on the full frame, then split by signal date without excluding rows whose exit occurs in validation/test.

Cross-boundary outcomes make a historical fold train on labels unavailable at its declared cutoff, even when feature timestamps are clean.

### 2026-07-16 | Checksum coverage does not prove daily-to-P2 target equality
- tags: target_weight, p2, evidence_lineage, checksum
- status: active
- severity: critical
- mitigation: Preserve the immutable daily per-security target instruction. Every pretrade/reserve/lot/broker change must emit a parent checksum, transform reason, and child checksum; promotion must compare equality or a complete transform chain.
- evidence: `quant_p2_paper_trade.py` records the upstream budget/checksum, drops per-name target fields, then calls `_assign_profile_target_weights`; rolling evidence can report checksum coverage without proving broker targets equal daily targets.

A downstream recomputation may be a valid execution transform, but it is a different portfolio unless explicitly linked and attributed.

### 2026-07-16 | Open-price fills cannot use the day's later high, low, or full amount
- tags: execution, lookahead, price_limits, adv, p2
- status: active
- severity: critical
- mitigation: Use official pre-close/up-limit/down-limit and only open-time observable state for an open-order model. Capacity at the open must use information through signal date; full-day high/low/amount are post-trade TCA inputs.
- evidence: `PaperBroker` checks same-day high/low to decide whether a limit-open order is tradable while filling at open, and `load_execution_bars` computes rolling amount including the execution day.

If intraday unlock execution is desired, it requires timestamped intraday data and a later fill price, not an open-price fill.

### 2026-07-16 | A universal 7-of-7 absolute-profit gate can become gate overfitting
- tags: raw_model, fold_stability, governance, overfitting
- status: active
- severity: high
- mitigation: Require data/method contracts in every fold, but preregister investment thresholds using directional stability, worst-fold floors, residual alpha, confidence intervals and multiple-experiment controls. Do not tune models until every long-only fold is positive merely to satisfy an arbitrary gate.
- evidence: External review correctly rejected the current 50% fold-pass rule but proposed that every fold simultaneously have positive absolute top return, RankIC and spreads. That criterion is not a universal requirement for a regime-aware long-only strategy and can incentivize repeated fitting to the worst fold.
