# Long-Term Learnings

Append durable research, execution, and governance learnings here. Keep entries factual, with artifact-backed evidence where possible.

## Learnings Log

### 2026-04-27 | P2 reserve re-optimization must stay inside upstream daily target budget
- tags: p2, target_weight, reserve_pool, v16, promotion
- reusable: yes
- confidence: high
- evidence: v16 profile daily for `2026-04-02` had upstream `target_weight` sum `18%`, but pre-fix P2 re-optimized the 2026-04-03 trade day back to about `38.6%` target exposure. After deriving P2 `total_target` and `max_single` from upstream target weights, the 10-day v16 smoke over `2026-03-23` to `2026-04-03` improved NAV/MDD to about `-0.34%/-0.98%`, reduced 2026-04-07 max trapped sell weight from about `35.7%` to `14.4%`, and reported `upstream_target_weight_overrun_max=0`.
- action: Keep P2 reserve replacement bounded by upstream daily target-weight sum and max single weight. Promotion must hard-fail any profile with positive upstream target-weight overrun.

Reserve pool repair is allowed to choose different executable names, but it must not expand the research/portfolio layer's target budget. Otherwise holiday/capacity guards appear ineffective even when daily signals were correctly capped.

### 2026-04-27 | v16 holiday-gap guard helps only after target-budget lineage is fixed
- tags: v16, holiday_gap, sell_trap, p2
- reusable: yes
- confidence: medium
- evidence: With P2 target-budget overrun fixed, `quality_regime_candidate_v16_holiday_gap_guard` triggered holiday guards on 2 of 10 smoke days and capped 2026-04-02/2026-04-03 upstream target budgets to `18%`. The 2026-04-07 sell-trap remains, with `broker_exit_not_tradable_orders=24`, max trapped sell weight about `14.4%`, and predictor direction still false.
- action: Treat v16 as an execution-credibility repair candidate, not a promotion candidate. Next work should identify position-level pre-holiday unwind rules and sell-trap state controls instead of simply lowering all holiday-gap target weights.

Uniform pre-holiday target caps reduce trapped exposure but do not solve which held names become unexit-able after the gap.

### 2026-04-27 | Expert review is an escalation mechanism, not a routine checkpoint
- tags: expert_review, governance, workflow
- reusable: yes
- confidence: high
- evidence: User clarified that expert review should be requested only when the agent is uncertain or needs independent advice; otherwise continue local implementation and evidence generation.
- action: Keep progressing locally when the next patch/replay/diagnostic is clear. Escalate only for genuine uncertainty, strategic forks, unresolved methodology risk, or near-promotion/default-profile decisions; when escalating, prepare a clean GitHub snapshot and provide the full expert prompt.

This reduces unnecessary review churn while preserving an explicit path to external scrutiny when local evidence is insufficient.

### 2026-04-27 | v15 volume-drought trap confirms entry features are insufficient
- tags: v15, sell_trap, p2, feature_study
- reusable: yes
- confidence: high
- evidence: Full-universe `quant_sell_trap_feature_study` over 520 recent trading days found `vol_ratio_low_risk` was the strongest signal-date-known feature for future 5-day exit blocks (Spearman about `0.387`, top-decile label rate about `12.89%` vs base `2.50%`). But v15 10-day P2 smoke over 2026-03-23 to 2026-04-03 had NAV `-2.17%`, MDD `-2.27%`, target_weight_sum_mean `33.9%`, broker exit-not-tradable orders `24`, and max blocked-sell current weight `36.2%`.
- action: Keep v15 shadow/diagnostic only. Stop trying to solve 2026-04-07-style sell traps with entry-score blending alone; next work should model holding-state, holiday-gap, market-wide liquidity stress, and sell-unwind policy.

Volume drought is a real risk feature at the full-universe label level, but translating it directly into ranking/portfolio caps did not improve execution NAV.

### 2026-04-27 | Sell-trap feature study supports larger-sample diagnostics
- tags: sell_trap, feature_study, diagnostics
- reusable: yes
- confidence: high
- evidence: `scripts/quant_sell_trap_feature_study.py` writes full-universe feature summaries, deciles, and meta; latest 520-day run covered about `2.64M` rows and `5270` codes from `2024-01-24` to `2026-04-07`.
- action: Use feature-study outputs before introducing new sell-trap risk scores. Require any candidate risk score to beat filled-sell controls in P2 predictor diagnosis, not only show full-universe correlation.

Full-universe feature studies are useful for finding risk candidates, but P2 position-lineage validation is the gate for portfolio use.

### 2026-04-27 | v14 exit-trap budget improves observability but not sell-trap prediction
- tags: v14, sell_trap, predictor, p2
- reusable: yes
- confidence: high
- evidence: v14 10-day P2 smoke over 2026-03-23 to 2026-04-03 had NAV `-1.36%`, MDD `-1.99%`, target_weight_sum_mean `35.96%`, broker entry-not-tradable orders `0`, broker exit-not-tradable orders `22`, and sell-trap days `6`.
- action: Keep v14 shadow/diagnostic only. Do not promote or tune exit-trap caps until predictor validation shows entry-time risk scores separate blocked sells from normal sells.

The first exit-trap budget moved risk earlier in the pipeline, but did not reduce the sell-trap problem enough to improve execution NAV.

### 2026-04-27 | Simple signal-date exit-trap score was anti-predictive in v14 smoke
- tags: sell_trap, predictor, validation, alpha
- reusable: yes
- confidence: high
- evidence: `quant_sell_trap_predictor_summary_20260427_160722.csv`; blocked sell orders had lower entry exit-trap risk than filled sell orders (`0.127` vs `0.172`), high-risk recall was `0%`, and `predictor_direction_ok=False`.
- action: Before adding more sell-trap penalties, build larger-sample predictor validation and feature attribution. Treat simple near-limit-down/volume-pressure rules as insufficient.

If a risk score cannot rank later blocked sells above normal sells, using it as a hard portfolio cap creates false comfort and may remove good exposure while leaving trap risk.

### 2026-04-27 | Mixed amount/volume units created false ADV-collapse evidence
- tags: data_quality, adv, p2, promotion
- reusable: yes
- confidence: high
- evidence: Several recent dates in `data/daily_all_5y.parquet` had date-wide low `amount` values inconsistent with adjacent days. After adding `utils/market_data_units.py` and rerunning v9 P2, executable_pool_halt_days dropped from `10/10/10` to `0/0/0`, ADV halt hits dropped to `0`, and target_weight_sum_mean rose to about `38.5%/38.6%/38.8%`.
- action: Treat pre-normalization ADV diagnostics as stale. Always load market bars through normalized loaders before capacity, P2, rolling compare, or promotion analysis.

The old v9 conclusion "candidate pool is mainly ADV-collapsing" was a data-unit artifact. After normalization, the real issue is sell traps, style/tradability interaction, and weak execution-layer alpha.

### 2026-04-27 | Higher investability exposed weaker v9 execution alpha
- tags: v9, alpha, p2, sell_trap
- reusable: yes
- confidence: high
- evidence: Unit-normalized v9 P2 60/90/120 NAV = `-2.62%/-4.69%/-4.17%`, MDD = `-7.91%/-7.95%/-7.93%`, target_weight_sum_mean = `38.5%/38.6%/38.8%`; formal promotion review `quant_profile_promotion_review_20260427_153053` kept default and rejected v9 for tradability/sell-trap hard gates.
- action: Do not promote v9. Next optimization should improve sell-trap avoidance and alpha quality under real invested exposure, not loosen ADV/style/industry risk.

Raising target-weight utilization is only useful when realized NAV/MDD improve. v9 now invests more cleanly, but returns still do not justify promotion.

### 2026-04-27 | v13 reserve cap reduces reserve-sourced sell traps but wins partly by lower exposure
- tags: v13, reserve_pool, sell_trap, p2, promotion
- reusable: yes
- confidence: high
- evidence: `quality_regime_candidate_v13_reserve_cap` added `target_max_reserve_weight=10%` and 10-day P2 smoke over 2026-03-23 to 2026-04-03 improved NAV from v12 `-1.88%` to `-0.44%`, reduced broker exit-not-tradable orders from `44` to `22`, and reduced reserve-entry blocked sell orders from `36` to `15`; target weight mean also fell from `11.60%` to `8.54%`, while executable-pool halt days stayed at `4`.
- action: Treat reserve exposure caps as sell-trap risk control, not alpha. Promotion must still reject candidates with low effective target weight, executable-pool halt clusters, or reserve-sourced trapped sells.

Reserve caps can make the path look cleaner by preventing risky replacement exposure from entering the book. That is useful risk evidence, but it does not solve the underlying executable-pool collapse.

### 2026-04-27 | v12 tradability-safe upstream scoring improves observability but does not solve sell traps
- tags: v12, tradability_safe, daily_signal, p2, sell_trap
- reusable: yes
- confidence: high
- evidence: Built `quality_regime_candidate_v12_tradability_safe` daily signals for 2026-03-20 to 2026-04-03 with `failed=0`; 10-day P2 smoke over 2026-03-23 to 2026-04-03 had `target_weight_sum_mean=11.60%`, `broker_exit_not_tradable_orders=44`, `executable_pool_halt_days=4`, and 2026-04-03/2026-04-07 attribution remained `sell_trap`.
- action: Keep v12 as a shadow diagnostic profile. Do not expect upstream tradability-safe ranking alone to fix trapped sell exposure; next work should address exit-risk posture and sell-trap unwind policy.

Candidate generation can reduce obviously hot/near-limit reserve names, but it cannot make an already trapped A-share position sellable.

### 2026-04-27 | v11 makes sell-trap clusters promotion hard evidence
- tags: v11, promotion, sell_trap, blocked_orders
- reusable: yes
- confidence: high
- evidence: `quant_profile_promotion_review_20260427_140352` merged `quant_p2_halt_cluster_attribution_latest.csv`; v9 now fails explicit cluster gates with `halt_cluster_sell_trap_worse_than_main` and `halt_cluster_severe_sell_trap_failed` in addition to target-weight, tradability, halt-rate, and ADV gates.
- action: Keep halt cluster attribution wired into promotion review; severe sell traps should block promotion even when aggregate NAV/MDD windows look acceptable.

Late-March and early-April A-share execution breaks must be treated as stateful execution risk, not only as daily blocked-order counts.

### 2026-04-27 | Blocked-sell freeze needs active state exposure, not just same-day orders
- tags: v11, paper_broker, blocked_sell, p2
- reusable: yes
- confidence: high
- evidence: `PaperBroker` now reports `active_blocked_sell_state_weight`, `active_blocked_sell_state_notional`, `active_blocked_sell_state_max_consecutive_days`, and `blocked_exit_freeze_reason`; tests cover a second blocked-sell day where freeze reason becomes `same_day_exit_block+active_blocked_sell_state`.
- action: Diagnose buy freezes using both same-day `exit_not_tradable` orders and carried blocked-sell state exposure.

A blocked sell is a continuing risk-budget claim until the position exits or the strategy no longer wants to reduce it.

### 2026-04-27 | v10 promotion evidence separates main coverage gaps from candidate execution failure
- tags: v10, promotion, p2, empty_signal, v9
- reusable: yes
- confidence: high
- evidence: `output/backtest/promotion_decision_20260427_132220.json`; `quality_regime` 60/90/120 P2 now has `run_failed_days=0` and `empty_after_universe_filter_days=2` per window, while v9 has `empty_signal_days=0` but still fails hard gates with `target_weight_sum_mean=28.97%`, `broker_tradability_block_orders_sum=155`, `executable_pool_halt_days_total=30`, and `shadow_adv_blocked_rows_total=2421`.
- action: Treat main-profile BJ/9-code empty days as a signal/universe coverage gap; treat v9 failure as true execution pass-through failure, not an empty-signal artifact.

The v10 evidence split makes promotion review cleaner: fixing no-signal accounting does not rescue v9, because its bottleneck remains executable capacity, sell-side traps, and ADV/halt concentration.

### 2026-04-27 | v10 splits no-signal, executable-pool halt, and broker block evidence
- tags: v10, p2, promotion, evidence
- reusable: yes
- confidence: high
- evidence: `scripts/quant_p2_paper_trade.py` now writes `execution_state` values `empty_signal_raw`, `empty_after_universe_filter`, `executable_pool_halt`, and `normal`; rolling/shadow/promotion summaries expose separate empty-signal, halt, and broker tradability fields. Main-profile 20-day in-process replay returned `run_failed_days=0`, `empty_signal_days=2`, `empty_after_universe_filter_days=2`, and `empty_signal_rate_pct=10.0`.
- action: Use the three-way evidence split in future promotion reviews; do not count raw/BJ-only no-signal days as P2 process failures.

2026-03-19 and 2026-03-20 are BJ/9-code universe-filter-empty days, not broker failures.

### 2026-04-27 | Halt cluster attribution identifies different late-March failure modes
- tags: halt_cluster, p2, adv, style, sell_trap
- reusable: yes
- confidence: high
- evidence: `scripts/quant_p2_halt_cluster_attribution.py --p2-summary output/backtest/p2_rolling_replay_summary_latest_quality_regime.csv --profiles quality_regime --windows 20` labeled 2026-03-19/20 as `universe_filter_empty`, 2026-03-25 as `style_gate_collapse`, 2026-03-26 as `adv_capacity_collapse`, and the 2026-04-03 signal / 2026-04-07 trade date as `sell_trap`.
- action: Diagnose cluster days by label before changing strategy parameters; reserve pools only address replacement capacity and cannot fix universe-wide tradability or sell traps.

The late-March/early-April execution issue is not one bottleneck. It combines universe filtering, style/ADV collapse, and trapped sell exposure.

### 2026-04-27 | In-process P2 replay can match subprocess evidence while reducing startup cost
- tags: p2, replay, performance
- reusable: yes
- confidence: high
- evidence: v10 5-day quality_regime subprocess vs cached in-process replay matched `executed_days`, NAV, MDD, target-weight mean, empty-signal days, executable-pool halt days, and broker tradability block counts exactly.
- action: Use `quant_p2_rolling_replay.py --execution-mode inprocess` for promotion refresh smoke and long-window reruns, while keeping subprocess as fallback if parity breaks.

The in-process mode caches P2 market bars and reuses the profile module within a profile run; behavior parity remains the first gate before using it for formal promotion evidence.

### 2026-04-27 | Formal v9 promotion review correctly keeps main profile
- tags: promotion, v9, p2, rolling_compare, executable_pool_halt
- reusable: yes
- confidence: high
- evidence: Ran `quant_profile_rolling_compare.py` for `quality_regime` vs `quality_regime_candidate_v9_exec_state` over `2025-06-14` to `2026-04-14`, then ran same-script main-profile P2 60/90/120 and formal `quant_profile_promotion_review_20260427_123211`. Decision was `keep`; final default remains `quality_regime`. v9 research score was high (`199.96`) but hard gates failed: target_weight_sum_mean `28.97%`, executable_pool_halt_rate_mean `12.06%`, max halt days `10`, ADV blocked rows `2421`, max daily tradability blocked orders `34`.
- action: Keep v9 shadow. Do not interpret its research objective as promotion evidence until Sortino/metric sanity and execution hard gates pass.

Research score can be dominated by pathological path metrics. In this run v9's research-side objective was much higher than main, but promotion correctly rejected it because execution quality and capacity evidence did not pass.

### 2026-04-27 | Main profile also has BJ-only shared-daily evidence gaps
- tags: p2, quality_regime, daily_signal, evidence
- reusable: yes
- confidence: high
- evidence: Initial same-script replay showed `2026-03-19` and `2026-03-20` failed in 60/90/120 windows; v10 inspection corrected the cause: both shared daily files had 10 raw `920xxx` rows and became empty only after the default BJ/9-code universe filter.
- action: Treat BJ-only shared-daily files as a platform evidence-gap. Convert raw empty and post-universe-empty recommendation inputs into explicit no-signal ledger states before future promotion runs.

The incumbent being operationally weak does not make a candidate promotable. Main-profile evidence gaps should be fixed directly rather than used to lower the bar for v9.

