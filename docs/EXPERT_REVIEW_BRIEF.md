# Expert Review Brief

> Review snapshot date: 2026-07-16
> Repository purpose: A-share daily quant research, portfolio construction, paper execution, diagnostics, and promotion governance.

## 2026-07-16 ODS Migration Audit Note

The project now reads the shared market-data root `/Users/max/Data/ashare-source-data` through the read-only ODS gateway. The old local market parquet has been retired and deleted. This creates a hard evidence-generation break: P2, promotion, raw-model, and profile artifacts generated before the migration are historical diagnostics only and are not valid promotion evidence for the ODS generation.

The current local audit identified unresolved P0 risks that the external reviewer should verify independently:

- Research bars are explicitly `unadjusted`; `daily_adj_factor` is joined but not applied to research features or labels.
- The historical panel joins one `instrument_master` snapshot as of the window end to every date in the window. The available historical master partitions are not proven PIT and can carry current names/ST/industry information into historical rows.
- ODS manifests are read but `available_at`, `visible_at`, row count, schema/hash and freeze status are not enforced by the adapter.
- Execution constructs `prev_close` from the prior raw close and infers board/ST limit ratios instead of consuming the provided `pre_close`, `up_limit`, and `down_limit` first.
- The newest local model binary predates the ODS migration, has no embedded market-data lineage, uses an `open_to_open` H=3 label, while the default `quality_regime` holding period is H=8.
- The default profile's latest daily evidence resolved to `score_weight` with zero portfolio-level industry cap, ADV cap and impact cost, and a regime-derived 6% single-name cap despite the profile's 4% configured cap.
- The latest H8/H10 raw-universe walk-forward verdict was `raw_walkforward_alpha_failed`; no current annualized return should be claimed.

Until these issues are fixed and the ODS-generation raw-model and 60/90/120 P2 evidence are regenerated, the project should be treated as research/paper infrastructure, not an investable strategy.

## Current Freshness Note

This brief is a review package, not a promotion artifact. Before sending it to an external expert, refresh the latest P2 rolling replay, shadow diagnosis, promotion review, and `memory/actives.md`.

Current operating state:

- Default profile remains `quality_regime`.
- v7-v26 are shadow/diagnostic profiles unless a formal promotion review says otherwise.
- Recent evidence after v18-v26 suggests the main unresolved issue is not a simple ADV-only bottleneck. The active risks are post-filter alpha quality, target-weight lineage, style-gate口径, cash drag, capacity fallback illusions, and T+1 sell-trap behavior.
- v23's NAV-weighted style exposure reduced executable-pool halts and raised target utilization, but worsened NAV/MDD under higher deployment, so it is diagnostic only.
- v25/v26 tested whether positive liquidity-score spread could survive target-weight construction. v25's apparent 60-day P2 improvement was mostly low exposure; v26 deployed more credibly after NAV-weighted style exposure, but after capacity fallback repair it failed the hardened score-alpha gate.

## 0. Review Escalation Policy

External expert review is not a per-iteration ritual. It should be requested only when the project reaches genuine uncertainty, a strategic fork, an unresolved methodology or execution-credibility risk, or a near-promotion/default-profile decision that needs independent scrutiny. If the next local patch, replay, attribution, or promotion artifact is clear, the agent should keep progressing locally and document evidence instead of asking for expert review.

When review is needed, the repository should first be prepared as a clean GitHub snapshot, then the user should receive a complete expert prompt covering the expert role, current state, evidence paths, unresolved questions, and the exact decisions needing review.

## 1. What This Project Is

This repository is an A-share daily stock-selection and paper-execution platform. The goal is not live broker connectivity yet. The current goal is to make the full chain credible:

`research signal -> daily selection -> portfolio construction -> backtest -> pretrade risk -> P2 paper replay -> shadow diagnosis -> promotion governance -> memory loop`

The project should be reviewed as a quant strategy platform under development, not as a finished production trading system.

## 2. Main Entry Points For Review

- `README.md`: project navigation and run commands.
- `docs/PROJECT_INDEX.md`: repository map and operating conventions.
- `config/quant_live_profiles.json`: default and candidate profile definitions.
- `core/platform/portfolio_engine.py`: target-weight generation and portfolio constraints.
- `core/risk/pretrade.py`: pretrade risk checks.
- `scripts/daily_ml_select.py`: daily ML and ranking selection.
- `scripts/quant_portfolio_backtest.py`: portfolio backtest path.
- `scripts/quant_p2_paper_trade.py`: P2 paper execution.
- `scripts/quant_p2_rolling_replay.py`: rolling P2 replay.
- `scripts/quant_p2_shadow_diagnosis.py`: profile shadow diagnosis.
- `scripts/quant_alpha_execution_attribution.py`: alpha-to-execution attribution.
- `scripts/quant_profile_promotion_review.py`: profile promotion gate.
- `schemas/promotion_decision.schema.json`: promotion decision evidence schema.
- `memory/README.md`, `memory/actives.md`, `memory/learnings.md`: project memory loop.
- `tests/`: unit and integration-style coverage.

