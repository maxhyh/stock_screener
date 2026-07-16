# -*- coding: utf-8 -*-
"""Raw alpha to P2 residual diagnosis tests."""

from __future__ import annotations

import pandas as pd

import scripts.quant_raw_alpha_p2_residual_diagnosis as diag


def test_score_pass_requires_positive_top_spread_and_ic():
    assert diag._score_pass(
        {
            "top_mean_forward_return_pct": 1.0,
            "top_minus_all_pct": 0.2,
            "top_minus_bottom_pct": 0.5,
            "rank_ic_mean": 0.01,
        }
    )
    assert not diag._score_pass(
        {
            "top_mean_forward_return_pct": 1.0,
            "top_minus_all_pct": 0.2,
            "top_minus_bottom_pct": 0.5,
            "rank_ic_mean": -0.01,
        }
    )


def test_report_marks_final_static_alpha_not_p2_executed_when_raw_is_weak():
    score = pd.DataFrame(
        [
            {
                "research_stage": "raw_scored_post_indicator",
                "score_col": "ml_score",
                "top_mean_forward_return_pct": -1.0,
                "top_minus_all_pct": -1.2,
                "top_minus_bottom_pct": -2.0,
                "rank_ic_mean": -0.03,
            },
            {
                "research_stage": "raw_scored_post_indicator",
                "score_col": "liquidity_score",
                "top_mean_forward_return_pct": 1.0,
                "top_minus_all_pct": 0.2,
                "top_minus_bottom_pct": 0.4,
                "rank_ic_mean": -0.02,
            },
            {
                "research_stage": "final_target_weight",
                "score_col": "target_weight",
                "top_mean_forward_return_pct": 1.2,
                "top_minus_all_pct": 1.4,
                "top_minus_bottom_pct": 0.8,
                "rank_ic_mean": 0.04,
            },
        ]
    )
    transition = pd.DataFrame(
        [
            {
                "from_stage": "filtered_signal_pool",
                "to_stage": "ranking_pool_pre_pretrade",
                "from_mean_forward_return_pct": 0.5,
                "to_mean_forward_return_pct": 0.2,
                "dropped_minus_kept_pct": 0.6,
            }
        ]
    )
    p2 = pd.DataFrame(
        [
            {
                "verdict": "static_alpha_not_p2_passed",
                "aligned_days": 60,
                "relative_return_gap_sum_pct": -4.5,
                "static_positive_days": 24,
                "static_positive_p2_underperform_days": 15,
            }
        ]
    )

    summary, candidates = diag.build_raw_alpha_p2_residual_report(
        score_stage_summary=score,
        transition_summary=transition,
        static_to_p2_summary=p2,
        profile="candidate",
        main_profile="main",
    )

    row = summary.iloc[0]
    assert row["overall_verdict"] == "final_static_alpha_not_p2_executed_raw_alpha_weak"
    assert bool(row["raw_ml_score_pass"]) is False
    assert bool(row["raw_any_score_pass"]) is False
    assert bool(row["final_gate_score_pass"]) is True
    assert bool(row["damaging_transition"]) is True
    assert not candidates.empty


def test_report_stops_when_final_alpha_fails():
    score = pd.DataFrame(
        [
            {
                "research_stage": "raw_scored_post_indicator",
                "score_col": "ml_score",
                "top_mean_forward_return_pct": 1.0,
                "top_minus_all_pct": 0.2,
                "top_minus_bottom_pct": 0.5,
                "rank_ic_mean": 0.03,
            },
            {
                "research_stage": "final_target_weight",
                "score_col": "target_weight",
                "top_mean_forward_return_pct": -0.2,
                "top_minus_all_pct": -0.1,
                "top_minus_bottom_pct": 0.2,
                "rank_ic_mean": -0.01,
            },
        ]
    )

    summary, _ = diag.build_raw_alpha_p2_residual_report(
        score_stage_summary=score,
        transition_summary=pd.DataFrame(),
        static_to_p2_summary=pd.DataFrame(),
        profile="candidate",
        main_profile="main",
    )

    assert summary.iloc[0]["overall_verdict"] == "stop_profile_evolution_final_alpha_failed"