### 2026-04-27 | Promotion gate must reject no-entry halt wins
- tags: promotion, executable_pool_halt, p2, v9
- reusable: yes
- confidence: high
- evidence: v9 no-entry replay produced `0/0/0` run failures but still had executable_pool_halt_days = `10/10/10`, mean halt rate about `12.06%`, and weak 90/120 NAV. `quant_profile_promotion_review.py` now aggregates halt days/rates and hard-rejects candidates above `5%` mean halt rate or `5` worst-window halt days.
- action: Keep halt evidence in promotion review and expert briefs. Treat no-entry/risk-off days as execution risk unless NAV/MDD, effective exposure, ADV, and halt-rate gates all pass.

Operational reliability is not alpha. A replay that succeeds because it stops entering positions must be separated from a replay that successfully fills executable alpha.

### 2026-04-27 | v9 no-entry replay separates executable-pool halts from sell traps
- tags: v9, p2, blocked_orders, entry_not_tradable, executable_pool_halt, promotion
- reusable: yes
- confidence: high
- evidence: Rebuilt 120 profile-isolated v9 daily files with zero failures and ran P2 60/90/120 after excluding the terminal signal date with no next market trade day. Pretrade-empty days now enter explicit no-entry/risk-off state instead of replay failure. NAV = +1.89%/-3.30%/-2.84%, MDD = -3.39%/-6.21%/-6.22%, target_weight_sum_mean = 25.1%/29.7%/32.1%, replay success days = 60/90/119, run failures = 0/0/0, executable_pool_halt_days = 10/10/10. Broker entry_not_tradable_orders = 0, broker exit_not_tradable_orders = 45/55/55, blocked_exit_buy_freeze_days = 6/6/6.
- action: Keep v9 shadow. Diagnose `2026-03-24` to `2026-03-26` and `2026-04-03` as executable-pool halt clusters; diagnose `2026-04-07` as a severe sell-side trap day where roughly 34 sell orders were blocked and about 35% current weight was trapped.

Reserve pool quality is not the main bottleneck when the executable pool collapses before broker execution. v9 improved evidence quality and blocked false buying power, but did not yet improve execution-alpha pass-through. Zero failed replay days are not a promotion-quality improvement when they are replaced by high no-entry halt rates and weak 90/120-day NAV/MDD.

### 2026-04-27 | Rolling replay must exclude signal dates without a next market trade day
- tags: p2, replay, evidence, calendar
- reusable: yes
- confidence: high
- evidence: v9 profile-isolated replay originally counted `2026-04-14` as a failed day in 60/90/120 windows only because local market data ended on `2026-04-14`; `quant_p2_paper_trade.py` logged `signal_date=2026-04-14 后无下一交易日，跳过。` Rolling replay now filters terminal signal dates using the market calendar before window selection.
- action: Treat endpoint/no-next-trade dates as data coverage artifacts, not strategy failures; keep the exclusion metadata in P2 replay artifacts for audit.

Execution coverage gates should measure tradable replay opportunities. Counting a local data endpoint as a failed execution day distorts promotion evidence and blocked-cluster diagnosis.

### 2026-04-27 | v9 should repair execution breaks before alpha/risk tuning
- tags: v9, reserve_pool, blocked_orders, p2
- reusable: yes
- confidence: high
- evidence: Implemented `quality_regime_candidate_v9_exec_state`, capacity-safe upstream reserve ranking (`portfolio_rank_score`), blocked-order state tracking in `PaperBroker`, and rolling replay summary fields for blocked-sell/freeze state evidence. Smoke rebuilt v9 `2026-03-27` and `2026-04-03` files at 40% target posture, then P2 smoke for `2026-03-30` and `2026-04-07` produced zero fills with blocked buy states visible.
- action: Use v9 to diagnose whether 2026-03-30 and 2026-04-07 style blocked clusters can be reduced without relaxing industry/ADV caps or raising exposure floors.

Capacity-safe reserves should be generated before portfolio/P2 pretrade, and blocked sells should become explicit state that can freeze new buys when trapped sell exposure is material. This prevents false cash reuse and makes late-March/early-April execution breaks reviewable.

### 2026-04-27 | Profile-specific signal calendars are mandatory for fair replay
- tags: p2, profile, evidence, replay
- reusable: yes
- confidence: high
- evidence: Initial v8 P2 replay mixed profile-specific v8 files with shared `output/daily` files for dates absent from `output/daily_profiles/quality_regime_candidate_v8_reserve_pool`; replay was stopped and `quant_p2_rolling_replay.py` was changed to use profile calendars when present.
- action: For profile evidence, rebuild `output/daily_profiles/<profile>/daily_*.csv` first and require rolling replay to select dates from that profile calendar.

Shared daily fallback can silently contaminate candidate replay because old default-profile daily files may not match the tested profile's reserve pool, target weights, or gates.

### 2026-04-27 | v8 improves invested weight but fails execution-alpha validation
- tags: v8, p2, reserve_pool, alpha, promotion
- reusable: yes
- confidence: high
- evidence: v8 profile-isolated P2 60/90/120 NAV = -5.33%/-11.74%/-16.09%, MDD = -8.10%/-12.78%/-16.79%, target_weight_sum_mean = 34.3%/36.1%/37.2%; alpha attribution shows negative forward return for raw ML top, optimizer, and P2 fill stages.
- action: Keep v8 shadow; next work should improve capacity-safe reserve quality and blocked-order state handling before loosening risk constraints or promoting.

Reserve pool raised effective target weight compared with v7, but the higher exposure revealed weak execution-layer alpha and severe ADV/tradability blocking.

### 2026-04-26 | Reserve pool must enter before optimizer and P2 pretrade
- tags: reserve_pool, p2, capacity, tradability
- reusable: yes
- confidence: high
- evidence: Implemented `quality_regime_candidate_v8_reserve_pool`, `PortfolioConstraints.max_names`, daily reserve candidates, and P2 pretrade re-optimization.
- action: Feed expanded candidate pools into portfolio/pretrade, but keep primary topN as the initial weight budget; reserve rows should receive weight only after capacity/tradability/industry clips.

Reserve candidates cannot be appended only after execution. They must be visible before capacity clipping and before P2 pretrade so blocked buys and low-capacity names can be replaced instead of leaving cash.

### 2026-04-26 | Promotion needs target-weight source and checksum evidence
- tags: promotion, checksum, target_weight, p2
- reusable: yes
- confidence: high
- evidence: Added `target_weight_checksum`, `target_weight_source_external_rate_pct`, and checksum coverage into P2 rolling summaries and promotion hard gates.
- action: Reject candidates whose P2 ledger did not use external optimizer weights or whose target-weight checksum coverage is incomplete.

Target-weight consistency must be a first-class promotion artifact, not an informal assumption.

### 2026-04-26 | P2 execution evidence must use the canonical broker path
- tags: p2, target_weight, execution, promotion
- reusable: yes
- confidence: high
- evidence: External expert review flagged that legacy script-level `_rebalance` in `scripts/quant_p2_paper_trade.py` could recompute score weights and double-scale total position, while `core.execution.paper_broker.PaperBroker` already respected external `target_weight`.
- action: Keep P2 rolling replay on the canonical broker path; any compatibility wrapper must delegate to `PaperBroker.rebalance_on_state` and preserve `target_weight_source`.

Promotion evidence is only trustworthy if daily target weights, P2 requested weights, and ledger weights share one execution implementation.

### 2026-04-26 | Signal pretrade defaults must be research-safe
- tags: pretrade, lookahead, research_safe, a_share
- reusable: yes
- confidence: high
- evidence: External expert review highlighted that default next-trade-day pretrade checks in daily selection could leak ex-post tradability into research candidates.
- action: Default `MFTS_SIGNAL_PRETRADE_USE_NEXT_TRADE_DAY` to false in `daily_ml_select.py`; use explicit next-day mode only for replay/expost diagnostics.

T+1 tradability is execution evidence, not a default research input.

### 2026-04-26 | v7 industry balance reduces industry concentration but fails promotion
- tags: p2, promotion, industry, adv, target_weight
- reusable: yes
- confidence: high
- evidence: `output/backtest/promotion_decision_latest.json`; v7 NAV 60/90/120 = -0.67%/-1.08%/-1.13%; ADV blocked rows = 105; target weight mean = 21.03%/27.03%/30.52%
- action: Do not promote candidates that win by carrying cash or only reducing industry concentration; require NAV parity and effective target weight.

v7 improved invested-weight industry concentration to 31.86%, but the execution path failed long-window NAV parity and left too much cash in 60/90-day windows.

### 2026-04-26 | Industry concentration needs invested and NAV-weight views
- tags: shadow, industry, diagnosis
- reusable: yes
- confidence: high
- evidence: `output/backtest/quant_p2_shadow_diagnosis_latest.csv`
- action: Use invested-weight concentration for crowding and NAV-weight concentration for cash-adjusted exposure; do not rely on a single top-industry metric.

Invested concentration shows whether the active book is crowded. NAV-weight concentration shows whether low concentration is just a byproduct of low invested weight.

### 2026-04-26 | Research-side annualized return can be misleading when hard-pass rate is zero
- tags: research, rolling_compare, overfit
- reusable: yes
- confidence: medium
- evidence: `output/backtest/quant_profile_rolling_compare_summary_latest.csv`; v7 annual_return_mean positive but hard_pass_rate = 0 and P2 failed
- action: Treat positive rolling annual return with zero hard-pass rate as diagnostic only, not promotion evidence.

The latest v7 rolling compare looked attractive on mean annual return, but path quality and execution evidence did not support promotion.

### 2026-04-26 | Alpha attribution must state artifact limitations
- tags: attribution, alpha, evidence
- reusable: yes
- confidence: high
- evidence: `scripts/quant_alpha_execution_attribution.py`
- action: When only daily recommendation files exist, label raw/quality/refactor attribution as recommendation-proxy attribution, not full-universe raw prediction attribution.

The project currently persists daily candidate recommendations, not necessarily the full raw ML prediction universe. Diagnostics must be honest about this boundary.

### 2026-04-27 | Explicit zero target weights must remain risk-off in P2
- tags: p2, target_weight, holiday_gap, risk_off
- reusable: yes
- confidence: high
- evidence: v17 work required the ability to express a very low or zero pre-holiday target budget. `PaperBroker` and `quant_p2_paper_trade.py` now treat a present `target_weight` column as authoritative even when all weights are zero, instead of falling back to score weights.
- action: Use explicit zero/low `target_weight` daily files for risk-off or pre-holiday unwind experiments; verify `target_weight_source=external_target_weight` and `upstream_target_weight_overrun_max=0` before interpreting replay results.

Risk-off is a portfolio instruction, not a missing-signal condition. A zero upstream target budget must not be silently re-expanded at the broker layer.

### 2026-04-27 | v16 has cleaner lineage but still fails promotion-quality evidence
- tags: v16, promotion, p2, sell_trap
- reusable: yes
- confidence: high
- evidence: v16 profile-isolated daily rebuild produced 121/121 files successfully. Fixed-lineage 60/90/120 P2 NAV was about `-1.77%/-2.14%/-2.84%`, MDD about `-6.39%/-6.37%/-6.36%`, target-weight mean about `32.0%/31.6%/31.1%`, and `upstream_target_weight_overrun_max=0`. Promotion review `20260427_183644` rejected v16 for weak research rolling evidence, P2 objective below main, tradability block clusters, severe sell traps, reserve-sourced sell traps, and executable-pool halt hard gates.
- action: Do not promote v16. Treat it as the clean holiday-gap baseline for future sell-trap unwind experiments.

Fixing target-budget lineage made the evidence trustworthy, but it did not create alpha or remove exit traps.

### 2026-04-27 | v17 reduces sell-trap exposure mostly by holding too much cash
- tags: v17, holiday_gap, sell_trap, cash_drag
- reusable: yes
- confidence: high
- evidence: v17 10/20-day smoke reduced max blocked-sell current weight to about `4.3%` versus v16 same-window about `14.5%`, but target-weight mean collapsed to about `9.0%/5.8%` and executable-pool halt days rose to `2/8`.
- action: Keep v17 shadow as an extreme-risk diagnostic. Next iteration should search for a middle guard, such as moderate pre-holiday caps or position-level unwind rules, and must enforce target-weight floors before promotion.

Lower trapped exposure is not enough if the mechanism is mostly not investing.

### 2026-04-27 | Missing volume with positive amount is tradable evidence, not suspension
- tags: data_quality, p2, tradability, a_share
- reusable: yes
- confidence: high
- evidence: v18 long-window P2 initially showed 65 broker `entry_not_tradable` orders and max blocked-sell weight around `8.6%`. Inspection of 2026-03-25/2026-03-26 orders found valid open prices and positive `amount` but missing `vol`; after treating `amount > 0` or `vol > 0` as tradability evidence, broker entry blocks fell to `0` and max blocked-sell weight fell to about `0.16%`.
- action: Suspension checks in P2, portfolio backtest, and sell-trap diagnostics should require invalid price or no positive amount/volume evidence; missing `vol` alone must not create entry/exit traps.

Cleaner tradability evidence can worsen NAV because previously skipped buys now execute. That is a good credibility fix, not an alpha improvement.

### 2026-04-27 | Profile rebuild force mode must remove stale daily outputs
- tags: daily_signal, profile, replay, evidence
- reusable: yes
- confidence: high
- evidence: v18 121-day rebuild failed on five January/February dates, but stale profile-specific daily files could remain and contaminate the profile replay calendar. `quant_rebuild_profile_daily_signals.py --force` now removes the target output before generation and removes any output left behind after failure.
- action: Treat failed profile daily generation as absent signal evidence, not as permission to reuse old files. Rolling replay should report profile signal calendar coverage and promotion should hard-fail calendar shortfall.

Profile-isolated replay is only profile-isolated if failed rebuild dates cannot silently fall back to stale signals.

### 2026-04-27 | v18 balanced trap guard fixes false traps but does not pass promotion
- tags: v18, p2, promotion, alpha
- reusable: yes
- confidence: high
- evidence: After stale-daily cleanup and missing-volume tradability fix, v18 60/90/120 P2 had `run_failed_days=0`, signal calendar shortfall `0`, target-weight mean about `33.3%/32.8%/33.7%`, broker entry blocks `0/0/0`, and max blocked-sell weight around `0.15%/0.15%/0.16%`; NAV was about `-2.91%/-2.91%/-6.05%` and MDD about `-7.63%/-7.63%/-7.66%`.
- action: Do not promote v18. Use it as a cleaner execution-credibility baseline, then refresh the main profile and prior candidates under the corrected tradability口径 before comparing strategy quality.

Removing false non-execution exposed weaker realized alpha. The next problem is selection/alpha quality under clean execution, not loosening risk controls.

### 2026-04-27 | Corrected tradability口径 keeps v18 in shadow after formal review
- tags: v18, promotion, p2, baseline
- reusable: yes
- confidence: high
- evidence: After refreshing `quality_regime` under the missing-volume fix, main 60/90/120 P2 NAV was about `-3.60%/-6.41%/-3.58%`, MDD about `-4.63%/-6.85%/-7.16%`, target-weight mean about `28.9%/25.8%/25.6%`, empty-signal days total `6`, and executable-pool halt days total `39`. Formal review `20260427_210319` kept the default as `quality_regime`; v18 failed hard gates for long-window MDD parity, MDD worse than main, and tradability blocked orders worse than main.
- action: Treat v18 as a cleaner but non-promotable shadow. Before designing the next candidate, refresh old baselines under the same tradability/data-quality口径 and focus on alpha quality plus reducing executable-pool halts without sacrificing MDD.

A candidate with higher target utilization and some NAV improvement is still not promotion-grade if it buys into worse drawdown and blocked-order exposure.

### 2026-04-27 | Local frontend should launch through the stock environment wrapper
- tags: ops, web, local_run
- reusable: yes
- confidence: high
- evidence: The repository has no project-local `.venv`; the working local environment is `/opt/homebrew/Caskroom/miniforge/base/envs/stock/bin/python`. `scripts/start_web.sh` starts `web/app.py` on `127.0.0.1:5001` inside a `screen` session named `stock_screener_web` and safely detects an existing session.
- action: Use `scripts/start_web.sh` for local frontend startup. Stop it with `screen -S stock_screener_web -X quit`. Override the interpreter with `MFTS_PYTHON=/path/to/python` if the machine uses a different environment.