Generated outputs in `output/`, logs in `logs/`, trained model binaries in `models/*.pkl`, and large local market data files are intentionally not tracked in Git.

## 3. Strategy Architecture

- Research signal layer: ML score, signal quality score, feature refactor/stability score, liquidity score, and execution overlay score.
- Ranking layer: candidate ordering. The intended direction is that ranking chooses candidates, while the portfolio engine owns final target weights.
- Filter and gate layer: A-share tradability filters, ST and special-board exclusions, limit-up/limit-down handling, suspension handling, minimum price, minimum traded value, ADV participation, industry, and style gates.
- Portfolio construction layer: moving toward capacity-aware and crowding-aware target-weight generation with single-name, industry, ADV, style, and turnover/cost constraints.
- Execution layer: P2 paper trade, rolling replay, shadow compare, execution consistency reports, and research-to-execution funnel diagnostics.
- Governance layer: profile promotion review, schema validation, apply gate, and memory-assisted operating discipline.

## 4. Current Profile State

- Current default profile: `quality_regime`.
- v7 shadow profile: `quality_regime_candidate_v7_industry_balance`.
- v8 shadow profile: `quality_regime_candidate_v8_reserve_pool`.
- v9 shadow profile: `quality_regime_candidate_v9_exec_state`.
- v12 shadow profile: `quality_regime_candidate_v12_tradability_safe`.
- v13 shadow profile: `quality_regime_candidate_v13_reserve_cap`.
- v14 shadow profile: `quality_regime_candidate_v14_exit_trap_budget`.
- v15 shadow profile: `quality_regime_candidate_v15_volume_drought_trap`.
- v16-v26 are later diagnostic profiles around holiday-gap guards, balanced trap guards, liquidity/quality alpha, safe primary ranking, target-score overrides, low-volume filter relaxation, NAV-weighted style exposure, conditional holiday-gap caps, liquidity target scoring, and capacity fallback repair.
- v7 direction is judged correct on industry concentration, but it has not yet delivered enough execution-layer NAV improvement.
- v7 should not be promoted now.
- v8 implements reserve-pool execution repair: expanded candidates, capacity-clip redistribution, and P2 pretrade replacement for buy-side tradability/ADV/industry blocks. It is not promoted by default.
- v9 extends v8 without loosening risk: upstream capacity-safe reserve ranking plus a blocked-order state machine that tracks trapped sells and can freeze new buys when blocked sell exposure is material. It is not promoted by default.
- v12 adds signal-date-known tradability-safe ranking and reserve ordering. It improves observability but does not solve sell traps.
- v13 adds a portfolio-level reserve exposure cap (`target_max_reserve_weight`) and promotion hard evidence for reserve-sourced sell traps. It is a risk-control diagnostic, not a promotion candidate.
- v14 adds entry-time exit-trap scoring, a portfolio-level high-exit-risk budget, and sell-trap predictor diagnostics. Its first smoke test is diagnostic only and not promotion evidence.
- v15 uses full-universe sell-trap feature study evidence to emphasize volume-drought risk, but its first smoke test is diagnostic only and not promotion evidence.

## 5. Latest v7 Evidence Summary

Latest local P2 and shadow evidence indicates:

- v7 60/90/120 day P2 NAV: about `-0.67% / -1.08% / -1.13%`.
- v7 60/90/120 target-weight mean: about `21.0% / 27.0% / 30.5%`.
- v7 60/90 day position utilization is too low.
- v7 invested-weight top industry concentration: about `31.86%`, which passes the 32% target.
- v7 NAV-weight top industry concentration: about `6.21%`, which passes the 24% target.
- v7 ADV blocked rows: about `105`, still above the hard target of `<100`.
- The late-March blocked-order cluster was driven mainly by `entry_not_tradable` and `exit_not_tradable`, not purely by ADV.
- Current promotion decision should remain `keep`, with `quality_regime` as default.

These figures are copied into this brief to give external reviewers context without committing the full local `output/` artifact tree.

## 6. Latest v8 Evidence Summary

