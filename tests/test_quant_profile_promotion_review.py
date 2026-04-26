# -*- coding: utf-8 -*-
"""Profile 升档评审测试。"""

from __future__ import annotations

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
        "p2_target_weight_sum_mean": 0.36,
        "p2_target_weight_sum_60": 0.30,
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