The frontend can be opened at `http://127.0.0.1:5001`; `/health` may be stricter than page availability if local data/artifacts are incomplete.

### 2026-04-28 | v19/v20 show ranking-blend tweaks are not yet fixing alpha pass-through
- tags: v19, v20, alpha_diagnosis, reserve_pool, ranking
- reusable: yes
- confidence: high
- evidence: Recommendation-proxy diagnostics for v18 showed liquidity/quality scores were less bad than final `portfolio_rank_score`, so v19 shifted reserve/ranking blends toward liquidity and quality without loosening ADV/industry/style caps. v19 still had `portfolio_rank_score/target_weight` top forward return around `-0.86%` over the 105-day sample and 20-day P2 NAV about `-1.65%` with MDD about `-3.36%`. A follow-up v20 added `capacity_safe_primary_rank_mode=blend_full_pool` so reserve-safe candidates could enter the primary ranking; the recent smoke diagnostic was worse, with `target_weight/portfolio_rank_score` top forward return around `-3.31%` versus candidate-pool average about `-2.40%`.
- action: Do not promote or long-window v19/v20 unless a refreshed score-level diagnostic first shows final target-weight ranking beating the candidate-pool average. The next productive path is alpha attribution and candidate-pool construction quality, not more blind blend tuning.

Reserve pool mechanics can improve execution coverage, but they do not create alpha when the scores that reach target weights remain negatively sorted.

### 2026-04-28 | Stage snapshots show raw liquidity alpha is mostly concentrated industry exposure
- tags: alpha_diagnosis, research_stage, industry_crowding, v18
- reusable: yes
- confidence: high
- evidence: `research_stage_profiles/quality_regime_candidate_v18_balanced_trap_guard` stage diagnostics over 2026-03-12 to 2026-04-13 showed raw-scored liquidity top-20 forward return about `+2.87%` versus raw universe average about `-1.36%`, but the top industry label was `计算机、通信和其他电子设备制造业` and top-industry concentration was about `73%`. After filters/pretrade/optimizer/final target, final `target_weight` top forward return was about `-0.90%` versus final pool average about `-0.42%`.
- action: Treat raw liquidity as a theme/crowding hypothesis, not promotion-grade alpha. Keep industry caps in portfolio/pretrade and use stage snapshots before designing new blends, so the project can see where alpha is consumed.

The current chain appears to be suppressing a crowded raw theme, but the remaining diversified target-weight ranking still lacks positive alpha.

### 2026-04-28 | v21 target ML score improves 20-day loss mostly by cutting exposure
- tags: v21, target_score_col, p2, cash_drag
- reusable: yes
- confidence: high
- evidence: `target_score_col` is now honored by `_assign_target_weights`. v21 (`quality_regime_candidate_v21_target_ml_score`) used `ml_score` for target weights and 20-day P2 improved NAV/MDD versus v18 (`-1.53%/-2.05%` versus `-2.55%/-4.06%`), but average target weight fell to about `18.3%`, risk block rate rose to about `76.6%`, executable-pool halt days rose to `3`, and objective was worse than v19.
- action: Do not long-window or promote v21 as-is. A target-score override is useful diagnostically, but candidates that improve losses by failing to deploy capital should be rejected by target-weight floors before promotion work.

Lower loss from lower realized exposure is not alpha, even when the code path is cleaner.

### 2026-04-28 | Stage transition diagnostics identify low-volume hard filtering as an alpha attrition point
- tags: alpha_diagnosis, research_stage, tradability_filter, vol_ratio
- reusable: yes
- confidence: high
- evidence: v18 stage transition diagnostics over 2026-03-12 to 2026-04-13 showed raw -> tradability kept rows had mean forward return about `-3.49%`, while dropped rows had about `-0.17%`. After splitting flags, about `91.5%` of dropped rows were `vol_anomaly_low_flag`; these rows were not empty-trading artifacts because about `99.95%` had positive amount and amount MA20 was positive.
- action: Treat low-vol hard filtering as a suspect attrition point, but do not simply disable it. v22 disabled the low-vol hard filter and improved early pool statistics, yet final target and P2 evidence remained weak, so the useful path is more selective post-liquidity/pretrade scoring rather than broad filter relaxation.

Relative low volume is not the same thing as no executable capacity. Signal-day amount and downstream ADV/pretrade constraints must decide capacity.

### 2026-04-28 | NAV-weighted style exposure fixes execution halt but exposes weak alpha
- tags: pretrade, style_exposure, v23, p2, alpha
- reusable: yes
- confidence: high
- evidence: The old pretrade style gate used invested-average exposure, so a first 2.6% entry could be blocked because its raw style z-score exceeded the threshold. v23 switched style exposure to NAV-weighted. In the 20-day smoke, executable-pool halt days fell from `16` to `0` and target-weight mean rose from about `2.24%` to `36.65%`, but NAV/MDD worsened from about `-0.93%/-0.93%` to `-3.14%/-4.15%`.
- action: Keep `risk_style_exposure_basis=nav_weighted` as the more credible execution口径 for diagnostics, but do not promote v23. The next optimization target is post-filter alpha quality and loss avoidance under real exposure, not returning to cash-generating style gates.

A style gate that keeps the strategy safe by preventing almost all buys is not alpha. Fixing the口径 can make losses worse, and that is valuable evidence.

### 2026-04-28 | Codex engineering discipline is now a first-class project reference
- tags: codex, process, skill, maintenance
- reusable: yes
- confidence: high
- evidence: The project now has `skills/audit-a-share-quant-project/references/codex-engineering-discipline.md`, adapted from the MIT-licensed `forrestchang/andrej-karpathy-skills` ideas but rewritten for this A-share quant repository and Codex workflows. `AGENTS.md`, `agent.md`, `README.md`, `docs/README.md`, `docs/PROJECT_INDEX.md`, the audit skill, and the maintenance loop now point to it.
- action: For non-trivial strategy, execution, promotion, architecture, or maintenance work, read and apply this reference: surface material assumptions, keep patches surgical, preserve research-to-execution evidence lineage, define verification before coding, and avoid treating cash drag as alpha.

The external expert-review loop remains an escalation path, not a per-iteration habit.

### 2026-04-28 | Maintenance snapshot now tracks architecture-size risk
- tags: architecture, maintenance, skill, code_health
- reusable: yes
- confidence: high
- evidence: `skills/audit-a-share-quant-project/scripts/build_maintenance_snapshot.py` now reports total Python lines, file/line counts by directory, largest Python files, and large production files with warn/high/critical thresholds. The current snapshot shows 47,570 Python lines across 173 scanned files and 13 large production files; `scripts/daily_ml_select.py` and `scripts/quant_portfolio_backtest.py` are critical-size orchestration risks.
- action: Use the snapshot before recurring architecture work. Treat large-file flags as refactor evidence, not a mandate for broad rewrites; extract testable helpers only when changing those production paths for a concrete execution, backtest, data, or promotion improvement.

Architecture health should become measurable drift control. The next useful cleanup is targeted helper extraction around confirmed hot paths, not cosmetic reshuffling.

### 2026-04-28 | Documentation and skill ownership is now explicit
- tags: docs, skill, governance, maintenance
- reusable: yes
- confidence: high
- evidence: Added `docs/DOCUMENTATION_AND_SKILLS.md` to define documentation source-of-truth hierarchy, the single repo-local skill inventory, intentional duplicates (`AGENTS.md` vs `agent.md`, expert brief vs expert prompt), and stale-doc risks. Updated README, docs index, project index, workflow, local guide, expert-review docs, and the audit skill metadata to reflect `quality_regime` as the current default and v7-v23 as shadow/diagnostic candidates.
- action: Do not create parallel project skills unless the trigger boundary is stable and clearly separate from `audit-a-share-quant-project`. Before external expert review, refresh expert brief/prompt plus latest P2/shadow/promotion evidence instead of copying stale history.

Docs should route evidence, not replace it. Current truth remains fresh artifacts, profile config, promotion review, and memory.

### 2026-04-28 | Score alpha smoke gate now blocks expensive P2 work when final ranking is weak
- tags: alpha_diagnosis, score_gate, target_weight, p2_efficiency
- reusable: yes
- confidence: high
- evidence: `scripts/quant_score_alpha_diagnosis.py` now emits `alpha_quality_gate` and supports `--enforce-alpha-gate`. The gate checks whether `target_weight` or `portfolio_rank_score` top buckets beat the candidate-pool average, beat the bottom bucket, and have positive RankIC. Fresh runs rejected both v23 and v18: v23 `target_weight` top-minus-all was about `-1.20pp` and `portfolio_rank_score` top-minus-all about `-1.85pp`; v18 `target_weight` top-minus-all was about `-0.66pp` and `portfolio_rank_score` top-minus-all about `-0.71pp`.
- action: Before running costly 60/90/120 P2 windows for a new ranking/target-weight profile, run `quant_score_alpha_diagnosis.py --enforce-alpha-gate` on profile-isolated daily files. If the gate fails, stop and improve candidate construction or scoring before P2 long-window work.

Execution repair can make a weak ranking more honestly invested. The first gate is now whether the final target-weight ordering has positive recommendation-proxy alpha.

### 2026-04-28 | Promotion review now consumes score-alpha evidence
- tags: promotion, alpha_diagnosis, score_gate, governance
- reusable: yes
- confidence: high
- evidence: `scripts/quant_profile_promotion_review.py` now accepts `--score-alpha-diagnosis` JSON/CSV inputs. JSON artifacts from `quant_score_alpha_diagnosis.py` activate a hard gate: when a candidate's `target_weight` / `portfolio_rank_score` alpha-quality smoke fails, promotion review records `score_alpha_gate_failed` and keeps the default. A real v18 smoke review produced `decision=keep`, `final_default=quality_regime`, and hard reason `score_alpha_gate_failed`.
- action: Include the latest score-alpha JSON in formal promotion review whenever evaluating a new ranking or target-weight profile. A candidate with weak final ranking alpha should not proceed to promotion even if P2 NAV looks temporarily better.

Final-ranking alpha evidence belongs in the same governance artifact as P2, ADV, halt, and industry evidence. Separate diagnostics are useful; promotion decisions need the joined view.

### 2026-04-28 | Promotion refresh now auto-attaches score-alpha latest JSON
- tags: promotion, automation, score_gate, governance
- reusable: yes
- confidence: high
- evidence: `scripts/quant_refresh_promotion_gate.py` now discovers `output/backtest/quant_score_alpha_diagnosis_latest_<profile>.json` for the profiles being reviewed and passes them to `quant_profile_promotion_review.py --score-alpha-diagnosis`. Focused tests cover both the no-artifact path and the auto-attach path.
- action: For a formal promotion refresh, generate or refresh score-alpha JSON for any active candidate first. If no score-alpha latest JSON exists, refresh remains backward compatible but the final-ranking alpha hard gate will not be active for that candidate.

Automation should preserve the same evidence bundle used in manual review. Otherwise a good hard gate can become a side diagnostic that humans forget to attach.

### 2026-04-28 | Promotion refresh can actively rebuild score-alpha evidence
- tags: promotion, automation, score_gate, evidence_lineage
- reusable: yes
- confidence: high
- evidence: `scripts/quant_refresh_promotion_gate.py --refresh-score-alpha` now discovers profile-isolated daily files under `output/daily_profiles/<profile>/daily_*.csv`, runs `quant_score_alpha_diagnosis.py --write-latest` for candidate profiles, and then attaches the resulting `quant_score_alpha_diagnosis_latest_<profile>.json` to promotion review. Tests cover profile daily discovery, active score-alpha refresh command generation, explicit evidence override, and no-artifact backward compatibility.
- action: Use `--refresh-score-alpha` for formal candidate refreshes before expensive or promotion-facing P2 evidence. If no profile-isolated daily files exist, the refresh correctly skips that profile instead of falling back to shared daily evidence.

Score-alpha evidence should be generated from the same profile-isolated daily files that P2 uses. Shared daily fallback is not acceptable for candidate promotion evidence.

### 2026-04-28 | Score-alpha precheck can prune candidates before expensive P2 refresh
- tags: promotion, automation, score_gate, p2_efficiency
- reusable: yes
- confidence: high
- evidence: `scripts/quant_refresh_promotion_gate.py --precheck-score-alpha` now keeps the main profile, checks candidate `quant_score_alpha_diagnosis_latest_<profile>.json` files, and removes candidates whose `alpha_quality_gate.pass` is false or missing before running rolling compare, P2 replay, shadow diagnosis, funnel, and promotion review. Combined with `--refresh-score-alpha`, the refresh first rebuilds profile-isolated score-alpha evidence and then prunes failed candidates. Tests cover pass/fail JSON parsing, candidate filtering, active refresh order, stale-file avoidance, and effective `--profiles` propagation into downstream commands.
- action: Use `--refresh-score-alpha --precheck-score-alpha` for formal candidate sweeps when the goal is to avoid spending 60/90/120 P2 cycles on final rankings that already fail recommendation-proxy alpha. Do not use precheck as a promotion substitute; it only decides which candidates deserve expensive execution evidence.

The cheap gate should happen before the expensive gate. Passing score-alpha smoke is necessary for P2 spend, not sufficient for promotion.

### 2026-04-28 | Score-alpha precheck now leaves auditable skip evidence
- tags: promotion, automation, score_gate, evidence_lineage
- reusable: yes
- confidence: high
- evidence: `scripts/quant_refresh_promotion_gate.py --precheck-score-alpha` now writes `output/backtest/quant_score_alpha_precheck_latest.json` and `.csv`, with requested profiles, effective profiles, skipped profiles, score-alpha file paths, gate pass flags, and skip reasons. Tests cover missing evidence, failed gates, explicit artifact labels, and latest report output.
- action: When a candidate is pruned before 60/90/120 P2, cite the precheck latest artifact instead of relying on console logs. This keeps the skipped-candidate decision visible to promotion review operators and external reviewers.

Skipping P2 is also a decision. It needs evidence lineage, because otherwise efficiency tooling can look like silent cherry-picking.

### 2026-04-28 | Promotion refresh has a precheck-only mode for cheap candidate pruning
- tags: promotion, automation, score_gate, p2_efficiency
- reusable: yes
- confidence: high
- evidence: `scripts/quant_refresh_promotion_gate.py --precheck-only` now automatically runs score-alpha precheck, writes `quant_score_alpha_precheck_latest.json/csv`, and exits before rolling compare, P2 replay, shadow diagnosis, funnel, or promotion review. Full tests passed after the change.
- action: Use `--refresh-score-alpha --precheck-only` as the first pass for broad candidate sweeps. Only run expensive 60/90/120 P2 refresh for candidates that survive the cheap final-ranking alpha gate.

This keeps the project honest and faster: failed final rankings get an auditable skip reason instead of silently consuming replay time.

### 2026-04-28 | Broad candidate precheck leaves only four current shadow profiles worth P2 spend
- tags: promotion, score_gate, candidate_sweep, alpha_diagnosis
- reusable: yes
- confidence: medium
- evidence: A real `quant_refresh_promotion_gate.py --end 2026-04-14 --refresh-score-alpha --precheck-only` run requested 22 profiles and kept only `quality_regime`, `quality_regime_candidate_v14_exit_trap_budget`, `quality_regime_candidate_v15_volume_drought_trap`, `quality_regime_candidate_v17_holiday_exit_trap_guard`, and `quality_regime_candidate_v22_relaxed_low_volume_gate`. It skipped 10 candidates for `score_alpha_gate_failed/no_gate_score_passed` and 7 older candidates for missing profile-isolated daily evidence.
- action: Do not spend fresh 60/90/120 P2 on v8, v9, v18, v19, v20, v21, or v23 unless their profile-isolated daily ranking is rebuilt and passes score-alpha smoke. If continuing candidate work, start from the four precheck survivors, then apply P2/sell-trap/promotion hard gates.

This is not promotion evidence. It is a cheap narrowing step that says which candidates deserve the expensive evidence pass.