Fresh local v8 evidence was generated with profile-isolated daily signals, not shared daily files:

- v8 60/90/120 day P2 NAV: about `-5.33% / -11.74% / -16.09%`.
- v8 60/90/120 max drawdown: about `-8.10% / -12.78% / -16.79%`.
- v8 60/90/120 target-weight mean: about `34.3% / 36.1% / 37.2%`.
- v8 60/90/120 executed days: `47 / 77 / 107`, with `13` failed/no-trade days in each window.
- v8 shadow diagnosis shows mean invested-weight top industry about `21.70%` and mean NAV-weight top industry about `6.26%`, so average industry concentration is improved.
- v8 ADV/risk blocked rows remain severe: shadow diagnosis reports about `1017` ADV-blocked rows across 60/90/120.
- The largest execution breaks remain clustered around `2026-03-30` and `2026-04-07`, with heavy `entry_not_tradable` and `exit_not_tradable` blocks.
- v8 alpha attribution is not convincing: artifact-based raw ML top mean forward return is about `-0.32%`, optimizer-stage mean forward return about `-1.06%`, and P2-fill mean forward return about `-0.16%`.

Interpretation: v8 is a more honest execution-repair profile because it raises deployed target weight versus v7, but it does not pass NAV/MDD, ADV, or executed-day evidence. It should remain shadow.

## 7. v9 Implementation And Latest Evidence

v9 was introduced to address the specific execution breaks exposed by v8, especially 2026-03-30 and 2026-04-07 style clusters:

- Profile: `quality_regime_candidate_v9_exec_state`.
- Risk posture: no promotion, no default switch, no loosened industry/ADV caps to chase return.
- Reserve generation: `daily_ml_select.py` now emits `portfolio_rank_score`, `reserve_safe_score`, and `reserve_capacity_score` so the expanded reserve pool can prefer capacity-safe, liquid, less crowded candidates after the primary TopN.
- P2 weighting: `quant_p2_paper_trade.py` can consume `portfolio_rank_score` via `target_score_col`, keeping v9 reserve ordering aligned with the upstream selection file.
- Blocked-order state: `core/execution/paper_broker.py` now persists active blocked buy/sell state, tracks blocked sell exposure, blocked consecutive days, and blocked target weights.
- Sell-side trap handling: if a blocked sell exceeds the configured threshold, v9 can freeze new buys with `blocked_exit_freeze` rather than treating failed sells as freed risk budget.
- Replay evidence: `quant_p2_rolling_replay.py` now summarizes blocked-sell exposure, freeze days/orders/weights, blocked-state max counts/consecutive days, and executable-pool halt days when pretrade removes the whole buy pool.

A data-unit sanity fix materially changed the v9 diagnosis. Several recent dates in the local market data used spot-style units for `amount` and `vol` while adjacent dates used normal RMB and hand-like units. The runtime now applies date-level normalization through `utils/market_data_units.py` in daily selection, P2 replay, and portfolio backtest loaders. The raw parquet file is not rewritten.

After this normalization, the earlier "ADV collapse" evidence should be considered stale. Fresh local v9 evidence was generated with profile-isolated daily files and the normalized loader path:

- v9 60/90/120 P2 NAV: about `-2.62% / -4.69% / -4.17%`.
- v9 60/90/120 max drawdown: about `-7.91% / -7.95% / -7.93%`.
- v9 60/90/120 target-weight mean: about `38.5% / 38.6% / 38.8%`.
- v9 60/90/120 replay coverage: `60 / 90 / 119` executed days, `0` failed days.
- v9 executable-pool halt days are now `0 / 0 / 0`; ADV halt hits are also `0 / 0 / 0`.
- Broker-layer `entry_not_tradable_orders` are `0 / 0 / 0`, while broker-layer `exit_not_tradable_orders` are `35 / 44 / 44`.
- Focused bottleneck diagnosis still finds sell-trap clusters: `10 / 20 / 20` sell-trap days across 60/90/120 focus windows, with reserve-entry blocked sell orders around `27 / 26 / 26`.
- v9 shadow diagnosis shows mean invested top-industry weight about `25.57%`, mean NAV-weight top-industry weight about `6.39%`, and total broker tradability block orders `123`.
- Formal promotion review `quant_profile_promotion_review_20260427_153053` kept the default profile as `quality_regime`. v9 failed hard gates for tradability block clusters, sell-trap clusters, severe sell-trap evidence, and reserve-sourced sell traps.

The same normalized replay also changes the main-profile baseline:

