import pandas as pd
import pytest

from scripts.quant_stage_transition_diagnosis import (
    build_alpha_decay_summary,
    build_score_stage_summary,
    build_stage_summary,
    build_transition_diagnosis,
)


def test_transition_diagnosis_reports_dropped_alpha():
    df = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-01-01"] * 5),
            "code": ["A", "B", "C", "A", "B"],
            "research_stage": ["raw", "raw", "raw", "filtered", "filtered"],
            "forward_return": [0.10, 0.02, -0.05, 0.10, 0.02],
            "industry": ["Tech", "Bank", "Tech", "Tech", "Bank"],
            "hard_limit_flag": [0, 0, 1, 0, 0],
        }
    )

    summary, daily = build_transition_diagnosis(df, stage_order=["raw", "filtered"])

    row = summary.iloc[0]
    assert int(row["kept_rows"]) == 2
    assert int(row["dropped_rows"]) == 1
    assert row["dropped_mean_forward_return_pct"] < row["kept_mean_forward_return_pct"]
    assert row["dropped_top_filter_flag"] == "hard_limit_flag"
    assert daily.iloc[0]["from_stage"] == "raw"


def test_stage_summary_tracks_top_industry_and_stage_rank_top_return():
    df = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-01-01"] * 3),
            "code": ["A", "B", "C"],
            "research_stage": ["raw", "raw", "raw"],
            "stage_rank": [1, 2, 3],
            "forward_return": [0.10, -0.02, -0.03],
            "industry": ["Tech", "Tech", "Bank"],
        }
    )

    summary = build_stage_summary(df, top_n=1, stage_order=["raw"])
    row = summary.iloc[0]

    assert row["top_industry_label"] == "Tech"
    assert row["top_industry_count_weight_pct"] == pytest.approx(100.0 * 2 / 3)
    assert row["stage_rank_top_mean_forward_return_pct"] == 10.0


def test_score_stage_summary_reports_rank_ic_and_spread():
    df = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-01-01"] * 4 + ["2026-01-02"] * 4),
            "code": ["A", "B", "C", "D", "A", "B", "C", "D"],
            "research_stage": ["raw"] * 8,
            "alpha_score": [4, 3, 2, 1, 4, 3, 2, 1],
            "forward_return": [0.08, 0.04, -0.01, -0.03, 0.06, 0.02, -0.02, -0.05],
            "industry": ["Tech", "Bank", "Bank", "Tech", "Tech", "Bank", "Bank", "Tech"],
        }
    )

    out = build_score_stage_summary(df, score_cols=["alpha_score"], top_n=1, stage_order=["raw"])
    row = out.iloc[0]

    assert row["score_col"] == "alpha_score"
    assert row["top_mean_forward_return_pct"] == pytest.approx(7.0)
    assert row["bottom_mean_forward_return_pct"] == pytest.approx(-4.0)
    assert row["top_minus_bottom_pct"] == pytest.approx(11.0)
    assert row["rank_ic_mean"] == pytest.approx(1.0)


def test_alpha_decay_summary_flags_damaging_transition_and_gate_failure():
    transition = pd.DataFrame(
        {
            "from_stage": ["filtered_signal_pool"],
            "to_stage": ["ranking_pool_pre_pretrade"],
            "from_mean_forward_return_pct": [0.50],
            "to_mean_forward_return_pct": [-0.20],
            "dropped_mean_forward_return_pct": [0.80],
            "kept_mean_forward_return_pct": [-0.20],
            "dropped_minus_kept_pct": [1.00],
            "keep_rate_pct": [33.0],
            "dropped_rows": [20],
        }
    )
    score = pd.DataFrame(
        {
            "research_stage": ["final_target_weight", "final_target_weight", "final_target_weight"],
            "score_col": ["target_weight", "portfolio_rank_score", "liquidity_score"],
            "all_mean_forward_return_pct": [-0.30, -0.30, -0.30],
            "top_mean_forward_return_pct": [-0.10, -0.40, 1.20],
            "top_minus_all_pct": [0.20, -0.10, 1.50],
            "top_minus_bottom_pct": [0.10, 0.20, 1.70],
            "rank_ic_mean": [0.01, -0.02, 0.03],
        }
    )

    out = build_alpha_decay_summary(pd.DataFrame(), transition, score)

    assert out.iloc[0]["verdict"] == "ranking_alpha_decay_before_p2"
    assert "filtered_signal_pool" in set(out["from_stage"])
    gate = out[out["score_col"].eq("portfolio_rank_score")].iloc[0]
    assert gate["verdict"] == "gate_score_failed"
    assert "rank_ic_not_positive" in gate["reason"]
    component = out[out["summary_type"].eq("component_score_survives")].iloc[0]
    assert component["score_col"] == "liquidity_score"
    assert component["verdict"] == "hypothesis_only_not_profile_gate"


def test_alpha_decay_summary_marks_gate_score_pass_as_p2_candidate():
    score = pd.DataFrame(
        {
            "research_stage": ["final_target_weight"],
            "score_col": ["target_weight"],
            "all_mean_forward_return_pct": [0.10],
            "top_mean_forward_return_pct": [0.80],
            "top_minus_all_pct": [0.70],
            "top_minus_bottom_pct": [1.00],
            "rank_ic_mean": [0.05],
        }
    )

    out = build_alpha_decay_summary(pd.DataFrame(), pd.DataFrame(), score)

    assert out.iloc[0]["verdict"] == "profile_gate_scores_need_p2_smoke"
    assert out[out["score_col"].eq("target_weight")].iloc[0]["verdict"] == "gate_score_passed"