### 2026-04-28 | Score-alpha survivors still fail execution-quality smoke
- tags: p2, score_gate, sell_trap, coverage, cash_drag
- reusable: yes
- confidence: high
- evidence: A 60-day in-process P2 smoke on `quality_regime` plus score-alpha survivors kept by precheck showed `quality_regime` NAV `+1.18%` with MDD `-5.89%`; `v17_holiday_exit_trap_guard` NAV `-0.23%` and MDD `-1.21%` but target-weight mean only `13.66%`; `v22_relaxed_low_volume_gate` target-weight mean `35.07%` but NAV/MDD `-0.91%/-2.62%`; `v14` and `v15` both lost about `-3.22%` with 10 signal days, 6 exit-not-tradable orders, and invested top industry above `51%`. Shadow diagnosis confirmed v14/v15 worst top industry reached `100%`, while halt attribution showed v14/v15 sell traps around 2026-03-30/2026-03-31.
- action: Do not promote or spend full 90/120 windows on these candidates before rebuilding profile-isolated daily coverage and fixing concentration/sell-trap behavior. Treat v17's lower loss as cash drag until target-weight utilization reaches promotion floors. Treat v22 as the only survivor with plausible utilization, but it needs better realized NAV/MDD before long-window spend.

Passing final-ranking score-alpha is only the first gate. The current survivors still fail execution-quality or coverage gates.

### 2026-04-28 | Promotion refresh now gates profile daily coverage before P2 spend
- tags: promotion, signal_calendar, p2_efficiency, evidence_lineage
- reusable: yes
- confidence: high
- evidence: `scripts/quant_refresh_promotion_gate.py --precheck-signal-coverage` now counts replayable profile-isolated daily files before running rolling/P2/shadow/funnel/promotion. A real `--end 2026-04-14 --precheck-score-alpha --precheck-signal-coverage --precheck-only` run first kept score-alpha survivors `v14/v15/v17/v22`, then rejected all four for insufficient replayable profile signal days: v14/v15 had `10/60`, and v17/v22 had `20/60`. The final effective profile list was only `quality_regime`.
- action: Use `--precheck-score-alpha --precheck-signal-coverage --precheck-only` before broad 60/90/120 refreshes. A profile must pass both final-ranking alpha smoke and signal-calendar coverage before it deserves long-window P2. Cite `output/backtest/quant_signal_coverage_precheck_latest.json` when explaining why a candidate was skipped.

This closes the loophole where a candidate with only 10-20 profile signal days could consume or be described as 60-day execution evidence.

### 2026-04-28 | Profile daily rebuild should use replayable dates and explicit metadata staleness
- tags: daily_signal, profile_rebuild, signal_calendar, p2_efficiency
- reusable: yes
- confidence: high
- evidence: `scripts/quant_rebuild_profile_daily_signals.py` now supports `--replayable-only` to exclude signal dates without a next market trade day before selecting the rebuild window, and `--max-metadata-staleness-days` to pass an explicit historical metadata freshness threshold into `daily_ml_select.py`. A real v22 rebuild with `--days 70 --replayable-only --max-metadata-staleness-days 999` produced 65 replayable profile daily files before `20260414`; v22 then passed score-alpha and signal-coverage prechecks.
- action: Before 60/90/120 profile-isolated P2, rebuild candidate daily files with `--replayable-only` and enough lookback days to survive genuine no-data failures. Do not fabricate failed dates; extend the replayable window or record the coverage gap.

Promotion evidence needs a clean signal calendar. A candidate can pass score-alpha only after enough replayable daily files exist.

### 2026-04-28 | P2 smoke fail-fast prevents expensive long-window spend on execution losers
- tags: promotion, p2_efficiency, smoke_gate, execution_quality
- reusable: yes
- confidence: high
- evidence: `scripts/quant_refresh_promotion_gate.py --fail-fast-p2-smoke-window 60` now runs a 60-day P2 smoke after score-alpha and signal-coverage prechecks but before rolling compare, long-window P2, shadow, funnel, or promotion refresh. A real v22 smoke produced main `quality_regime` NAV/MDD `+1.18%/-5.89%` and target-weight mean `41.07%`; v22 had `-1.91%/-7.71%`, target-weight mean `34.25%`, and exit-not-tradable orders `7` versus main `3`, so the smoke precheck skipped v22 and stopped the long-window refresh.
- action: Use `--precheck-score-alpha --precheck-signal-coverage --fail-fast-p2-smoke-window 60 --p2-execution-mode inprocess` before spending on 90/120 P2. A smoke skip is not a promotion decision; it is auditable evidence that the candidate does not deserve expensive execution refresh yet.

Research-side survival is not enough. A candidate that loses to the main profile in 60-day execution smoke should not consume long-window promotion cycles.

### 2026-04-28 | Signal coverage must be same-calendar coverage, not just enough rows
- tags: signal_calendar, promotion, p2, evidence_lineage
- reusable: yes
- confidence: high
- evidence: `quant_refresh_promotion_gate.py --precheck-signal-coverage` now checks whether a candidate covers the same replayable shared signal dates used as the main-profile reference window. A real v22 precheck had `65/60` replayable profile daily files, but still failed as `profile_signal_calendar_mismatch` because it missed five reference dates: `20260126,20260127,20260128,20260203,20260205`.
- action: Treat candidate daily coverage as a date-set parity requirement. A candidate that reaches 60 rows by pulling in earlier dates is not valid 60-day same-generation evidence against `quality_regime`.

Count coverage is necessary but not sufficient. Promotion comparisons need the same market days, not just the same number of rows.

### 2026-04-28 | P2 reference calendars must exclude stale daily files without market bars
- tags: signal_calendar, data_quality, p2, promotion
- reusable: yes
- confidence: high
- evidence: The shared `output/daily` folder contained `daily_20260126`, `20260127`, `20260128`, `20260203`, and `20260205`, but `data/daily_all_5y.parquet` had zero market rows for those dates. `quant_p2_rolling_replay.py` and `quant_refresh_promotion_gate.py` now exclude signal dates that do not exist in the market trade-date set. After this fix, v22 passed same-calendar signal coverage, but the clean 60-day P2 smoke still failed versus `quality_regime`: main NAV/MDD `+4.73%/-5.84%`, v22 `-1.91%/-7.71%`, and v22 exit-not-tradable orders `7` versus main `3`.
- action: Treat daily recommendation files without corresponding market bars as stale/orphan artifacts. They must not enter rolling replay windows or promotion reference calendars.

Signal files alone are not a market calendar. P2 evidence must be anchored to the same data source used for execution prices and tradability.

### 2026-04-29 | P2 smoke failures now have a first-class attribution report
- tags: p2, smoke_gate, attribution, sell_trap, evidence_lineage
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_p2_smoke_failure_diagnosis.py`, which joins P2 smoke precheck, score-alpha JSON, rolling summary, and main/candidate ledgers. `scripts/quant_refresh_promotion_gate.py --fail-fast-p2-smoke-window 60` now triggers it automatically when a candidate is skipped. The latest v22 run labels `quality_regime_candidate_v22_relaxed_low_volume_gate` as `sell_trap_or_exit_block`: score-alpha gate passed on `target_weight`, but 60-day P2 NAV lagged the main profile by `-6.64pct`, MDD lagged by `-1.88pct`, target-weight mean was `-8.51pct` lower, and broker exit-not-tradable orders were `7` versus main `3`. Full tests passed: `328 passed, 3 skipped`.
- action: After a candidate passes score-alpha and signal-calendar coverage but fails 60-day P2 smoke, use `quant_p2_smoke_failure_diagnosis_latest.csv/json` before any new profile tweak or 90/120 replay. Use the failure label to choose the next workstream: sell trap, cash drag, calendar mismatch, entry tradability, or score-alpha not executed.

Do not let a P2 smoke skip become a black box. A failed candidate should leave a compact explanation table before the next experiment starts.

### 2026-04-29 | Worst P2 failure days need order-level attribution
- tags: p2, attribution, sell_trap, cash_drag, holiday_gap
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_p2_failure_day_attribution.py` and wired it into `quant_refresh_promotion_gate.py` after P2 smoke failure diagnosis. On the latest v22 smoke failure, the worst relative signal day `2026-01-19` is labeled `holiday_gap_cash_drag+sell_trap`: candidate target weight was about `12%` versus main `48%` because `holiday_gap_target_scale=0.3` from `signal_to_trade_gap+post_trade_gap`; candidate also had one blocked sell (`600415`) and four `entry_not_tradable` risk-gate rows. Full tests passed: `330 passed, 3 skipped`.
- action: When a smoke failure label is broad, inspect `quant_p2_failure_day_attribution_latest.csv`, `quant_p2_failure_day_orders_latest.csv`, and `quant_p2_failure_day_risks_latest.csv` before changing profile parameters. Distinguish window-level sell-trap parity from day-level cash drag or holiday-gap suppression.

A window can fail for one dominant aggregate reason while the worst day is mixed. Diagnose the day before deciding the next profile hypothesis.