- `quality_regime` 60/90/120 P2 NAV: about `-4.35% / -7.15% / -4.32%`.
- `quality_regime` 60/90/120 max drawdown: about `-5.72% / -7.96% / -8.22%`.
- `quality_regime` 60/90/120 target-weight mean: about `28.9% / 25.8% / 25.6%`.
- Main-profile `2026-03-19` and `2026-03-20` are now explicit `empty_after_universe_filter` days because the shared daily files were BJ/9-code-only under the default universe filter.
- Main profile still has executable-pool halt days `7 / 13 / 19`, driven by style/tradability gates rather than ADV.

Cluster interpretation:

- The earlier conclusion "v9 is mainly ADV-broken" is no longer valid after unit normalization.
- v9 improved target-weight utilization and removed false executable-pool halt evidence, but higher exposure revealed weaker realized NAV and persistent sell traps.
- `2026-04-07` remains a severe sell-side execution-break date across profiles.
- v9 should remain shadow and must not be promoted. The current problem is not simply reserve-pool capacity; it is execution-after-alpha quality plus T+1 sell-trap risk.

## 8. v10-v17 Execution Evidence Updates

- v10 split P2 evidence into `empty_signal_raw`, `empty_after_universe_filter`, `executable_pool_halt`, and broker tradability blocks. This prevents BJ-only/no-signal days from masquerading as P2 process failure.
- v11 made sell-trap clusters stateful promotion evidence: active blocked-sell exposure, consecutive blocked days, and buy freezes now survive across replay days.
- v12 added tradability-safe upstream scoring using only signal-date-known fields. A 10-day smoke over `2026-03-23` to `2026-04-03` still had NAV about `-1.88%`, target-weight mean about `11.6%`, broker exit-not-tradable orders `44`, and executable-pool halt days `4`.
- v13 capped reserve exposure at `10%` of NAV. Before the data-unit fix, the same 10-day smoke improved NAV to about `-0.44%`, reduced broker exit-not-tradable orders to `22`, and reduced reserve-entry blocked sell orders from `36` to `15`, but target-weight mean fell to about `8.5%` and halt days stayed at `4`.
- After the data-unit fix, v13 10-day target-weight mean rose to about `28.2%`, ADV halt hits dropped to zero, halt days fell to `2`, and reserve-entry blocked sell orders fell to `4`; however NAV worsened to about `-1.07%`, confirming that better investability did not create better alpha.
- v13 is therefore useful evidence that reserve pool exposure can amplify sell traps, but it is not proof of better alpha. Lower exposure cannot be accepted as promotion-quality improvement.
- v14 adds `exit_trap_safe_score`, `exit_trap_risk_score`, `exit_trap_downside_headroom_pct`, portfolio `target_max_exit_trap_weight`, and P2 lineage fields for blocked sells. A 10-day smoke over `2026-03-23` to `2026-04-03` produced NAV about `-1.36%`, MDD about `-1.99%`, target-weight mean about `36.0%`, broker entry-not-tradable orders `0`, broker exit-not-tradable orders `22`, and sell-trap days `6`.
- v14 is not an improvement over v13. It raised invested exposure and removed buy-side order blocks, but sell-trap weight rose and NAV/MDD worsened.
- `scripts/quant_sell_trap_predictor_diagnosis.py` was added to validate whether entry-time scores predict later blocked sells. In the v14 10-day smoke, blocked sell orders had lower entry exit-trap risk than filled sell orders (`0.127` vs `0.172`), high-risk recall was `0%`, and `predictor_direction_ok=False`.
- Interpretation: simple signal-date limit-down/volume pressure rules are not enough to forecast A-share sell traps. Do not promote or tune v14 until sell-trap prediction is validated on a larger sample.
- `scripts/quant_sell_trap_feature_study.py` was added to study full-universe, signal-date-known features against future 5-day exit blocks. On 520 recent trading days (`2024-01-24` to `2026-04-07`, about `2.64M` rows), the strongest feature was `vol_ratio_low_risk`: Spearman about `0.387`, top-decile future exit-block rate about `12.89%` versus base rate about `2.50%`.
- v15 converts that finding into a volume-drought-focused shadow profile and preserves new P2 lineage fields such as `exit_trap_volume_drought_risk`, `exit_trap_drawdown_10d_pct`, `exit_trap_down_momentum_5d`, and `exit_trap_volatility_10d`.
- v15 10-day smoke over `2026-03-23` to `2026-04-03` produced NAV about `-2.17%`, MDD about `-2.27%`, target-weight mean about `33.9%`, broker entry-not-tradable orders `0`, broker exit-not-tradable orders `24`, max blocked-sell current weight about `36.2%`, and reserve-entry blocked sell orders `4`.
- v15 predictor diagnosis showed directionally higher volume-drought and exit-risk means for blocked sells than filled sells, but threshold recall remained poor and the 2026-04-07 cluster still had volume-drought weighted mean near `0`. Therefore v15 is not an improvement; the sell-trap problem likely requires holding-state, holiday-gap, and market-wide liquidity stress logic rather than more entry-score blending.
- v16 adds a holiday-gap guard that caps target exposure before/after long calendar gaps. A first smoke exposed a P2 evidence bug: the profile daily file for `2026-04-02` correctly had upstream target-weight sum `18%`, but P2 re-optimized the 2026-04-03 trade day back to about `38.6%`. This meant execution replay was overrunning the research/portfolio-layer budget.
- The P2 path now derives reserve re-optimization `total_target` and `max_single` from upstream daily `target_weight` when present, and rolling replay reports `upstream_target_weight_overrun_max` / `underuse_max`. Promotion hard-fails positive upstream target-weight overrun.
- After that fix, v16 60/90/120 profile-isolated P2 replay produced NAV about `-1.77% / -2.14% / -2.84%`, MDD about `-6.39% / -6.37% / -6.36%`, target-weight mean about `32.0% / 31.6% / 31.1%`, and `upstream_target_weight_overrun_max=0`. It is cleaner evidence, not a promotable profile.
- Formal promotion review `20260427_183644` kept `quality_regime` as default. v16 failed for weak research rolling score, P2 objective below main, worse tradability/sell-trap clusters, reserve-sourced sell traps, and executable-pool halt hard gates.
- P2 now treats an explicit `target_weight` column as authoritative even when all weights are zero. This prevents future risk-off or pre-holiday zero-budget daily files from being silently re-expanded by score-weight fallback.
- v17 `quality_regime_candidate_v17_holiday_exit_trap_guard` tests a stricter long-gap cap (`6%` total / `0.6%` single) and mild exit-trap budget. A 10/20-day smoke over the late-March/early-April cluster reduced max blocked-sell current weight to about `4.3%`, but target-weight mean collapsed to about `9.0% / 5.8%` and executable-pool halt days rose to `2 / 8`. v17 is therefore an extreme-risk diagnostic, not a promotion candidate.

