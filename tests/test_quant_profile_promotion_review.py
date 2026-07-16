# -*- coding: utf-8 -*-
"""Profile 升档评审测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import scripts.quant_profile_promotion_review as review


def test_detect_profile_from_name_prefers_longest_match():
    profiles = ["quality_regime", "quality_regime_candidate"]
    name = "paper_replay_quality_regime_candidate_60_g1_20260424_001324_ledger.csv"
    assert review._detect_profile_from_name(name, profiles) == "quality_regime_candidate"


def test_build_promotion_review_keeps_candidate_in_shadow_when_p2_days_insufficient():
    research_df = pd.DataFrame(
        [
            {
                "profile": "quality_regime",
                "window_count": 5,
                "hard_pass_rate": 0.2,
                "annual_return_mean": 2.5,
                "annual_return_median": -4.0,
                "excess_annual_mean": 2.0,
                "excess_annual_median": 7.0,
                "max_drawdown_worst": -6.4,
                "sharpe_mean": 1.0,
                "sortino_mean": -0.1,
                "profit_factor_mean": 2.8,
                "tail_ratio_mean": 1.6,
                "rank_score_mean": 10.3,
                "objective_score": 2.5,
            },
            {
                "profile": "quality_regime_candidate",
                "window_count": 5,
                "hard_pass_rate": 0.6,
                "annual_return_mean": 10.0,
                "annual_return_median": 8.4,
                "excess_annual_mean": 8.1,
                "excess_annual_median": 12.9,
                "max_drawdown_worst": -4.3,
                "sharpe_mean": 1.2,
                "sortino_mean": 1.3,
                "profit_factor_mean": 3.2,
                "tail_ratio_mean": 2.2,
                "rank_score_mean": 16.3,
                "objective_score": 14.3,
            },
        ]
    )
    p2_df = pd.DataFrame(
        [
            {
                "profile": "quality_regime",
                "p2_replay_count": 2,
                "p2_executed_days_total": 30,
                "p2_executed_days_mean": 15.0,
                "p2_nav_return_mean": 1.2,
                "p2_max_drawdown_worst": -1.0,
                "p2_exec_block_rate_mean": 0.0,
                "p2_risk_block_rate_mean": 18.0,
                "p2_style_hit_rate_mean": 0.0,
                "p2_objective_mean": 0.8,
                "p2_min_days_gate": 1,
            },
            {
                "profile": "quality_regime_candidate",
                "p2_replay_count": 1,
                "p2_executed_days_total": 5,
                "p2_executed_days_mean": 5.0,
                "p2_nav_return_mean": 0.5,
                "p2_max_drawdown_worst": -1.2,
                "p2_exec_block_rate_mean": 0.0,
                "p2_risk_block_rate_mean": 16.0,
                "p2_style_hit_rate_mean": 0.0,
                "p2_objective_mean": 0.6,
                "p2_min_days_gate": 0,
            },
        ]
    )

    out = review._build_promotion_review(research_df, p2_df, main_profile="quality_regime")

    candidate = out[out["profile"] == "quality_regime_candidate"].iloc[0]
    main = out[out["profile"] == "quality_regime"].iloc[0]
    assert candidate["decision"] == "shadow_only"
    assert main["decision"] == "keep_main"


def test_summarize_p2_ledgers_groups_profiles_correctly(tmp_path: Path):
    ledger = pd.DataFrame(
        {
            "nav_pre": [1_000_000.0, 1_001_000.0],
            "nav_post": [1_001_000.0, 1_002_500.0],
            "turnover": [200_000.0, 180_000.0],
            "filled_orders": [10, 11],
            "partial_orders": [0, 0],
            "blocked_orders": [0, 0],
            "rejected_orders": [0, 0],
            "risk_input_count": [15, 15],
            "risk_blocked_count": [2, 1],
            "risk_style_limits_hit": [0, 0],
            "risk_style_size_limits_hit": [0, 0],
            "risk_style_beta_limits_hit": [0, 0],
            "risk_style_momentum_limits_hit": [0, 0],
            "risk_style_vol_limits_hit": [0, 0],
        }
    )
    f1 = tmp_path / "paper_replay_quality_regime_60_g1_20260424_ledger.csv"
    f2 = tmp_path / "paper_replay_quality_regime_candidate_60_g1_20260424_ledger.csv"
    ledger.to_csv(f1, index=False, encoding="utf-8-sig")
    ledger.to_csv(f2, index=False, encoding="utf-8-sig")

    out = review._summarize_p2_ledgers(
        ["quality_regime", "quality_regime_candidate"],
        [f1, f2],
        min_days=2,
    )

    assert set(out["profile"]) == {"quality_regime", "quality_regime_candidate"}
    assert int(out.loc[out["profile"] == "quality_regime_candidate", "p2_executed_days_total"].iloc[0]) == 2


def test_load_p2_summary_derives_signal_calendar_coverage_from_signal_days(tmp_path: Path):
    summary = tmp_path / "p2_summary.csv"
    pd.DataFrame(
        [
            {
                "profile": "quality_regime",
                "window": 60,
                "signal_days": 60,
                "executed_days": 60,
                "nav_return_pct": 1.0,
                "max_drawdown_pct": -1.0,
                "exec_block_rate_pct": 0.0,
                "risk_block_rate_pct": 0.0,
                "style_hit_rate_pct": 0.0,
                "target_weight_sum_mean": 0.40,
                "objective_score": 1.0,
            },
            {
                "profile": "quality_regime_candidate",
                "window": 60,
                "signal_days": 20,
                "executed_days": 20,
                "nav_return_pct": 2.0,
                "max_drawdown_pct": -0.8,
                "exec_block_rate_pct": 0.0,
                "risk_block_rate_pct": 0.0,
                "style_hit_rate_pct": 0.0,
                "target_weight_sum_mean": 0.35,
                "objective_score": 2.0,
            },
        ]
    ).to_csv(summary, index=False, encoding="utf-8-sig")

    out, _ = review._load_or_build_p2_summary(
        p2_summary_file=summary,
        profiles=["quality_regime", "quality_regime_candidate"],
        ledger_glob="none",
        min_days=20,
        main_profile="quality_regime",
    )

    candidate = out[out["profile"] == "quality_regime_candidate"].iloc[0]
    assert float(candidate["p2_signal_calendar_shortfall_days_max"]) == 40.0
    assert round(float(candidate["p2_signal_calendar_coverage_min_pct"]), 2) == 33.33


def test_build_promotion_decision_holds_without_margin_or_gate():
    review_df = pd.DataFrame(
        [
            {
                "profile": "quality_regime_candidate",
                "promotion_score": 8.0,
                "research_score": 15.0,
                "ops_score": -5.0,
                "p2_executed_days_total": 13,
                "p2_min_days_gate": 0,
                "decision": "shadow_only",
            },
            {
                "profile": "quality_regime",
                "promotion_score": 1.0,
                "research_score": 3.0,
                "ops_score": -3.0,
                "p2_executed_days_total": 32,
                "p2_min_days_gate": 1,
                "decision": "keep_main",
            },
        ]
    )

    decision = review._build_promotion_decision(
        review_df,
        main_profile="quality_regime",
        min_promote_margin=1.0,
        review_id="r1",
        min_p2_executed_days=20,
        review_csv="review.csv",
        review_meta_json="review.json",
    )
    assert decision["decision"] == "keep"
    assert decision["final_default_profile"] == "quality_regime"
    assert decision["reason_code"] == "candidate_p2_gate_failed"


def test_build_promotion_decision_promotes_when_gate_and_margin_pass():
    review_df = pd.DataFrame(
        [
            {
                "profile": "quality_regime_candidate",
                "promotion_score": 12.0,
                "research_score": 14.0,
                "ops_score": 6.0,
                "p2_executed_days_total": 40,
                "p2_min_days_gate": 1,
                "decision": "promote_candidate",
            },
            {
                "profile": "quality_regime",
                "promotion_score": 8.5,
                "research_score": 5.0,
                "ops_score": 2.0,
                "p2_executed_days_total": 32,
                "p2_min_days_gate": 1,
                "decision": "keep_main",
            },
        ]
    )

    decision = review._build_promotion_decision(
        review_df,
        main_profile="quality_regime",
        min_promote_margin=1.0,
        review_id="r2",
        min_p2_executed_days=20,
        review_csv="review.csv",
        review_meta_json="review.json",
    )
    assert decision["decision"] == "promote"
    assert decision["final_default_profile"] == "quality_regime_candidate"
    assert decision["change_required"] is True


def test_build_promotion_decision_holds_when_candidate_execution_underperforms():
    review_df = pd.DataFrame(
        [
            {
                "profile": "quality_regime_candidate",
                "promotion_score": 12.0,
                "research_score": 14.0,
                "ops_score": -10.0,
                "p2_objective_mean": -15.0,
                "p2_executed_days_total": 40,
                "p2_min_days_gate": 1,
                "decision": "promote_candidate",
            },
            {
                "profile": "quality_regime",
                "promotion_score": 8.0,
                "research_score": 5.0,
                "ops_score": -8.0,
                "p2_objective_mean": -12.0,
                "p2_executed_days_total": 40,
                "p2_min_days_gate": 1,
                "decision": "keep_main",
            },
        ]
    )

    decision = review._build_promotion_decision(
        review_df,
        main_profile="quality_regime",
        min_promote_margin=1.0,
        review_id="r3",
        min_p2_executed_days=20,
        review_csv="review.csv",
        review_meta_json="review.json",
    )
    assert decision["decision"] == "keep"
    assert decision["reason_code"] == "candidate_execution_underperformed"
    assert decision["final_default_profile"] == "quality_regime"


def test_promotion_hard_gate_rejects_industry_concentration_regression():
    research_df = pd.DataFrame(
        [
            {
                "profile": "quality_regime",
                "window_count": 4,
                "hard_pass_rate": 0.4,
                "annual_return_mean": 4.0,
                "annual_return_median": 3.0,
                "excess_annual_mean": 2.0,
                "excess_annual_median": 1.0,
                "max_drawdown_worst": -5.0,
                "sharpe_mean": 1.0,
                "sortino_mean": 1.0,
                "profit_factor_mean": 1.5,
                "tail_ratio_mean": 1.2,
                "rank_score_mean": 8.0,
                "objective_score": 5.0,
            },
            {
                "profile": "quality_regime_candidate_v4_exec",
                "window_count": 4,
                "hard_pass_rate": 0.8,
                "annual_return_mean": 10.0,
                "annual_return_median": 8.0,
                "excess_annual_mean": 7.0,
                "excess_annual_median": 6.0,
                "max_drawdown_worst": -4.0,
                "sharpe_mean": 1.5,
                "sortino_mean": 1.4,
                "profit_factor_mean": 2.0,
                "tail_ratio_mean": 1.6,
                "rank_score_mean": 15.0,
                "objective_score": 15.0,
            },
        ]
    )
    p2_df = pd.DataFrame(
        [
            {
                "profile": "quality_regime",
                "p2_executed_days_total": 80,
                "p2_nav_return_mean": 1.0,
                "p2_max_drawdown_worst": -1.0,
                "p2_exec_block_rate_mean": 0.0,
                "p2_risk_block_rate_mean": 10.0,
                "p2_style_hit_rate_mean": 0.0,
                "p2_objective_mean": 1.0,
                "p2_min_days_gate": 1,
                "shadow_executed_days_total": 80,
                "shadow_adv_blocked_rows_total": 10,
                "shadow_mean_top_industry_weight_pct": 30.0,
                "shadow_worst_top_industry_weight_pct": 45.0,
            },
            {
                "profile": "quality_regime_candidate_v4_exec",
                "p2_executed_days_total": 80,
                "p2_nav_return_mean": 2.0,
                "p2_max_drawdown_worst": -1.0,
                "p2_exec_block_rate_mean": 0.0,
                "p2_risk_block_rate_mean": 8.0,
                "p2_style_hit_rate_mean": 0.0,
                "p2_objective_mean": 2.0,
                "p2_min_days_gate": 1,
                "shadow_executed_days_total": 80,
                "shadow_adv_blocked_rows_total": 10,
                "shadow_mean_top_industry_weight_pct": 40.0,
                "shadow_worst_top_industry_weight_pct": 70.0,
            },
        ]
    )

    out = review._build_promotion_review(research_df, p2_df, main_profile="quality_regime")
    candidate = out[out["profile"] == "quality_regime_candidate_v4_exec"].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "industry_concentration_hard_cap_failed" in candidate["promotion_hard_gate_reasons"]
    assert candidate["decision"] == "shadow_only"

    decision = review._build_promotion_decision(
        out,
        main_profile="quality_regime",
        min_promote_margin=1.0,
        review_id="r4",
        min_p2_executed_days=20,
        review_csv="review.csv",
        review_meta_json="review.json",
    )
    assert decision["decision"] == "keep"
    assert decision["reason_code"] == "candidate_hard_gate_failed"


def _minimal_research_for_gate(candidate: str = "candidate") -> pd.DataFrame:
    base = {
        "window_count": 4,
        "hard_pass_rate": 0.5,
        "annual_return_mean": 5.0,
        "annual_return_median": 4.0,
        "excess_annual_mean": 3.0,
        "excess_annual_median": 2.0,
        "max_drawdown_worst": -4.0,
        "sharpe_mean": 1.0,
        "sortino_mean": 1.0,
        "profit_factor_mean": 1.5,
        "tail_ratio_mean": 1.2,
        "rank_score_mean": 8.0,
        "objective_score": 5.0,
    }
    cand = dict(base)
    cand.update({"profile": candidate, "hard_pass_rate": 0.9, "objective_score": 15.0})
    main = dict(base)
    main.update({"profile": "quality_regime"})
    return pd.DataFrame([main, cand])


def _minimal_p2_for_gate(candidate: str = "candidate", **candidate_overrides) -> pd.DataFrame:
    main = {
        "profile": "quality_regime",
        "p2_executed_days_total": 270,
        "p2_nav_return_mean": 1.0,
        "p2_max_drawdown_worst": -1.2,
        "p2_exec_block_rate_mean": 0.0,
        "p2_risk_block_rate_mean": 8.0,
        "p2_style_hit_rate_mean": 0.0,
        "p2_objective_mean": 1.0,
        "p2_min_days_gate": 1,
        "p2_window_count": 3,
        "p2_nav_not_below_main_windows": 3,
        "p2_mdd_not_worse_than_main_windows": 3,
        "p2_signal_calendar_shortfall_days_total": 0.0,
        "p2_signal_calendar_shortfall_days_max": 0.0,
        "p2_signal_calendar_coverage_min_pct": 100.0,
        "p2_target_weight_sum_mean": 0.36,
        "p2_target_weight_sum_60": 0.30,
        "p2_target_weight_source_external_rate_pct": 100.0,
        "p2_target_weight_checksum_coverage_pct": 100.0,
        "p2_entry_not_tradable_orders_sum": 10,
        "p2_exit_not_tradable_orders_sum": 5,
        "p2_broker_entry_not_tradable_orders_sum": 10,
        "p2_broker_exit_not_tradable_orders_sum": 5,
        "p2_broker_tradability_block_orders_sum": 15,
        "p2_blocked_target_weight_sum": 0.10,
        "p2_max_daily_tradability_blocked_orders": 5,
        "p2_empty_signal_days_total": 0.0,
        "p2_empty_signal_rate_mean_pct": 0.0,
        "p2_empty_signal_raw_days_total": 0.0,
        "p2_empty_after_universe_filter_days_total": 0.0,
        "p2_empty_signal_filtered_bj9_rows_sum": 0.0,
        "p2_executable_pool_halt_days_total": 0.0,
        "p2_executable_pool_halt_rate_mean_pct": 0.0,
        "p2_executable_pool_halt_days_max": 0.0,
        "p2_executable_pool_halt_adv_hit_sum": 0.0,
        "p2_executable_pool_halt_entry_not_tradable_hit_sum": 0.0,
        "p2_executable_pool_halt_style_hit_sum": 0.0,
        "shadow_executed_days_total": 270,
        "shadow_adv_blocked_rows_total": 80,
        "shadow_mean_top_industry_invested_weight_pct": 30.0,
        "shadow_mean_top_industry_nav_weight_pct": 20.0,
    }
    cand = dict(main)
    cand.update(
        {
            "profile": candidate,
            "p2_nav_return_mean": 2.0,
            "p2_max_drawdown_worst": -1.0,
            "p2_risk_block_rate_mean": 6.0,
            "p2_objective_mean": 2.0,
            "shadow_adv_blocked_rows_total": 70,
            "shadow_mean_top_industry_invested_weight_pct": 31.0,
            "shadow_mean_top_industry_nav_weight_pct": 22.0,
        }
    )
    cand.update(candidate_overrides)
    return pd.DataFrame([main, cand])


def test_promotion_hard_gate_rejects_nav_weight_industry_concentration():
    candidate_name = "quality_regime_candidate_v7_industry_balance"
    out = review._build_promotion_review(
        _minimal_research_for_gate(candidate_name),
        _minimal_p2_for_gate(candidate_name, shadow_mean_top_industry_nav_weight_pct=25.0),
        main_profile="quality_regime",
    )
    candidate = out[out["profile"] == candidate_name].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "industry_nav_concentration_hard_cap_failed" in candidate["promotion_hard_gate_reasons"]


def test_promotion_hard_gate_rejects_low_target_weight_sum():
    candidate_name = "quality_regime_candidate_v7_industry_balance"
    out = review._build_promotion_review(
        _minimal_research_for_gate(candidate_name),
        _minimal_p2_for_gate(candidate_name, p2_target_weight_sum_mean=0.20, p2_target_weight_sum_60=0.23),
        main_profile="quality_regime",
    )
    candidate = out[out["profile"] == candidate_name].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "target_weight_sum_mean_too_low" in candidate["promotion_hard_gate_reasons"]
    assert "target_weight_sum_60_too_low" in candidate["promotion_hard_gate_reasons"]


def test_promotion_hard_gate_rejects_long_window_nav_parity_failure():
    candidate_name = "quality_regime_candidate_v7_industry_balance"
    out = review._build_promotion_review(
        _minimal_research_for_gate(candidate_name),
        _minimal_p2_for_gate(candidate_name, p2_nav_not_below_main_windows=1),
        main_profile="quality_regime",
    )
    candidate = out[out["profile"] == candidate_name].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "p2_long_window_nav_parity_failed" in candidate["promotion_hard_gate_reasons"]


def test_promotion_hard_gate_rejects_adv_blocked_hard_cap():
    candidate_name = "quality_regime_candidate_v7_industry_balance"
    out = review._build_promotion_review(
        _minimal_research_for_gate(candidate_name),
        _minimal_p2_for_gate(candidate_name, shadow_adv_blocked_rows_total=101),
        main_profile="quality_regime",
    )
    candidate = out[out["profile"] == candidate_name].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "adv_blocked_rows_hard_cap_failed" in candidate["promotion_hard_gate_reasons"]


def test_promotion_hard_gate_rejects_target_weight_source_or_checksum_gap():
    candidate_name = "quality_regime_candidate_v8_execution_repair"
    out = review._build_promotion_review(
        _minimal_research_for_gate(candidate_name),
        _minimal_p2_for_gate(
            candidate_name,
            p2_target_weight_source_external_rate_pct=99.0,
            p2_target_weight_checksum_coverage_pct=80.0,
        ),
        main_profile="quality_regime",
    )
    candidate = out[out["profile"] == candidate_name].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "target_weight_source_not_external" in candidate["promotion_hard_gate_reasons"]
    assert "target_weight_checksum_missing" in candidate["promotion_hard_gate_reasons"]


def test_promotion_hard_gate_rejects_upstream_target_weight_overrun():
    candidate_name = "quality_regime_candidate_v16_holiday_gap_guard"
    out = review._build_promotion_review(
        _minimal_research_for_gate(candidate_name),
        _minimal_p2_for_gate(candidate_name, p2_upstream_target_weight_overrun_max=0.02),
        main_profile="quality_regime",
    )
    candidate = out[out["profile"] == candidate_name].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "upstream_target_weight_overrun" in candidate["promotion_hard_gate_reasons"]


def test_promotion_hard_gate_rejects_signal_calendar_shortfall():
    candidate_name = "quality_regime_candidate_v18_balanced_trap_guard"
    out = review._build_promotion_review(
        _minimal_research_for_gate(candidate_name),
        _minimal_p2_for_gate(
            candidate_name,
            p2_signal_calendar_shortfall_days_total=4.0,
            p2_signal_calendar_shortfall_days_max=4.0,
            p2_signal_calendar_coverage_min_pct=96.7,
        ),
        main_profile="quality_regime",
    )
    candidate = out[out["profile"] == candidate_name].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "p2_signal_calendar_shortfall" in candidate["promotion_hard_gate_reasons"]


def test_promotion_hard_gate_rejects_tradability_block_cluster():
    candidate_name = "quality_regime_candidate_v8_execution_repair"
    out = review._build_promotion_review(
        _minimal_research_for_gate(candidate_name),
        _minimal_p2_for_gate(
            candidate_name,
            p2_entry_not_tradable_orders_sum=25,
            p2_exit_not_tradable_orders_sum=20,
            p2_broker_entry_not_tradable_orders_sum=25,
            p2_broker_exit_not_tradable_orders_sum=20,
            p2_broker_tradability_block_orders_sum=45,
            p2_max_daily_tradability_blocked_orders=11,
        ),
        main_profile="quality_regime",
    )
    candidate = out[out["profile"] == candidate_name].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "tradability_blocked_orders_worse_than_main" in candidate["promotion_hard_gate_reasons"]
    assert "tradability_block_cluster_hard_cap_failed" in candidate["promotion_hard_gate_reasons"]


def test_promotion_hard_gate_rejects_empty_signal_rate():
    candidate_name = "quality_regime_candidate_v9_exec_state"
    out = review._build_promotion_review(
        _minimal_research_for_gate(candidate_name),
        _minimal_p2_for_gate(
            candidate_name,
            p2_empty_signal_days_total=18.0,
            p2_empty_signal_rate_mean_pct=6.0,
            p2_empty_after_universe_filter_days_total=18.0,
            p2_empty_signal_filtered_bj9_rows_sum=180.0,
        ),
        main_profile="quality_regime",
    )
    candidate = out[out["profile"] == candidate_name].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "empty_signal_rate_hard_cap_failed" in candidate["promotion_hard_gate_reasons"]
    assert "empty_signal_rate_worse_than_main" in candidate["promotion_hard_gate_reasons"]


def test_promotion_hard_gate_rejects_executable_pool_halt_rate():
    candidate_name = "quality_regime_candidate_v9_exec_state"
    out = review._build_promotion_review(
        _minimal_research_for_gate(candidate_name),
        _minimal_p2_for_gate(
            candidate_name,
            p2_executable_pool_halt_days_total=30.0,
            p2_executable_pool_halt_rate_mean_pct=12.0,
            p2_executable_pool_halt_days_max=10.0,
            p2_executable_pool_halt_adv_hit_sum=1416.0,
            p2_executable_pool_halt_entry_not_tradable_hit_sum=24.0,
            p2_executable_pool_halt_style_hit_sum=825.0,
        ),
        main_profile="quality_regime",
    )
    candidate = out[out["profile"] == candidate_name].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "executable_pool_halt_rate_hard_cap_failed" in candidate["promotion_hard_gate_reasons"]
    assert "executable_pool_halt_days_hard_cap_failed" in candidate["promotion_hard_gate_reasons"]


def test_load_halt_cluster_attribution_summarizes_profile_labels(tmp_path: Path):
    fp = tmp_path / "halt.csv"
    pd.DataFrame(
        [
            {
                "profile": "quality_regime_candidate_v9_exec_state",
                "signal_date": "2026-04-03",
                "trade_date": "2026-04-07",
                "attribution_label": "sell_trap",
                "broker_exit_not_tradable_orders": 34,
                "blocked_sell_current_weight": 0.35,
                "blocked_sell_reserve_entry_orders": 12,
                "blocked_sell_high_entry_risk_orders": 2,
            },
            {
                "profile": "quality_regime_candidate_v9_exec_state",
                "signal_date": "2026-03-26",
                "trade_date": "2026-03-27",
                "attribution_label": "adv_capacity_collapse",
                "risk_adv_hit": 8,
            },
        ]
    ).to_csv(fp, index=False, encoding="utf-8-sig")

    out = review._load_halt_cluster_attribution(fp, ["quality_regime_candidate_v9_exec_state"])
    row = out.iloc[0]
    assert int(row["halt_cluster_sell_trap_days"]) == 1
    assert int(row["halt_cluster_severe_sell_trap_days"]) == 1
    assert int(row["halt_cluster_adv_capacity_days"]) == 1
    assert float(row["halt_cluster_blocked_sell_weight_max"]) == 0.35
    assert int(row["halt_cluster_reserve_sell_trap_days"]) == 1
    assert float(row["halt_cluster_reserve_sell_trap_orders_sum"]) == 12.0
    assert float(row["halt_cluster_high_entry_risk_sell_orders_sum"]) == 2.0


def test_promotion_hard_gate_rejects_severe_sell_trap_cluster():
    candidate_name = "quality_regime_candidate_v9_exec_state"
    out = review._build_promotion_review(
        _minimal_research_for_gate(candidate_name),
        _minimal_p2_for_gate(
            candidate_name,
            halt_cluster_sell_trap_days=1,
            halt_cluster_severe_sell_trap_days=1,
            halt_cluster_broker_exit_orders_sum=34,
            halt_cluster_blocked_sell_weight_max=0.35,
        ),
        main_profile="quality_regime",
    )
    candidate = out[out["profile"] == candidate_name].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "halt_cluster_sell_trap_worse_than_main" in candidate["promotion_hard_gate_reasons"]
    assert "halt_cluster_severe_sell_trap_failed" in candidate["promotion_hard_gate_reasons"]


def test_promotion_hard_gate_rejects_reserve_sourced_sell_trap_cluster():
    candidate_name = "quality_regime_candidate_v13_reserve_cap"
    out = review._build_promotion_review(
        _minimal_research_for_gate(candidate_name),
        _minimal_p2_for_gate(
            candidate_name,
            halt_cluster_sell_trap_days=1,
            halt_cluster_severe_sell_trap_days=0,
            halt_cluster_reserve_sell_trap_orders_sum=5,
            halt_cluster_reserve_sell_trap_days=1,
        ),
        main_profile="quality_regime",
    )
    candidate = out[out["profile"] == candidate_name].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "halt_cluster_reserve_sell_trap_worse_than_main" in candidate["promotion_hard_gate_reasons"]
    assert "halt_cluster_reserve_sell_trap_failed" in candidate["promotion_hard_gate_reasons"]


def test_load_score_alpha_diagnosis_json_extracts_gate_evidence(tmp_path: Path):
    fp = tmp_path / "quant_score_alpha_diagnosis_latest_quality_regime_candidate_v23_nav_weighted_style_gate.json"
    fp.write_text(
        json.dumps(
            {
                "artifact_label": "quality_regime_candidate_v23_nav_weighted_style_gate",
                "alpha_quality_gate": {
                    "pass": False,
                    "reasons": ["no_gate_score_passed"],
                    "gate_score_cols": ["target_weight", "portfolio_rank_score"],
                    "evaluated": [
                        {
                            "score_col": "target_weight",
                            "top_days": 12,
                            "top_valid_forward_rows": 60,
                            "top_minus_all_pct": -1.2,
                            "top_minus_bottom_pct": -0.8,
                            "rank_ic_mean": -0.1,
                            "pass": False,
                            "reasons": ["top_not_above_pool_average"],
                        },
                        {
                            "score_col": "portfolio_rank_score",
                            "top_days": 12,
                            "top_valid_forward_rows": 60,
                            "top_minus_all_pct": -1.8,
                            "top_minus_bottom_pct": -1.1,
                            "rank_ic_mean": -0.2,
                            "pass": False,
                            "reasons": ["top_not_above_pool_average"],
                        },
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out = review._load_score_alpha_diagnosis(
        [fp],
        ["quality_regime", "quality_regime_candidate_v23_nav_weighted_style_gate"],
    )

    row = out.iloc[0]
    assert row["profile"] == "quality_regime_candidate_v23_nav_weighted_style_gate"
    assert int(row["score_alpha_evidence_available"]) == 1
    assert int(row["score_alpha_gate_pass"]) == 0
    assert row["score_alpha_gate_reasons"] == "no_gate_score_passed"
    assert float(row["score_alpha_target_weight_top_minus_all_pct"]) == -1.2


def test_promotion_hard_gate_rejects_failed_score_alpha_gate():
    candidate_name = "quality_regime_candidate_v23_nav_weighted_style_gate"
    out = review._build_promotion_review(
        _minimal_research_for_gate(candidate_name),
        _minimal_p2_for_gate(
            candidate_name,
            score_alpha_evidence_available=1,
            score_alpha_gate_pass=0,
            score_alpha_gate_reasons="no_gate_score_passed",
            score_alpha_top_score_col="target_weight",
            score_alpha_top_minus_all_pct=-1.2,
            score_alpha_rank_ic_mean=-0.1,
        ),
        main_profile="quality_regime",
    )
    candidate = out[out["profile"] == candidate_name].iloc[0]
    assert int(candidate["promotion_hard_gate_pass"]) == 0
    assert "score_alpha_gate_failed" in candidate["promotion_hard_gate_reasons"]

    decision = review._build_promotion_decision(
        out,
        main_profile="quality_regime",
        min_promote_margin=1.0,
        review_id="score-alpha-gate",
        min_p2_executed_days=20,
        review_csv="review.csv",
        review_meta_json="review.json",
    )
    assert decision["decision"] == "keep"
    assert decision["reason_code"] == "candidate_hard_gate_failed"
    assert decision["evidence"]["winner_score_alpha_evidence_available"] is True
    assert decision["evidence"]["winner_score_alpha_gate_pass"] is False