### 2026-04-29 | Holiday-gap guard now has reason-level attribution
- tags: p2, holiday_gap, cash_drag, sell_trap, attribution
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_p2_holiday_gap_guard_attribution.py` and wired it into `quant_refresh_promotion_gate.py` after fail-fast P2 smoke skips. On the latest v22 60-day evidence, `post_trade_gap` and `signal_to_trade_gap` each had four guard days and were classified as `effective_protection`, while the single `signal_to_trade_gap+post_trade_gap` day was `insufficient_sample` and carried `-2.10pct` relative return, about `0.705pct` cash-drag proxy, target-weight gap about `-36.0pct`, and one exit block on 2026-01-19.
- action: Use `quant_p2_holiday_gap_guard_reason_summary_latest.csv` and `quant_p2_holiday_gap_guard_day_detail_latest.csv` before changing holiday-gap policy. Treat reason-level verdicts as attribution evidence only; do not promote, disable, or loosen a guard from aggregate window metrics alone.

Holiday-gap guard can be protective for some gap reasons and damaging or inconclusive for combined reasons. The next version should condition guard policy on reason-level evidence rather than treating all long gaps as one regime.

### 2026-04-29 | Holiday-gap caps can now be conditionally overridden by reason
- tags: holiday_gap, daily_signal, p2, shadow_profile
- reusable: yes
- confidence: high
- evidence: Added `holiday_gap_reason_overrides` support to `daily_ml_select.py`. A shadow profile can now set separate `total_position_cap` / `single_pos_cap` for `signal_to_trade_gap`, `post_trade_gap`, and `signal_to_trade_gap+post_trade_gap`. The daily output and P2 ledger now carry `holiday_gap_reason_override_applied`, and rolling replay summarizes override days. Full tests passed: `335 passed, 3 skipped`.
- action: Use reason-specific overrides only in shadow profiles, then rebuild profile-isolated daily files and run score-alpha/coverage/P2 smoke before any 90/120 spend. Do not modify `quality_regime` or broadly disable holiday protection from one cash-drag day.

This gives vNext a clean way to test conditional holiday protection without muddying existing v22 evidence or relaxing all guards at once.

### 2026-04-29 | v24 conditional holiday-gap cap failed score-alpha before P2
- tags: v24, holiday_gap, score_gate, alpha, p2_efficiency
- reusable: yes
- confidence: high
- evidence: Created `quality_regime_candidate_v24_conditional_holiday_gap_guard` as a shadow profile based on v22, with a milder cap only for `signal_to_trade_gap+post_trade_gap`. Rebuilt 70 replayable profile-isolated daily files from `20251204` to `20260413`; signal coverage passed with `70` replayable files, `60/60` reference dates covered, and no missing reference signal days. The score-alpha precheck then skipped v24 for `score_alpha_gate_failed/no_gate_score_passed`: `target_weight` top mean forward return was about `-0.168%` with `rank_ic_mean=-0.015`, while `portfolio_rank_score` top mean was about `-0.348%` and failed both top-vs-pool and top-vs-bottom checks. Full tests passed: `337 passed, 3 skipped`.
- action: Do not spend 60/90/120 P2 on v24 unless the final target-weight or portfolio-rank alpha gate is repaired first. Treat the v24 result as evidence that one-day holiday cash-drag relief does not solve post-filter alpha decay.

v24 fixed a narrow exposure policy hypothesis but did not create executable alpha. The next workstream should diagnose where positive component scores, such as liquidity or exit-trap safety in some grouped views, are lost before final `target_weight` selection.

### 2026-04-29 | v24 stage-transition shows ranking-stage alpha decay before P2
- tags: v24, stage_transition, score_gate, alpha_decay, ranking
- reusable: yes
- confidence: high
- evidence: Rebuilt v24 with `MFTS_WRITE_RESEARCH_STAGE_SNAPSHOTS=true` over 70 replayable signal dates, then ran `quant_stage_transition_diagnosis.py --forward-days 10 --top-n 5`. The full filtered signal pool had mean forward return about `+0.656%`, but `ranking_pool_pre_pretrade` fell to about `-0.150%`; the candidates dropped by `filtered_signal_pool -> ranking_pool_pre_pretrade` averaged about `+1.052%`, while the kept set averaged about `-0.150%`. In the final target pool, `liquidity_score` top-5 had about `+1.23%` mean forward return and positive RankIC around `0.039`, while `exit_trap_safe_score` top-5 had about `+0.40%` mean and RankIC around `0.065`; `portfolio_rank_score` and `target_weight` did not provide promotion-quality alpha.
- action: Treat the current bottleneck as final-ranking / target-score alpha decay. Do not tune holiday-gap caps further until a target-score experiment proves that it can preserve the positive liquidity/exit-trap-safe spread and then pass P2 smoke.

The optimizer is not the first place v24 loses alpha. The high-score quantile gate and final portfolio rank are selecting a weak subset in this 60-day evidence window.

### 2026-05-07 | v25/v26 target-score experiments exposed cash and fallback illusions
- tags: v25, v26, score_gate, p2, execution_quality
- reusable: yes
- confidence: high
- evidence: Created `quality_regime_candidate_v25_liquidity_target_score` to test the positive final-pool `liquidity_score` spread. It passed score-alpha precheck before P2, but aligned 60-day P2 smoke only improved NAV by carrying much lower exposure: v25 NAV/MDD about `-2.62%/-3.89%` versus main `-3.61%/-4.70%`, while target-weight mean was only `14.73%` versus main `29.49%`, with `10` executable-pool halt days. v26 added NAV-weighted style exposure and initially removed style halts, but after fixing capacity optimizer fallback evidence, the rebuilt v26 had `13/70` zero-target days, last-60 target-weight mean about `26.89%`, no `optimizer_fallback` rows, and failed the hardened score-alpha gate because top-bucket forward return was still slightly negative.
- action: Do not spend 90/120 P2 on v25 or v26. The next viable candidate must preserve positive absolute top-bucket forward return after capacity constraints and avoid low-exposure improvement. Treat liquidity-score relative spread as a clue, not a sufficient target-score solution.

v25 improved optics by staying in cash; v26 showed that deploying the same idea under a more credible style basis transmits losses. The project improved because it rejected both forms instead of promoting them.

### 2026-05-07 | Capacity optimizer empty output must remain evidence, not fallback weights
- tags: portfolio_engine, daily_signal, capacity, evidence_lineage
- reusable: yes
- confidence: high
- evidence: `daily_ml_select.py` previously fell back to unconstrained score weights when `build_portfolio_decision` returned an empty selection. On v26 this created days with more than 100 tiny target weights, zero participation/cost diagnostics, and `constraint_reason=optimizer_fallback`, masking capacity failure as diversified deployment. The fallback is now disabled for capacity-aware modes: empty optimizer output is preserved as empty profile daily evidence, and `quant_rebuild_profile_daily_signals.py` sets `MFTS_ALLOW_EMPTY_DAILY_OUTPUT=true` so rebuilds do not delete these artifacts. Full tests passed: `343 passed, 3 skipped`.
- action: For capacity-aware profiles, zero/empty target days are valid no-entry evidence and must flow into score coverage, P2, and promotion gates. Never replace an infeasible constrained portfolio with an unconstrained fallback in promotion evidence.

When constraints say "do not buy", the platform should show cash and shortfall. It should not invent small weights to make the daily file look alive.

### 2026-05-07 | Score-alpha gate now rejects negative top buckets even with positive relative spread
- tags: score_gate, alpha_quality, p2_efficiency
- reusable: yes
- confidence: high
- evidence: v26 after fallback repair had target-weight top bucket forward return about `-0.033%`, all-candidate mean about `-1.018%`, positive top-minus-all, and positive top-minus-bottom. The old gate passed this as relative alpha; the gate now requires `top_mean_forward_return_pct > 0` by default in addition to top-minus-all, top-minus-bottom, RankIC, and coverage. The refreshed v26 precheck now returns `alpha_quality_gate_pass=False` and skips P2 spend.
- action: Keep absolute top-bucket return in the score-alpha smoke gate. A long-only A-share profile should not consume expensive P2 refresh solely because it loses less than its candidate pool.

Relative alpha in a falling recommendation pool can still be useful research information, but it is not enough to justify a new execution candidate.

### 2026-05-07 | Grouped score-alpha diagnostics are not profile gates
- tags: score_gate, diagnostics, promotion, alpha_quality
- reusable: yes
- confidence: high
- evidence: v26 grouped score diagnostics found local bright spots such as primary-only `portfolio_rank_score` top bucket near `+0.26%` and non-holiday `target_weight` top bucket near `+0.26%`, while the full profile-level v26 score gate still failed. `quant_score_alpha_diagnosis.py --group-col ...` now reports `alpha_quality_gate_pass=False` with `grouped_diagnostic_not_profile_gate`, and stores any subgroup gate result only under `subgroup_alpha_quality_gate`.
- action: Use grouped diagnostics to generate hypotheses for a new candidate, not to approve P2 spend or promotion. A profile must pass the ungrouped score-alpha gate before expensive 60/90/120 P2 refresh.

A subgroup can reveal where alpha might survive, but it can also be a small-sample or cash-drag slice. Do not let a local bright spot become a profile-level conclusion.

### 2026-05-07 | v27 primary/reserve isolation failed before P2 spend
- tags: v27, score_gate, target_utilization, reserve_pool, p2_efficiency
- reusable: yes
- confidence: high
- evidence: Created `quality_regime_candidate_v27_primary_reserve_isolation` as a shadow profile based on v26, with `target_score_col=portfolio_rank_score` and `target_max_reserve_weight=0.02` so reserve rows remain available for replacement but have tightly capped active target exposure. Rebuilt 70 replayable profile-isolated daily files through `2026-04-14` with `failed=0`. Cheap precheck showed signal coverage passed and daily target utilization was not the blocker (`target_weight_sum_mean_60≈35.27%`, p10 about `12.0%`, zero-target days `0`), but ungrouped score-alpha failed: `target_weight` top bucket forward return about `-0.563%`, `portfolio_rank_score` about `-0.942%`, and both had negative RankIC. The refresh correctly skipped P2 long-window spend.
- action: Do not run v27 60/90/120 P2 or promotion review unless the full-profile, ungrouped `target_weight` or `portfolio_rank_score` alpha gate is repaired first. Treat primary-only or grouped v26 positives as hypothesis signals, not deployable profile evidence.

Primary/reserve isolation fixed a contamination hypothesis but did not fix final ranking alpha. The bottleneck remains target-score construction, not reserve exposure size.

### 2026-05-07 | Promotion prechecks should emit all cheap evidence before intersecting candidates
- tags: promotion, precheck, target_utilization, evidence_lineage
- reusable: yes
- confidence: high
- evidence: During the v27 cheap run, score-alpha precheck pruned the candidate before signal-coverage and target-utilization prechecks, which initially meant the latest coverage/utilization artifacts only showed the main profile. `quant_refresh_promotion_gate.py` now evaluates coverage and target utilization across the original requested profiles, writes evidence rows for skipped candidates, and then intersects all precheck keep sets before deciding whether P2 should run.
- action: Keep cheap prechecks as independent evidence producers. A candidate skipped by score-alpha should still leave coverage and utilization diagnostics, so the next researcher can tell whether it failed alpha, calendar coverage, low exposure, or a combination.

Skipping P2 is correct only when the reason is auditable. Cheap gates should save compute without erasing evidence.

### 2026-05-07 | P2 reserve and exit-trap caps must be consumed as profile caps
- tags: p2, reserve_pool, exit_trap, config_lineage
- reusable: yes
- confidence: high
- evidence: Added regression tests around `_assign_profile_target_weights` proving positive `target_max_reserve_weight`, `target_exit_trap_risk_threshold`, `target_max_exit_trap_weight`, and `target_max_exit_trap_single_weight` values from profile config flow into P2 reserve re-optimization. The reserve cap path now honors a 2% active reserve cap instead of silently behaving like a disabled/zero cap.
- action: When changing reserve or exit-trap controls, verify both daily portfolio output and P2 replacement artifacts consume the same profile caps. Old P2 artifacts produced before this fix should be treated as legacy-cap evidence and not used for promotion.

Profile-level caps are part of the strategy contract. If P2 drops or clamps them incorrectly, execution evidence is not comparable to research evidence.

### 2026-05-07 | Stage alpha-decay summary makes ranking damage explicit
- tags: stage_transition, alpha_decay, score_gate, diagnostics
- reusable: yes
- confidence: high
- evidence: `quant_stage_transition_diagnosis.py` now writes `*_alpha_decay_summary.csv/json` in addition to stage, transition, daily, and score-stage outputs. On v27, the summary verdict was `ranking_alpha_decay_before_p2`: `filtered_signal_pool -> ranking_pool_pre_pretrade` was the harmful transition, with dropped names beating kept names by about `1.09pct` while the stage mean fell from about `+0.50%` to `-0.23%`. The same summary also identified `liquidity_score` and `exit_trap_safe_score` as hypothesis-only late-stage component scores, while final `portfolio_rank_score` and `target_weight` gate scores failed.
- action: Before creating target-score candidates, run stage alpha-decay summary and require any hypothesis to address the named transition without worsening target utilization. Treat component scores as hypothesis generators only.

Big stage reports are easy to cherry-pick. A compact verdict table keeps the next experiment tied to the actual alpha leak.

### 2026-05-07 | v28 ranking-gate relief worsened target utilization and still failed alpha
- tags: v28, ranking_gate, target_score_blend, target_utilization, score_gate
- reusable: yes
- confidence: high
- evidence: Added shadow-only controls for ranking quantile gates (`score_quantile_normal/choppy/panic` or `score_quantile_q`) and target score blending (`target_score_blend -> target_blend_score`). Created `quality_regime_candidate_v28_ranking_gate_relief` from v27 with a softer quantile gate and a `liquidity_score` / `exit_trap_safe_score` target blend. Rebuilt 70 replayable profile-isolated daily files with `failed=0`; coverage passed, but cheap precheck skipped v28 for `score_alpha_gate_failed/no_gate_score_passed` and target utilization failure: `target_weight_sum_mean_60≈21.27%`, p10 `0%`, zero-target days `21/60` (`35%`).
- action: Do not run v28 P2 windows. Simple ranking-gate relief is not enough; it pushes more names into capacity/constraint infeasibility and does not produce positive full-profile target alpha.

The project learned something useful but unglamorous: the positive component-score slice does not survive as a capacity-aware deployable profile when the ranking gate is simply widened.

### 2026-05-07 | Keep-mode capacity-feasible alpha diagnosis blocked direct v29 creation
- tags: v29_precheck, capacity_feasible_alpha, v27, v28, p2_efficiency
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_capacity_feasible_alpha_diagnosis.py` to test whether candidate score columns still produce positive selected forward return after the profile's ADV, industry, reserve, exit-trap, single-name, and total-position constraints. In the original `keep` primary/reserve label mode, v27 and v28 over 70 replayable stage snapshots through `2026-04-14` produced `capacity_feasible_alpha_gate_pass=False`. v27 had usable target deployment (`target_weight_sum_mean≈36.8%-37.0%`, zero-target `0%`) but every capacity-selected score basket had negative selected weighted forward return. v28's blended `target_blend_score` showed positive unconstrained top return around `+0.95%`, but after constraints the selected weighted forward return was about `-0.51%`, so it was `capacity_ok_alpha_failed`.
- action: Treat keep-mode failure as a direct-profile blocker. A new shadow profile is only allowed if a stricter diagnostic shows the positive names can enter the primary path without raising reserve/exit-trap caps, and it must still pass rebuilt profile daily, cheap gates, and P2 smoke before any long-window spend.

Capacity was not the only culprit here. Some raw/component scores looked positive before constraints, but the actually investable basket selected by the current risk contract was still negative.

### 2026-05-07 | Selection-loss attribution shows v28 alpha is trapped in reserve, not primary
- tags: v28, capacity_feasible_alpha, reserve_pool, target_score_blend
- reusable: yes
- confidence: high
- evidence: Extended `quant_capacity_feasible_alpha_diagnosis.py` with unconstrained-top versus capacity-selected attribution. On v28, `target_blend_score` had unconstrained top mean forward return around `+0.95%`, but selected weighted forward return around `-0.51%`, `selection_loss≈-1.46pct`, top-selected overlap only about `25.5%`, and `selection_loss_label=reserve_cap_replaced_alpha`. The dropped top names averaged about `+0.90%`, while replacement names averaged about `-1.06%`. Similar reserve-cap replacement showed up for `liquidity_score`.
- action: Do not loosen the active reserve cap just to capture this slice. The next valid hypothesis must move genuinely positive, capacity-safe names into the primary ranking path while preserving reserve/exit-trap risk limits, then re-run capacity-feasible alpha before any P2.

The component score is not useless, but its current location in the pipeline is wrong. If the winners live in reserve and the primary book is weak, higher reserve exposure would mostly weaken the risk contract rather than prove alpha.

### 2026-05-07 | v29 primary relabel passed cheap gates but failed P2 smoke
- tags: v29, p2_smoke, target_score_topn, reserve_pool, execution_pass_through
- reusable: yes
- confidence: high
- evidence: Extended `quant_capacity_feasible_alpha_diagnosis.py` with `--primary-promotion-modes keep,score_topn`, then found v27/v28 `score_topn` mode passed for `liquidity_score`, `target_blend_score`, and `exit_trap_safe_score`. Added the default-off daily generation mode `capacity_safe_primary_rank_mode=target_score_topn` and created `quality_regime_candidate_v29_capacity_feasible_alpha` using the existing liquidity/exit-trap target blend, without loosening ADV, industry, reserve, exit-trap, style, holiday, or blocked-order controls. Rebuilt 70 replayable profile daily files with `failed=0`; v29 passed score-alpha, signal coverage, target utilization (`target_weight_sum_mean_60≈35.43%`, zero-target `0%`), and capacity-feasible alpha. The 60-day P2 smoke still skipped v29: main `quality_regime` NAV/MDD about `+4.73%/-5.84%`, v29 about `+0.10%/-7.54%`, exit-not-tradable orders `5` vs main `3`, with worst relative days `2026-01-19` holiday-gap cash drag + sell trap and `2026-03-30` underdeployment.
- action: Do not run v29 90/120 or formal promotion. Primary/reserve relabeling repaired the research artifact enough to pass cheap gates, but did not create execution pass-through. The next local work should attribute why positive forward-return baskets fail after P2 fills and path effects, especially holiday-gap/sell-trap days and underdeployment, before creating another profile.

This is a useful negative result: a score can survive capacity constraints in a static forward-return diagnostic and still fail when the P2 state machine, T+1 path, holiday exposure caps, and blocked exits are applied.

### 2026-05-07 | Static capacity-feasible alpha did not pass through to v29 P2
- tags: v29, execution_pass_through, capacity_feasible_alpha, p2_smoke
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_static_to_p2_pass_through_diagnosis.py` to join capacity-feasible daily selected forward return with same-calendar main/candidate P2 ledger returns. For `quality_regime_candidate_v29_capacity_feasible_alpha` 60-day smoke through `2026-04-14`, both `portfolio_rank_score` and `target_blend_score` produced the same pass-through picture: `60` aligned days, `24` static-positive selected-forward-return days, `15/24` static-positive days underperformed the main profile in P2, total relative return gap about `-4.59pct`, and verdict `static_alpha_not_p2_passed`. Loss labels were mixed: static-negative P2 losses, static-positive path losses, underdeployment, and one holiday cash-drag plus sell-trap day.
- action: Do not create another profile from v29's static capacity-feasible pass alone. The next research step should either prove a score has higher day-level pass-through correlation to P2 returns, or move to full-universe/raw-prediction alpha diagnostics. Do not spend 90/120 P2 on v29.

Capacity-feasible alpha is necessary but not sufficient. A static forward-return basket can look positive while the realized P2 path loses to the main profile because timing, exposure caps, T+1 state, and mark-to-market path dominate the average selected return.

### 2026-05-07 | v29 final static alpha passed while raw ML alpha was weak
- tags: v29, raw_alpha, p2_residual, model_quality
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_raw_alpha_p2_residual_diagnosis.py` to consume stage-transition score summaries plus static-to-P2 pass-through evidence. On v29, raw full-universe `ml_score` at `raw_scored_post_indicator` had top bucket mean forward return about `-2.35%`, top-minus-all about `-3.17pct`, top-minus-bottom about `-3.08pct`, and RankIC about `-0.057`. No raw main score passed the top/spread/RankIC gate. The final `portfolio_rank_score` / `target_weight` score passed static final-pool checks, but static-to-P2 pass-through failed with about `-4.59pct` relative gap. The combined verdict was `final_static_alpha_not_p2_executed_raw_alpha_weak`.
- action: Stop creating new profiles from v29-style final-pool static edges. The next research branch should audit raw model labels/features and horizon alignment, or prove a new raw-universe score passes before spending more P2 on profile variants.

Final-pool alpha can be a selection artifact. If raw ML is anti-predictive across the full universe and P2 pass-through fails, profile engineering is polishing the wrong layer.

### 2026-05-07 | Raw ml_score failure is not just a holding-period mismatch
- tags: raw_alpha, model_quality, label_horizon, v29
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_raw_ml_horizon_diagnosis.py` to test raw `ml_score` at `raw_scored_post_indicator` across open-to-open horizons `1/3/5/8/10/15`, both normal descending and inverted ascending score directions, while recording model `label_horizon` and profile `holding_days`. On v29 snapshots through `2026-04-14`, the latest model was `open_to_open` with `label_horizon=3`, while `quality_regime` uses `holding_days=8` and v29 uses `holding_days=10`, so there is a real model/profile horizon mismatch. However, normal-direction `ml_score` failed every tested horizon: H=3 top bucket was about `-0.51%` with RankIC about `-0.040`, H=8 top bucket about `-2.18%` with RankIC about `-0.056`. Inverted score only weakly passed H=1; longer inverted horizons had positive IC but top baskets below the full universe mean. Repeating the same diagnosis on v27 and v28 profile-isolated raw stage files produced the same `raw_ml_alpha_failed_profile_horizons` verdict, so this is not a v29-only calendar artifact. Latest artifacts: `output/backtest/quant_raw_ml_horizon_diagnosis_latest_quality_regime_candidate_v29_capacity_feasible_alpha_verdict.csv` and `..._summary.csv`.
- action: Do not explain v29/raw alpha failure as only `label_horizon=3` versus `holding_days=8/10`. Before creating more profile variants, audit the training label construction, prediction sign, sample split, feature drift, and whether the model should be retrained to the actual execution holding horizon.

The model/profile horizon mismatch is real, but it is not sufficient as the diagnosis. The raw score direction itself looks damaged across the horizons that matter for the current profiles.

### 2026-05-07 | H=10 raw walk-forward has weak pooled alpha but fails split stability
- tags: raw_model, walk_forward, label_horizon, split_stability
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_raw_model_walkforward_diagnosis.py`, a model-layer diagnostic that rebuilds raw-universe MFTS features, constructs H=8/H=10 open-to-open labels, trains diagnosis-only LightGBM regressors across rolling windows, and writes label sample, fold, horizon, feature-drift, and verdict artifacts without saving a production model. The latest run used 7 rolling folds from 2024-01-01 through 2026-04-14, 120k sampled train rows per fold and full OOS test windows. H=10 pooled OOS looked positive (`top_mean≈+1.38%`, `top-minus-all≈+0.33pct`, `top-minus-bottom≈+3.56pct`, `RankIC≈0.054`), but only 3 of 7 folds passed the full top/spread/IC gate (`fold_pass_rate≈42.9%`), below the 50% stability floor, so verdict remained `raw_walkforward_alpha_failed`. H=8 was weaker: pooled top bucket about `+0.73%`, below all-universe mean about `+0.84%`. Latest files: `output/backtest/quant_raw_model_walkforward_diagnosis_latest_h8_h10_raw_walkforward_verdict.csv`, `_horizon_summary.csv`, `_fold_summary.csv`, `_feature_drift_summary.csv`.
- action: Do not create a profile or spend P2 on H=10 from pooled metrics alone. Next model work should explain fold instability, especially 2025Q4 and 2026Q1/Q2 failures, by feature drift, regime segmentation, sample weighting, and model family/objective choices. A raw model must pass pooled metrics and fold stability before capacity/P2 resumes.