## 9. Known Open Problems

The next review should be especially strict on these points:

1. Research-layer alpha may not yet survive execution-layer constraints.
2. Capacity clipping can leave too much cash, especially in 60/90 day windows.
3. P2 execution must prove no upstream target-weight overrun; reserve replacement may not expand the daily target budget.
4. Late-March blocked orders expose an execution break around T+1 tradability, limit-up/limit-down, and suspension behavior.
5. Industry concentration has improved, but effective deployed capital and post-execution NAV still need proof.
6. Profile promotion must reject candidates that win only by holding excess cash or benefiting from incomplete execution modeling.
7. v8 reserve-pool evidence now shows better target-weight utilization but worse execution-layer NAV and drawdown; it should not be promoted.
8. Profile-specific daily signal calendars are mandatory for fair replay. Shared daily fallback can contaminate candidate evidence.
9. v9 must prove that capacity-safe reserves and blocked-order freezing reduce cash shortfall and false buying power without worsening realized NAV/MDD.
10. Historical ADV diagnostics from before `utils/market_data_units.py` should be treated as stale unless rerun through normalized loaders.
11. The next real problem is not raw ADV capacity alone; it is style/tradability gate interaction, sell-trap state, and whether the raw alpha remains positive once the book is actually invested.
12. v14 shows that naive entry-time sell-trap scores can be anti-predictive. Predictor validation must come before more sell-trap budget tuning.
13. v15 shows that even a stronger full-universe volume-drought feature does not automatically improve P2. The 2026-04-07 sell-trap cluster is not explained by signal-date low volume alone.
14. v16 shows that holiday-gap guards are useful only after target-budget lineage is enforced; remaining sell traps need position-level unwind policy.

## 10. What Expert Review Should Decide

The review should answer:

- Is the system a credible evolving quant platform, or mostly a complex backtest framework?
- Where is the most likely pseudo-alpha?
- Does the current backtest/paper chain avoid material look-ahead and execution overstatement?
- Is the portfolio engine mature enough, or should the objective function be made more explicit?
- Are the promotion gates hard enough for real A-share constraints?
- Do v9-v23 execution and alpha-quality repairs correctly address the 2026-03-30 / 2026-04-07 execution breaks before any risk loosening, or are they mainly changing exposure, cash drag, and observability?