This is a useful improvement over the prior raw-score failure: the H=10 retrain line is not dead, but it is not yet a deployable alpha source.

### 2026-05-08 | H=10 fold instability is only partially improved by recency weighting
- tags: raw_model, fold_instability, regime, feature_drift, objective
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_raw_model_instability_attribution.py` to rerun focused H=10 failing folds with baseline, recency-weighted regression, lambdarank, and high-drift-feature-drop variants. Latest focused run on folds 6/7 (`2025-09-01..2025-12-31` and `2026-01-01..2026-04-14`) returned `instability_variant_partial_fix_only`. Fold 6 baseline top bucket was positive but weak (`top≈+0.94%`, `top-minus-all≈-0.39pct`, `top-minus-bottom≈-0.09pct`) and recency weighting rescued it (`top≈+1.63%`, `top-minus-all≈+0.30pct`). Fold 7 remained an absolute top-bucket failure: baseline `top≈-1.66%`, `top-minus-all≈-1.28pct`; recency weighting, lambdarank, and high-drift-feature-drop all failed. Latest files: `output/backtest/quant_raw_model_instability_attribution_latest_h10_instability_focus_verdict.csv`, `_variant_summary.csv`, `_fold_attribution.csv`, `_regime_summary.csv`.
- action: Do not create a profile or resume capacity/P2 from the H=10 line. Recency weighting is a hypothesis for 2025Q4 only; 2026Q1/Q2 requires regime-specific modeling, feature-drift treatment, or new raw features, and any fix must rerun the full 7-fold walk-forward before profile work.

The important distinction is that fold 6 was a relative ranking/spread problem, while fold 7 was a negative absolute top-bucket problem. A one-fold rescue is not a model fix.

### 2026-05-08 | Rank-normalized features fix fold 7 but remain split-unstable
- tags: raw_model, rank_normalization, drift_robust, split_stability
- reusable: yes
- confidence: high
- evidence: Extended `scripts/quant_raw_model_instability_attribution.py` to compare H=10 baseline, recency-weighted, lambdarank, L1/Huber objectives, rank-normalized features, cross-sectional-only features, high-drift-feature-drop, and ex-ante regime-specific models across all 7 folds. Latest `h10_model_family_7fold` evidence shows `rank_normalized` is the only variant that fixes critical fold 7: fold 7 top bucket about `+0.44%`, top-minus-all about `+0.83pct`, RankIC about `0.054`, gate pass. But it passes only `3/7` folds (`42.9%`), so variant verdict is `split_unstable`. `cross_sectional_only` passes `4/7` folds (`57.1%`) but fails fold 7 with top bucket about `-0.69%`. Regime-specific models, recency weighting, lambdarank, L1/Huber, and drop-high-drift did not solve both fold 7 and split stability. Latest files: `output/backtest/quant_raw_model_instability_attribution_latest_h10_model_family_7fold_variant_family_summary.csv`, `_variant_summary.csv`, `_fold_attribution.csv`.
- action: Keep capacity/P2 blocked. The next model-layer hypothesis should start from rank-normalized feature treatment but must improve full-fold stability before any profile work. Do not treat cross-sectional-only's higher pass rate as sufficient because it still fails the critical 2026Q1/Q2 fold.

This is progress, but not enough. The project found a mechanism that addresses the 2026Q1/Q2 absolute top-bucket failure, yet it does not generalize across the rolling splits.

### 2026-05-08 | Rank-normalized drift treatment is seed-sensitive and not deployable
- tags: raw_model, rank_normalization, sample_stability, feature_drift
- reusable: yes
- confidence: high
- evidence: Extended `scripts/quant_raw_model_instability_attribution.py` with `rank_norm_*` variants, rank-normalized prediction ensembles, and `--sample-mode date_stratified`. Full 7-fold H=10 runs showed apparent progress but not robust alpha: `blend_rank_norm_huber` passed seed1 (`5/7` folds, fold7 top about `+0.05%`) but failed seed2 fold7 (`top≈-0.11%`); `rank_norm_drop_high_drift` passed seed1/seed2 but failed seed3 (`2/7`, fold7 top about `-0.87%`) and failed deterministic date-stratified sampling (`3/7`, fold7 top about `-0.53%`, top-minus-all about `-0.15pct`). Latest date-stratified artifacts: `output/backtest/quant_raw_model_instability_attribution_latest_h10_ranknorm_drop_drift_7fold_date_stratified_variant_family_summary.csv` and `_variant_summary.csv`.
- action: Do not create a profile or run P2 from rank-normalized/drift-drop evidence. Treat these variants as diagnostic clues that 2026Q1/Q2 can sometimes be partially rescued, but require sample-stable fold7 pass and full-fold stability before capacity/P2 resumes. Next model work should reduce sample dependence with deterministic sampling, stronger feature-drift handling, and new raw features/objectives rather than profile engineering.

This is a stricter negative result than the earlier fold-7 rescue. The model line can look alive under one training sample and fail under another, which is exactly the kind of pseudo-alpha that would later vanish in execution.

### 2026-05-08 | Raw model seed stability is now an explicit hard gate
- tags: raw_model, seed_stability, sample_stability, model_gate
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_raw_model_seed_stability_report.py` to aggregate multiple `quant_raw_model_instability_attribution` variant-family summaries without retraining or touching P2. The latest `h10_ranknorm_seed_stability` report consumed seed1, seed2, seed3, and deterministic date-stratified evidence. No variant passed sample stability: `rank_norm_drop_high_drift` passed only `2/4` runs and failed seed3/date-stratified; `blend_rank_norm_huber` and `blend_rank_norm_l1` passed seed1 but failed seed2's critical fold; `rank_normalized` was split-unstable. Latest files: `output/backtest/quant_raw_model_seed_stability_report_latest_h10_ranknorm_seed_stability_variant_summary.csv`, `_run_detail.csv`, and `_verdict.json`.
- action: Before any raw model line can unlock capacity/P2 or a profile experiment, run the seed stability report over independent seeds plus deterministic sample-mode artifacts. Require `sample_stability_pass`; otherwise keep model work in diagnosis and treat attractive single-run results as seed/sample noise.

This turns an informal judgment into a repeatable gate. The project should now spend effort on why 2026Q1/Q2 remains unstable, not on selecting the lucky seed.

### 2026-05-08 | Fold 7 failure is regime-sensitive after rank normalization
- tags: raw_model, fold7, regime, feature_drift
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_raw_model_fold_failure_matrix.py` to aggregate fold-level variant metrics, regime failures, selected top-bucket feature exposure, and drifted feature importance across seed1/seed2/seed3/date-stratified instability artifacts. Latest `h10_fold7_ranknorm_failure_matrix` shows baseline as `absolute_failure_with_drifted_exposure`: fold7 top bucket is negative and below pool across all four runs, with drifted important `pv_corr_20` and recurring top-bucket exposure. `rank_normalized` and `rank_norm_drop_high_drift` are labeled `absolute_failure_regime_sensitive`: they sometimes improve relative spread, but fail across broad_down/mild_down/mild_up and sometimes broad_up regimes. `blend_rank_norm_l1/huber` are `absolute_top_bucket_failure`: spread can remain positive while absolute top returns turn negative. Latest files: `output/backtest/quant_raw_model_fold_failure_matrix_latest_h10_fold7_ranknorm_failure_matrix_variant_summary.csv`, `_run_matrix.csv`, and `_verdict.json`.
- action: Do not keep trying rank-normalized variants as profile inputs. Next raw-model work should explicitly model or condition 2026Q1/Q2 regimes and inspect drifted feature exposure, especially whether features like `pv_corr_20` and momentum/bias clusters should be transformed, capped, neutralized, or replaced. Any fix still has to rerun seed stability before capacity/P2.

The useful distinction is that baseline looks partly drift/exposure-driven, while rank-normalized variants look more regime-sensitive. That points to a model research problem, not another execution/profile tweak.

### 2026-05-08 | Fold 7 failure is partly identifiable by ex-ante regime
- tags: raw_model, fold7, exante_regime, regime_conditioning
- reusable: yes
- confidence: high
- evidence: Extended `scripts/quant_raw_model_instability_attribution.py` to write `exante_regime_summary` using signal-date `market_regime_exante`, and updated `quant_raw_model_fold_failure_matrix.py` to consume ex-ante regime failures. The latest `h10_fold7_exante_regime_probe` over date-stratified fold7 showed `neutral` had 27 days and was the main negative zone for rank-normalized variants: `rank_normalized` neutral top bucket about `-1.97%`, top-minus-all about `-0.28pct`; `rank_norm_drop_high_drift` neutral top about `-2.32%`, top-minus-all about `-0.63pct`. In `risk_on` and `risk_off`, top buckets were positive for rank-normalized variants, but RankIC could turn negative, so the issue is not solved by a naive risk-on/off switch. Baseline also remained badly reversed in `risk_on` with top about `-4.64%`.
- action: Treat ex-ante regime as a model-design clue, not a profile/P2 gate. Next raw-model work should test regime-conditioned objective/feature treatment, especially neutral-regime ranking and risk-on/risk-off IC direction, then rerun seed stability. Do not create a profile from this diagnostic.

This is a useful narrowing of the search space: fold7 is not merely an unknowable ex-post regime artifact, but the current ex-ante regime features are still too crude to become a trading rule.

### 2026-05-08 | Regime-specific modeling helps fold7 but still fails the raw alpha gate
- tags: raw_model, fold7, regime_conditioning, alpha_gate
- reusable: yes
- confidence: high
- evidence: Ran `scripts/quant_raw_model_instability_attribution.py` with `--sample-mode date_stratified`, `--focus-folds 7`, and variants `baseline,rank_normalized,regime_specific,rank_norm_regime_specific,rank_norm_drop_high_drift` under label `h10_fold7_regime_specific_probe`. The best variant was `rank_norm_regime_specific`: fold7 top bucket was about `-0.025%`, top-minus-all about `+0.358pct`, top-minus-bottom about `+2.79pct`, and RankIC about `0.030`. This is much better than baseline (`top≈-3.80%`) and raw `regime_specific` (`top≈-3.32%`), but it still fails because the absolute top bucket remains negative. Ex-ante summary shows `rank_norm_regime_specific` passes risk-on/risk-off slices but still fails the `neutral` slice, where top bucket is about `-1.76%` and only marginally above/below pool depending on the metric.
- action: Do not expand this result into a new profile, P2 run, or production model. Treat it as evidence that regime-conditioned modeling and rank normalization are useful building blocks, while the next model work should focus on neutral-regime feature treatment, regime-specific calibration/objectives, and drifted feature handling. Any future improvement must first pass absolute top bucket, spread, RankIC, full 7-fold stability, and seed/sample stability.

The important nuance: positive spread over a weak pool is not enough. The strategy needs a positive top bucket before capacity, costs, T+1, and P2 path effects have any chance to preserve alpha.

### 2026-05-08 | Daily-ranked regime label objective rescues fold7 but fails full split stability
- tags: raw_model, label_objective, fold_instability, split_stability
- reusable: yes
- confidence: high
- evidence: Extended `scripts/quant_raw_model_instability_attribution.py` with diagnosis-only label target modes: daily-demeaned and daily-ranked labels, including `rank_norm_regime_label_ranked`. On the focused `h10_fold7_label_objective_probe`, `rank_norm_regime_label_ranked` rescued the 2026Q1/Q2 critical fold: fold7 top bucket about `+0.309%`, top-minus-all about `+0.692pct`, top-minus-bottom about `+4.63pct`, RankIC about `0.110`, and `alpha_gate_pass=True`. But the strict full `h10_label_objective_7fold_date_stratified` run over all 7 folds returned `instability_variant_partial_fix_only`: `rank_norm_regime_label_ranked` passed only `2/7` folds, fold pass rate about `28.6%`. It also failed fold6 with top about `+1.09%` but top-minus-all about `-0.24pct` and top-minus-bottom about `-0.83pct`.
- action: Do not create a profile, rerun P2, or treat daily-ranked regime labels as deployable. This result is a model-research clue: daily-ranked labels and ex-ante regime-specific models can fix the current critical fold, but they transfer poorly across other regimes/windows. Next work should explain fold2/fold6 residual failures and test whether calibration, feature drift controls, or regime-specific ensembling can improve full-fold stability before any capacity/P2 work.

This is the cleanest model-layer progress so far, but it is still a research clue rather than strategy alpha. The failure moved; it did not disappear.

### 2026-05-08 | Fold2 and fold6 residual failures have different causes
- tags: raw_model, residual_fold, regime_conditioning, split_stability
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_raw_model_residual_fold_diagnosis.py` to explain residual failing folds from existing instability artifacts without retraining, profile changes, or P2. Latest `h10_label_objective_fold2_fold6_residuals` on `rank_norm_regime_label_ranked` shows fold2 is `absolute_loss_but_beats_pool`: top bucket about `-0.946%`, all-universe mean about `-1.907%`, top-minus-all about `+0.961pct`, top-minus-bottom about `+4.53pct`, RankIC about `0.072`. Its main failed ex-ante regimes are `neutral` (`top≈-3.36%`, spread `-0.52pct`) and `risk_on` (`top≈-6.31%`, spread `-0.21pct`). Fold6 is `positive_top_but_pool_and_bottom_lag`: top bucket about `+1.094%`, but all-universe mean about `+1.332%`, top-minus-all about `-0.238pct`, top-minus-bottom about `-0.83pct`, with `neutral` and `risk_on` failures and drifted important `pos_52w` (`share≈9.6%`, `psi≈0.64`, `std≈0.73`).
- action: Do not solve fold2/fold6 with another global profile or P2 test. Fold2 needs a weak-window absolute-return filter/calibration because relative defense still loses money. Fold6 needs market-beta/opportunity capture repair because the selected top bucket is positive but misses the broader pool and bottom bucket. Any next model experiment should target these two residual labels separately, then rerun full 7-fold and seed/sample gates.

This explains why the fold7 rescue did not generalize. The model does not have one residual problem; it has at least two: weak-market absolute loss and positive-market relative anti-selection.

### 2026-05-08 | Fold2 and fold6 now have separate raw-model treatment hypotheses
- tags: raw_model, residual_treatment, fold2, fold6, pos_52w
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_raw_model_residual_treatment_probe.py`, which consumes the residual fold diagnosis without retraining, profile changes, or P2. Latest `h10_label_objective_fold2_fold6_treatment_probe` labels fold2 as `weak_market_absolute_return_calibration`: top bucket about `-0.946%` while still beating the pool by about `+0.961pct`, with implicated signal-date regimes `neutral,risk_on,high_vol_down` and features `pv_corr_20,rs_20d,mom_20,bias`. It labels fold6 as `beta_capture_pos52w_drift_repair`: top bucket about `+1.094%` but pool lag about `0.238pct` and bottom lag about `0.830pct`, with implicated regimes `neutral,risk_on` and drifted feature `pos_52w`. Latest files: `output/backtest/quant_raw_model_residual_treatment_probe_latest_h10_label_objective_fold2_fold6_treatment_probe_summary.csv`, `_verdict.json`, and `_report.md`.
- action: Do not build v30 or run P2 from the label-objective line. Next model work should run treatment-specific raw-universe 7-fold diagnostics: fold2 needs an ex-ante absolute-return calibrator or weak-window deployment veto that turns weak-window top buckets positive; fold6 needs beta/opportunity capture and `pos_52w` drift treatment that makes neutral/broad-up top-minus-all and top-minus-bottom non-negative without re-breaking fold2.

This converts the residual diagnosis into concrete model gates. The next pass should test these treatments at the raw-model level only; capacity and P2 remain blocked until full 7-fold and sample-stability gates pass.

### 2026-05-08 | First residual treatment variants did not clear the 7-fold raw-model gate
- tags: raw_model, residual_treatment, fold2, fold6, pos_52w
- reusable: yes
- confidence: high
- evidence: Extended `scripts/quant_raw_model_instability_attribution.py` with diagnosis-only residual treatment variants: `abs_calibrated_rank_norm_regime_label_ranked`, `pos52w_beta_rank_norm_regime_label_ranked`, and `abs_pos52w_beta_rank_norm_regime_label_ranked`. The latest `h10_residual_treatments_7fold_date_stratified` full 7-fold run used critical folds `2,6,7`. No variant passed: `rank_norm_regime_label_ranked` and the two absolute/combo treatments each passed only `2/7` folds, while `pos52w_beta_rank_norm_regime_label_ranked` passed `0/7`. Fold2 remained negative: `rank_norm_regime_label_ranked` top about `-0.790%`, absolute blend worsened it to about `-2.273%`, and combo worsened it to about `-2.485%`. Fold6 improved under pos_52w/beta overlay from top-minus-all about `-0.675pct` to about `-0.090pct`, but still failed top-minus-pool and top-minus-bottom; the same overlay broke fold7 absolute top bucket to about `-0.294%`. Latest files: `output/backtest/quant_raw_model_instability_attribution_latest_h10_residual_treatments_7fold_date_stratified_variant_family_summary.csv`, `_variant_summary.csv`, `_exante_regime_summary.csv`, and `_verdict.csv`.
- action: Keep capacity/P2/profile work blocked. The simple absolute-return blend is not a valid weak-market calibrator, and unconditional pos_52w/beta boost is not safe because it helps fold6 only partially while damaging fold7. Next raw-model work should test a stricter day-level absolute-return calibrator/veto for fold2 and a conditional, regime-aware pos_52w/beta capture that activates in neutral/broad-up opportunity windows without re-breaking fold7.

This is a useful negative result. It narrows the next experiment: not "more profile engineering", and not a blind pos_52w boost, but a calibrated day/regime layer that has to survive all seven folds.

### 2026-05-08 | Strict deployment veto and conditional pos_52w/beta treatments still fail
- tags: raw_model, residual_treatment, deployment_veto, fold2, fold6, pos_52w
- reusable: yes
- confidence: high
- evidence: Extended `scripts/quant_raw_model_instability_attribution.py` with strict raw-model treatment variants: `day_veto_rank_norm_regime_label_ranked`, `conditional_pos52w_beta_rank_norm_regime_label_ranked`, and `day_veto_conditional_pos52w_beta_rank_norm_regime_label_ranked`, plus deployment-day coverage metrics and a deployment coverage floor. Latest `h10_residual_strict_treatments_7fold_date_stratified` still returned `instability_variant_partial_fix_only`. `day_veto_rank_norm_regime_label_ranked` passed only `1/7` folds with mean deployment about `54.7%` and minimum fold deployment about `18.3%`; fold2 still had negative top bucket and fold6 still lagged the pool. `conditional_pos52w_beta_rank_norm_regime_label_ranked` passed only `2/7`, mostly found no train-regime allowlist, and worsened fold6 top-minus-all to about `-0.968pct`. The combined treatment passed `0/7` and broke fold7 top bucket to about `-0.231%`.
- action: Keep capacity/P2/profile work blocked. A coarse signal-date day-level veto is not a validated fold2 calibrator because it creates low-deployment evidence, and the current conditional pos_52w/beta overlay is not a fold6 repair because training data does not identify a reliable activation regime. Next raw-model work should build richer ex-ante day-level calibration features and a genuine train-time opportunity detector before rerunning full 7-fold and seed/sample gates.

The important negative result is that "deployment veto" and "conditional overlay" are not automatically more professional than unconditional overlays. They must preserve sufficient signal coverage and pass all critical folds, otherwise they are just another way to hide weak raw alpha.

### 2026-05-08 | Day-state calibration and train-time opportunity detector still do not solve fold2/fold6
- tags: raw_model, day_state_calibration, opportunity_detector, fold2, fold6
- reusable: yes
- confidence: high
- evidence: Extended `scripts/quant_raw_model_instability_attribution.py` with signal-date day-state kNN treatments: `day_calibrated_rank_norm_regime_label_ranked`, `day_opportunity_pos52w_beta_rank_norm_regime_label_ranked`, and `day_calibrated_opportunity_rank_norm_regime_label_ranked`. Latest `h10_day_state_calibration_opportunity_critical_folds_date_stratified` over critical folds `2,6,7` still returned `instability_variant_partial_fix_only`. The base `rank_norm_regime_label_ranked` passed only fold7. The day-state absolute calibration kept 100% deployment and activated on about `72.6%` of fold2 days, but fold2 top bucket worsened from about `-0.790%` to `-1.491%`; fold6 top improved to about `+0.950%` but still lagged the pool by about `-0.382pct` and lagged bottom. The day-state pos_52w/beta opportunity detector activated on `0%` of fold6 days because train-neighbor expected edge was about `-0.368pct`; it activated on `97.5%` of fold7 days and kept fold7 passing, but did not solve fold2/fold6. The combo also failed critical folds.
- action: Keep capacity/P2/profile blocked. The current signal-date day-state features are not enough to turn weak-window defense into positive absolute top returns or to identify a fold6 pos_52w/beta opportunity. Next raw-model work should either add genuinely new day-level/regime features, redesign the H=10 label/objective, or test a two-stage model that separately predicts day deployability and within-day cross-sectional ranking; do not force an overlay when the train-time opportunity detector says edge is negative.

This is a better negative result than the previous veto experiment because it did not simply starve deployment. It shows the available day-state features themselves are not yet discriminative enough.

### 2026-05-08 | Raw feature-frame cache reduces repeated model-diagnosis cost
- tags: raw_model, feature_cache, diagnosis_performance
- reusable: yes
- confidence: high
- evidence: Added metadata-validated cache support to `scripts/quant_raw_model_walkforward_diagnosis.py` and reused it from `scripts/quant_raw_model_instability_attribution.py`. The cache request binds data file path/mtime/size, feature list, horizon list, date range, BJ/9-code filter, and cache version. First full H=10 engineered/two-stage 7-fold run wrote `output/cache/raw_model_frames/raw_model_frame_d06973bedd72540c.parquet`; a follow-up cache smoke printed `raw_model_frame_cache=hit` and skipped the heavy MFTS indicator rebuild.
- action: Keep `--feature-cache-file auto` as the default for raw-model diagnostics, and use `--no-feature-cache` only when validating cache behavior or suspected stale-frame issues. Do not commit cache files; they live under ignored `output/`.

The cache is an engineering accelerator, not strategy evidence. It should make future raw-model iterations cheaper while preserving explicit metadata lineage.

### 2026-05-08 | Engineered raw features and two-stage positive-hit blend are only a partial raw-model fix
- tags: raw_model, engineered_features, two_stage_model, split_stability
- reusable: yes
- confidence: high
- evidence: Extended `scripts/quant_raw_model_instability_attribution.py` with diagnosis-only engineered raw features, a `positive_daily_ranked` label target, and two-stage positive-hit blend variants. The full `h10_engineered_positive_two_stage_7fold_date_stratified` run used critical folds `2,6,7`. Best variant was `engineered_two_stage_hit_rank_norm_regime_label_positive_ranked`, but it passed only `2/7` folds. Fold2 stayed negative (`top≈-1.803%`), fold6 remained pool/bottom-lagged (`top≈+1.169%`, `top-minus-all≈-0.163pct`), and fold7 was only near zero (`top≈-0.002%`) rather than positive. Latest files: `output/backtest/quant_raw_model_instability_attribution_latest_h10_engineered_positive_two_stage_7fold_date_stratified_variant_family_summary.csv`, `_variant_summary.csv`, `_fold_attribution.csv`, and `_verdict.csv`.
- action: Keep capacity/P2/profile work blocked. Engineered interaction features and a positive-hit second stage improve some windows but do not solve the critical-fold gate. Next raw-model work should design richer raw feature families or model structures that specifically turn fold2 positive and make fold6 top-minus-pool/bottom non-negative without losing fold7.

This is real model-layer progress in observability, but not deployable alpha. The failure moved closer to zero in fold7 and improved fold6 somewhat, yet the complete raw gate still fails.

### 2026-05-08 | Market-context raw features rescue fold6/fold7 but leave fold2 unresolved
- tags: raw_model, context_features, fold2, fold6, fold7
- reusable: yes
- confidence: high
- evidence: Extended `scripts/quant_raw_model_instability_attribution.py` with a `context_` feature family that uses signal-date OHLCV shape, gap/intraday/range behavior, amount/volume logs, same-day market breadth, stock-minus-market return, and trailing market-stress interactions. The latest full `h10_context_tail_two_stage_7fold_date_stratified` run used critical folds `2,6,7`. Best variant was `context_rank_norm_regime_label_ranked`, passing `3/7` folds. It rescued fold6 (`top≈+1.751%`, `top-minus-all≈+0.418pct`) and fold7 (`top≈+0.469%`, `top-minus-all≈+0.851pct`), while fold2 remained an absolute top-bucket failure (`top≈-1.722%`) despite positive spread over the weak pool. Tail-positive label and context two-stage variants did not fix fold2 and sometimes damaged fold6/fold7.
- action: Keep capacity/P2/profile blocked. Treat market-context features as a useful raw-model building block for fold6/fold7, but do not use them as a deployable model line until fold2 is solved. Next raw-model work should focus on fold2-specific absolute-return objective, downside-aware loss, or weak-market deployability that turns top bucket positive without sacrificing the fold6/fold7 context repair.

This is the cleanest narrowing so far: context features can solve the strong/neutral opportunity-capture issue, but the weak-window absolute-return problem remains the hard blocker.

### 2026-05-08 | Downside-weighted context models still do not solve fold2
- tags: raw_model, downside_weighting, context_features, fold2, fold6, fold7
- reusable: yes
- confidence: high
- evidence: Fixed `scripts/quant_raw_model_instability_attribution.py` so `market_regime_exante` survives `_clean_with_extras` as a string instead of being coerced to NaN, then added `downside_*` sample weighting that emphasizes weak-day resilient winners and severe losers without changing deployment coverage. The full `h10_downside_context_7fold_date_stratified` run used critical folds `2,6,7`. `downside_context_rank_norm_regime_label_ranked` passed fold6 (`top≈+1.346%`, `top-minus-all≈+0.014pct`) and fold7 (`top≈+0.345%`, `top-minus-all≈+0.728pct`), but fold2 remained negative (`top≈-1.845%`). `downside_context_rank_norm_regime_label_tail_ranked` was the family best by pass count (`3/7`) and also passed fold6/fold7, but fold2 was still about `-2.243%`.
- action: Keep capacity/P2/profile blocked. Downside weighting is a useful diagnostic because it preserves 100% deployment and can stabilize fold6/fold7 with context features, but it is not a fold2 absolute-return fix. Next raw-model work should focus on fold2-specific day-level target design or a two-stage deployability/ranking model that turns weak-window top buckets positive before any execution-layer work resumes.

This also corrects a prior interpretation risk: the earlier context run was directionally useful, but regime-specific notes were weaker than they looked because the regime string could be lost during cleaning. Fresh evidence after the fix is the new reference.

### 2026-05-08 | Richer context day-state calibration improves but does not fix fold2
- tags: raw_model, day_state_calibration, context_features, fold2, fold6, fold7
- reusable: yes
- confidence: high
- evidence: Extended `DAY_STATE_RAW_FEATURES` so day-state calibration can use signal-date context fields such as gap, intraday return, range, amount/volume logs, stock-minus-market return, and market-stress interactions. Added `day_calibrated_context_rank_norm_regime_label_ranked` and `day_calibrated_downside_context_rank_norm_regime_label_ranked`. The full `h10_context_day_calibration_7fold_date_stratified` run still failed the raw-model gate. Best variant was `day_calibrated_context_rank_norm_regime_label_ranked`, passing `3/7` folds and fold6/fold7, with fold6 `top≈+1.484%`, `top-minus-all≈+0.152pct`, and fold7 `top≈+0.520%`, `top-minus-all≈+0.903pct`. Fold2 improved versus plain context (`-2.541%`) and downside context (`-1.845%`) to about `-1.660%`, but remained negative. The downside+day-calibrated variant passed fold7 but failed fold6 spread and did not fix fold2.
- action: Keep capacity/P2/profile blocked. Richer signal-date day-state calibration is directionally helpful for fold2 but still not a valid weak-window absolute-return repair. Next model work should move beyond defensive overlays toward a fold2-specific day-level target, a two-stage deployability/ranking model, or a redesigned weak-market label objective.

This narrows the next model question: the existing context features can tell the model something useful, but not enough to turn weak-window selected returns positive. The next experiment should change the target/model structure, not merely add another overlay.

### 2026-05-09 | Weak-positive context target is closer but still not a raw-model pass
- tags: raw_model, weak_positive_label, two_stage_model, fold2, fold6, fold7
- reusable: yes
- confidence: high
- evidence: Added `weak_positive_daily_ranked`, which uses ordinary daily ranks on non-weak training days but, on weak training days, strongly rewards positive-return stocks and assigns very low labels to negative-return stocks. Added context weak-positive variants plus a positive-hit two-stage head. The full `h10_weak_positive_context_7fold_date_stratified` run produced the best raw-model family so far: `day_calibrated_context_two_stage_hit_rank_norm_regime_label_weak_positive_ranked` passed `5/7` folds, with fold6 `top≈+1.373%`, `top-minus-all≈+0.041pct`, and fold7 `top≈+0.746%`, `top-minus-all≈+1.129pct`. But critical fold pass remained false because fold2 stayed negative: the family best had fold2 `top≈-1.884%`; the best fold2 variant in the run was `downside_context_rank_norm_regime_label_weak_positive_ranked` at about `-1.545%`.
- action: Keep capacity/P2/profile blocked. Weak-positive target design and two-stage positive-hit blending are genuine model-layer progress, but they still do not solve fold2 absolute returns. Next work should target fold2 day-level deployability or a two-stage day/head model that can identify when weak-window selected baskets can actually be positive, without starving deployment or breaking fold6/fold7.

This is the first model line to reach `5/7` folds, so it is worth preserving as a research baseline. It is not enough to reopen execution work because the binding critical fold still loses money before costs.

### 2026-05-09 | Fold2 abstention heads expose deployability miscalibration rather than fixing weak-market alpha
- tags: raw_model, fold2, abstention, deployability, weak_market
- reusable: yes
- confidence: high
- evidence: Added diagnosis-only deployability treatments to `scripts/quant_raw_model_instability_attribution.py`: day-state abstention, validation-calibrated day-state abstention, and stock-level positive-hit deployability abstention. Fold2-only probes show these do not clear the raw-model gate. `h10_validated_abstention_fold2_probe` reduced deployment to `40/84` days (`47.6%`) but top bucket stayed negative at about `-1.60%` and failed the deployment-rate floor. `h10_hit_abstention_fold2_probe` used a validation-calibrated positive-hit threshold, but the threshold deployed all `84/84` test days and top bucket stayed about `-2.75%`.
- action: Keep capacity/P2/profile blocked. Do not treat abstention heads as the next profile path. The problem is that current signal-date day-state and positive-hit deployability expectations are miscalibrated in fold2. Next raw-model work should focus on weak-market label/loss design, fold2-specific state segmentation, or new features that can identify weak-window positive baskets before the deployment head is trusted.

This is a useful negative result: "learn not to trade" only helps if the abstention head can identify bad deployment days out of sample. Current heads either deploy everything or cut exposure below the floor while still losing money.

### 2026-05-09 | Strict absolute-positive labels do not fix fold2
- tags: raw_model, fold2, label_objective, weak_market
- reusable: yes
- confidence: high
- evidence: Added diagnosis-only `strict_positive_daily_ranked` and `margin_positive_daily_ranked` training label modes, plus context and two-stage variants. The fold2-only `h10_strict_positive_fold2_probe` did not improve the critical fold. Baseline fold2 top bucket was about `-1.92%`; the best strict/margin variant, `context_rank_norm_regime_label_margin_positive_ranked`, was about `-2.09%`; `strict_positive` was about `-2.18%`; two-stage strict/margin variants were about `-2.39%/-2.85%`.
- action: Keep capacity/P2/profile blocked. Do not continue by simply making positive-return labels harsher. The next raw-model step should explain why fold2 test-state opportunity differs from train/validation, or add new state/feature structure that can identify weak-window positive baskets before changing labels again.

This closes another tempting shortcut: "reward only absolute winners" sounds right, but in fold2 it made selection worse. The failure is likely state/feature mismatch, not just target softness.

### 2026-05-09 | Fold2 failure is primarily state distribution shift, not over-deployment
- tags: raw_model, fold2, state_migration, weak_market
- reusable: yes
- confidence: high
- evidence: Added `scripts/quant_raw_model_state_migration_diagnosis.py`, a diagnosis-only fold state-migration report that reuses raw feature-frame cache and walk-forward splits without training a production model, creating a profile, or entering P2. Latest `h10_fold2_state_migration` verdict is `state_distribution_shift`: test expected return mean was about `-1.26%`, actual was about `-1.91%`, and expected deploy rate was only about `29.8%`, so the problem is not simply that a deployability head over-deployed. The strongest test state drift had max PSI about `6.51`, led by `market_vol_20d`, `volatility_ratio_day_std`, `atr_percent_day_mean`, `amount_day_mean/std`, `pos_52w_day_mean`, `rs_20d_day_mean`, and `pv_corr_20_day_mean`. Test `risk_on` and `neutral` regimes had day mean returns about `-6.10%` and `-2.85%`, while the validation window's `risk_off` slice was strongly positive, so validation was not a reliable proxy for this held-out weak window.
- action: Keep capacity/P2/profile blocked. Stop tightening labels or adding coarse abstention heads for fold2. The next valid raw-model work should target state-migration robustness: richer signal-date regime/state features, split-aware weak-market training, or model structures that detect when historical validation winners no longer represent the test state.

This result changes the fold2 question from "how do we select fewer weak days?" to "why did the signal-date state distribution move into a different opportunity set?" That is a model/data-regime problem, not an execution-layer problem.

### 2026-05-09 | Matched-state training only partially improves fold2 and still fails absolute alpha
- tags: raw_model, fold2, state_migration, matched_state
- reusable: yes
- confidence: high
- evidence: Extended `scripts/quant_raw_model_instability_attribution.py` with diagnosis-only state-migration variants. `state_weighted_*` weights training signal dates by similarity to the held-out fold's signal-date state distribution; `matched_state_*` trains on closest historical state days; `state_weak_positive_daily_ranked` triggers weak-positive labels from ex-ante weak-state features instead of future day mean. Fold2-only probes still failed the raw-model gate. `matched_state_context_rank_norm_regime_label_weak_positive_ranked` was best at the default 45% keep rate, improving fold2 top bucket from baseline about `-1.92%` to about `-1.54%` and top-minus-all from about `-0.01pct` to about `+0.37pct`, but top bucket remained negative. Keep-rate checks showed 25% was about `-1.93%` and 65% was about `-2.84%`. `state_weighted_*` and `state_weak_positive_daily_ranked` variants were worse, with state-aware weak target around `-2.96%` and matched-state state-aware target around `-2.72%`.
- action: Keep capacity/P2/profile blocked. Treat matched-state training as a useful diagnostic that historical similar states contain some relative-defense information, not deployable alpha. The next raw-model step should inspect the matched-state training days themselves and identify missing state features or alternative labels that distinguish positive weak-window opportunities from merely less-bad baskets.

State matching reduced one symptom but did not change the economic conclusion: the selected basket still loses money before costs. This is exactly where profile work would be premature.

### 2026-07-16 | Shared A-share ODS root is usable only through a latest-snapshot schema bridge
- tags: data_source, ods, schema_bridge, read_only
- reusable: yes
- confidence: high
- evidence: Read-only inspection of `/Users/max/Data/ashare-source-data` found complete core ODS datasets with paired parquet/manifest partitions. Latest `2026-07-15` daily panel can join `daily_bars`, `daily_basic`, `daily_adj_factor`, and `daily_limits` with no missing core fields after left-joining from bars. Added `core/data/ashare_ods_loader.py` with tests proving it selects the latest snapshot, maps `instrument_id/volume/display_name` to legacy `ts_code/vol/name`, and defaults to BJ/9-code exclusion.
- action: Do not directly replace `data/daily_all_5y.parquet` paths with the shared root. Migrate consumers through `AShareOdsLoader`, preserve latest-snapshot selection, manifest/data-lineage awareness, BJ/9-code filtering, and old field semantics. Treat `current_snapshot_only` as descriptive current data, not historical PIT truth.
- takeaway: The new shared data source is a better foundation, but unadapted path replacement would create schema, snapshot, and PIT errors.

### 2026-07-16 | ODS raw-model frames need trading-session warm-up and label buffer
- tags: data_source, ods, raw_model, feature_window, labels
- reusable: yes
- confidence: high
- evidence: The first ODS walk-forward bridge loaded only the requested `2026-04-01..2026-04-14` range. `pos_52w` and `label_h10` then had `0` valid rows because `calc_indicators` requires 252 trading sessions and the label enters at next open then exits at `H+1`. After expanding ODS reads by 252 preceding sessions and `max(horizon)+1` following sessions, the same requested frame had `44,184` non-null `pos_52w` rows and `46,503` non-null `label_h10` rows.
- action: Every ODS raw-model consumer must resolve data ranges against `daily_bars` trading dates, not natural-calendar days. Preserve at least the maximum indicator warm-up and forward label buffer before clipping back to the requested evidence dates.
- takeaway: A source bridge can preserve column names while still silently destroying features and labels at sample boundaries.

### 2026-07-16 | Latest-snapshot ODS caches need a partition fingerprint
- tags: data_source, ods, cache, snapshot, evidence_lineage
- reusable: yes
- confidence: high
- evidence: The ODS loader intentionally selects the newest partition snapshot, but a cache key containing only the root and requested dates would reuse an old feature frame if a vendor backfilled a historical snapshot. The raw-model walk-forward cache now records the expanded source window and a SHA-256 digest of each selected `daily_bars` `(trade_date, snapshot)` pair; a regression test proves a new same-day snapshot changes the cache request.
- action: Any cached ODS consumer must either fingerprint the exact selected partitions or disable cache reuse. Root path plus a generic `latest_snapshot` policy is not sufficient lineage.
- takeaway: Snapshot selection is part of the data version, not merely a loader implementation detail.

### 2026-07-16 | Legacy panel contains a broad corrupted daily slice that ODS does not reproduce
- tags: data_quality, legacy_data, ods, evidence_lineage
- reusable: yes
- confidence: high
- evidence: A read-only comparison over `2026-03-27..2026-04-14` found the legacy and ODS OHLC panels nearly identical on most days, but on `2026-04-03` `5,157 / 5,181` shared rows (`99.54%`) had different close values. Spot checks showed legacy `2026-04-03` repeated the `2026-04-02` OHLC for affected names, while ODS carried distinct `2026-04-03` bars. Legacy also had near-total `pct_chg` nulls on several adjacent days.
- action: Do not require numerical equality between ODS and legacy raw-model artifacts. Treat ODS runs as separately versioned evidence, surface date-level data divergences before attributing model changes, and investigate legacy corrupted slices before citing legacy-only conclusions.
- takeaway: Data-source migration can reveal historical source corruption; that is a data-quality finding, not evidence that an alpha changed.

### 2026-07-16 | Pipeline orchestration and execution evidence must name the ODS source explicitly
- tags: data_source, ods, orchestration, p2, backtest, lineage
- reusable: yes
- confidence: high
- evidence: `daily_all.py` now performs a read-only ODS availability check and has no downloader fallback; P2 manifests record the bounded market-data lineage used by execution rather than legacy parquet paths. Portfolio backtest, P1 capacity diagnostics, and P2 shadow prices now consume the same ODS gateway. Targeted regression coverage passed for these paths.
- action: Do not retain legacy filenames in manifests or step names once a consumer has moved to ODS. Treat an ODS coverage shortfall as a clear stop condition, never as permission to download or mutate shared data.
- takeaway: Data-source migration is incomplete when evidence metadata still describes an old source, even if the calculation itself uses the new one.

### 2026-07-16 | ODS migration requires removing mutation affordances, not only changing readers
- tags: data_source, ods, web, governance, read_only
- reusable: yes
- confidence: high
- evidence: Raw-model walk-forward and horizon diagnostics now default to shared ODS. Score/stage/capacity diagnostics use ODS whenever no explicit inspection file is supplied. The Web download endpoint now returns a clear read-only rejection instead of starting `daily_incremental_update.py`; ODS names and verification reads are available through the Web data service.
- action: During final removal, audit APIs, CLI defaults, docs, and manifests in addition to `read_parquet` calls. A hidden downloader is a data-source ownership violation even if production calculations use ODS.
- takeaway: Read-only boundaries are behavioral contracts across user interfaces and maintenance tooling.
# 2026-07-16 | 共享 ODS 首批生产迁移：会话与 execution window 必须统一

- `trading_calendar` 在共享根中是稀疏快照，不能单独作为历史 replay 的会话真相；当其不能覆盖完整请求区间时，连续的 `daily_bars` 分区才是历史可用交易日依据。完整覆盖时日历仍可用于交叉校验。
- 日选股、P2 和 pretrade 的行情/行业元数据已开始经只读 ODS gateway 获取；P2 execution bars 必须限制为 `signal_date` 前 20 个交易日加所需后续交易日，不能全量扫描共享历史。
- ODS 元数据门禁应按 signal-date as-of 读取 `instrument_master`，不得以本机 CSV 的 mtime 作为历史 evidence 的 freshness 代理。
# 2026-07-16 | 共享 ODS 迁移应以“可执行入口”而不是文件替换为单位

- 当前生产、训练、P2/promotion、Web、核心 raw-model 诊断默认已切换到
  `AShareMarketDataGateway` / ODS-only 读取；训练实验 lineage 改为记录 snapshot digest，
  不再把本地市场 Parquet 伪装成数据真相源。
- 旧本地行情修复、下载和历史回测脚本不能迁移为共享 ODS 写入器。它们应脱离调度、明确
  标注为 legacy，并在最终无旧数据验收与用户明确确认之后再删除。
- 验收不能只靠 `rg`：同时需要全量测试、真实 ODS health、以及一次不读取旧缓存的生产/研究
  rehearsal。共享 `trading_calendar` 稀疏时，历史会话仍应由 `daily_bars` 分区日期驱动。
# 2026-07-16 | ODS 迁移最终验收与旧缓存删除

- 用户确认后，已将 `data/daily_all_5y.parquet`、`stock_info.csv`、行业缓存、基准缓存和
  Python 缓存移入系统废纸篓；共享 `/Users/max/Data/ashare-source-data` 未被写入或修改。
- 新增 `tests/test_legacy_data_retirement.py`：它要求本地旧市场数据不存在，并要求所有遗留
  路径文本严格限于已隔离的历史/修复代码，防止未来生产入口回退到旧缓存。
- 无旧数据验收通过：ODS health、真实 bars/metadata smoke、production/raw-model/P2 help
  入口与完整测试集均正常。历史/修复脚本仍只作隔离参考，不能生成新的研究、执行或 promotion
  证据。

### 2026-07-16 | Default project commands must use the stock Conda environment
- tags: environment, reproducibility, operations
- reusable: yes
- confidence: high
- evidence: The maintained workstation environment exists at `/opt/homebrew/Caskroom/miniforge/base/envs/stock`, and `scripts/start_web.sh` already uses that interpreter by default. Project verification can silently differ when an agent runs the active `base` interpreter instead.
- action: Use `conda run -n stock python ...` for non-interactive commands or activate `stock` explicitly. Record intentional interpreter overrides through `MFTS_PYTHON`.
- takeaway: The Python environment is part of evidence lineage, not a local convenience.

### 2026-07-16 | ODS migration invalidates earlier model and P2 generations until rebuilt
- tags: ods, model_lineage, p2, promotion, evidence_lineage
- reusable: yes
- confidence: high
- evidence: The newest local model predates the ODS migration and has no embedded market-data snapshot or price-mode lineage. Existing raw-model, P2, and promotion artifacts were generated against the retired local parquet generation.
- action: Treat pre-ODS artifacts as historical diagnosis only. Rebuild raw-universe model evidence first, then profile-isolated daily signals and 60/90/120 P2 evidence from one frozen ODS generation.
- takeaway: A data-source generation break resets promotion evidence even when code paths and column names remain compatible.

### 2026-07-16 | Active documentation, skills, and memory must share the same evidence contract
- tags: documentation, skills, memory, ods, governance
- reusable: yes
- confidence: high
- evidence: The documentation audit found active deployment/training/cron guidance still referencing `.venv`, legacy downloaders, H=3, and pre-ODS profile evidence after production data had moved to read-only ODS. The repo skill also listed the retired updater as a production entry point, and generated active memory referenced the deleted local parquet calendar.
- action: Keep active docs, the repo-local audit skill, and memory aligned on Conda `stock`, read-only manifest-backed ODS, adjusted-research/raw-execution price separation, PIT metadata, official execution limits, and evidence-generation identity. Preserve old commands and results only behind explicit historical labels.
- takeaway: Governance text is part of the execution control plane; stale instructions can recreate an already-retired evidence path.

### 2026-07-16 | Expert review must follow the evidence dependency graph
- tags: expert_review, governance, ods, model_lineage, promotion
- reusable: yes
- confidence: high
- evidence: After the ODS migration, the expert brief still suggested refreshing P2 before review even though adjusted-price, PIT-universe, official-limit, manifest, and model-horizon P0 issues invalidate downstream evidence. The review prompt was updated to treat v7-v29 numbers as historical-only and request a staged P0 repair and evidence-rebuild plan.
- action: Ask experts to review data/PIT and model contracts before capacity/P2/promotion. Do not request or refresh downstream evidence merely to make a review package look current when its upstream generation is known to be invalid.
- takeaway: Independent review is most useful when its questions respect causal evidence order.

### 2026-07-16 | External review should be adjudicated finding by finding
- tags: expert_review, governance, raw_model, execution, evidence_lineage
- reusable: yes
- confidence: high
- evidence: Review of commit `8bb8a5e` independently confirmed adjusted-price, PIT, manifest, model-lineage and official-limit risks, and added three material gaps: labels crossing split boundaries, P2 dropping/recomputing daily per-name targets, and open fills using same-day high/low/full amount. The review's universal 7/7 positive absolute-return rule was rejected in favor of 7/7 method validity plus preregistered statistical fold stability.
- action: Convert verified findings into phase gates and regression tests, but challenge reviewer-prescribed thresholds that are preferences rather than invariants. Record accepted, modified, and rejected advice in the design before implementation.
- takeaway: Independent scrutiny improves the project only when code facts are separated from methodological opinion.

### 2026-07-16 | P0 remediation must advance through explicit evidence states
- tags: p0, evidence_state, ods, model, p2, promotion
- reusable: yes
- confidence: high
- evidence: The approved remediation design defines `P0_BLOCKED`, `DIAGNOSTIC_ONLY`, `RAW_MODEL_ELIGIBLE`, `EXECUTION_ELIGIBLE`, and `PROMOTION_ELIGIBLE`, with five dependency-ordered implementation plans. Current ODS manifests may remain `freeze_pending`, so read access alone cannot imply formal evidence eligibility.
- action: Execute the master plan in order and stop when a phase gate fails. Do not infer progress from `latest` filenames or module/test counts, and do not start profile/P2 performance work from a diagnostic-only generation.
- takeaway: A machine-readable stop state is more valuable than another round of optimistic strategy tuning.
