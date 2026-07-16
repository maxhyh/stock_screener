from __future__ import annotations

import pandas as pd

from scripts.quant_capacity_feasible_alpha_diagnosis import (
    build_capacity_feasible_summary,
    evaluate_capacity_feasible_row,
)


def _profile_cfg(**overrides):
    cfg = {
        "top_n": 1,
        "fallback_total_position": 0.40,
        "max_single_pos": 0.40,
        "optimizer_mode": "capacity_crowding_aware",
        "target_max_adv_participation": 0.02,
        "target_max_industry_weight": 1.0,
        "target_capacity_amount_col": "amount_ma20",
        "target_capacity_amount_buffer": 1.0,
        "target_capital_base": 1_000_000.0,
        "redistribute_clipped_weight": False,
        "min_valid_positions": 0,
    }
    cfg.update(overrides)
    return cfg


def test_capacity_feasible_gate_flags_positive_alpha_but_capacity_failure():
    rows = []
    for day in pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]):
        rows.extend(
            [
                {
                    "signal_date": day,
                    "ts_code": f"{day.day:06d}",
                    "industry": "Tech",
                    "score": 3.0,
                    "forward_return": 0.05,
                    "amount_ma20": 0.0,
                },
                {
                    "signal_date": day,
                    "ts_code": f"{day.day + 10:06d}",
                    "industry": "Bank",
                    "score": 1.0,
                    "forward_return": -0.02,
                    "amount_ma20": 100_000_000.0,
                },
            ]
        )

    summary, daily, gate = build_capacity_feasible_summary(
        pd.DataFrame(rows),
        profile_cfg=_profile_cfg(),
        score_cols=["score"],
        min_days=3,
        max_capacity_shortfall_weight=0.10,
    )

    assert gate["pass"] is False
    row = summary.iloc[0]
    assert row["verdict"] == "alpha_positive_but_capacity_failed"
    assert row["target_weight_sum_mean"] == 0.0
    assert row["zero_target_rate_pct"] == 100.0
    assert "target_weight_sum_mean_too_low" in row["reasons"]
    assert int(daily["invalid_amount_rows"].sum()) == 3


def test_capacity_feasible_gate_flags_capacity_ok_alpha_failure():
    rows = []
    for day in pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]):
        rows.extend(
            [
                {
                    "signal_date": day,
                    "ts_code": f"{day.day:06d}",
                    "industry": "Tech",
                    "score": 3.0,
                    "forward_return": -0.04,
                    "amount_ma20": 100_000_000.0,
                },
                {
                    "signal_date": day,
                    "ts_code": f"{day.day + 10:06d}",
                    "industry": "Bank",
                    "score": 1.0,
                    "forward_return": 0.01,
                    "amount_ma20": 100_000_000.0,
                },
            ]
        )

    summary, _, gate = build_capacity_feasible_summary(
        pd.DataFrame(rows),
        profile_cfg=_profile_cfg(),
        score_cols=["score"],
        min_days=3,
    )

    assert gate["pass"] is False
    row = summary.iloc[0]
    assert row["verdict"] == "capacity_ok_alpha_failed"
    assert row["target_weight_sum_mean"] >= 0.30
    assert "selected_forward_return_not_positive" in row["reasons"]


def test_capacity_feasible_gate_passes_only_when_alpha_and_capacity_pass():
    rows = []
    for day in pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]):
        rows.extend(
            [
                {
                    "signal_date": day,
                    "ts_code": f"{day.day:06d}",
                    "industry": "Tech",
                    "score": 3.0,
                    "forward_return": 0.04,
                    "amount_ma20": 100_000_000.0,
                },
                {
                    "signal_date": day,
                    "ts_code": f"{day.day + 10:06d}",
                    "industry": "Bank",
                    "score": 1.0,
                    "forward_return": -0.02,
                    "amount_ma20": 100_000_000.0,
                },
            ]
        )

    summary, _, gate = build_capacity_feasible_summary(
        pd.DataFrame(rows),
        profile_cfg=_profile_cfg(),
        score_cols=["score"],
        min_days=3,
    )

    row = summary.iloc[0]
    assert gate["pass"] is True
    assert bool(row["gate_pass"]) is True
    assert row["verdict"] == "capacity_feasible_alpha_pass"


def test_capacity_feasible_gate_rejects_insufficient_sample():
    row = {
        "days": 2,
        "target_weight_sum_mean": 0.40,
        "zero_target_rate_pct": 0.0,
        "capacity_shortfall_weight_mean": 0.0,
        "selected_weighted_forward_return_pct": 2.0,
        "selected_minus_pool_pct": 1.0,
        "rank_ic_mean": 0.10,
    }

    out = evaluate_capacity_feasible_row(row, min_days=3)

    assert out["gate_pass"] is False
    assert out["verdict"] == "insufficient_sample"


def test_capacity_diagnosis_builds_profile_target_blend_score():
    rows = []
    for day in pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]):
        rows.extend(
            [
                {
                    "signal_date": day,
                    "ts_code": f"{day.day:06d}",
                    "industry": "Tech",
                    "liquidity_score": 1.0,
                    "exit_trap_safe_score": 1.0,
                    "forward_return": 0.04,
                    "amount_ma20": 100_000_000.0,
                },
                {
                    "signal_date": day,
                    "ts_code": f"{day.day + 10:06d}",
                    "industry": "Bank",
                    "liquidity_score": 0.0,
                    "exit_trap_safe_score": 0.0,
                    "forward_return": -0.02,
                    "amount_ma20": 100_000_000.0,
                },
            ]
        )

    summary, _, gate = build_capacity_feasible_summary(
        pd.DataFrame(rows),
        profile_cfg=_profile_cfg(target_score_blend={"liquidity_score": 0.55, "exit_trap_safe_score": 0.45}),
        score_cols=["target_blend_score"],
        min_days=3,
    )

    assert summary.iloc[0]["score_col"] == "target_blend_score"
    assert bool(summary.iloc[0]["gate_pass"]) is True
    assert gate["passing_score_cols"] == ["target_blend_score"]


def test_capacity_diagnosis_attributes_top_replacement_loss():
    rows = []
    for day in pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]):
        rows.extend(
            [
                {
                    "signal_date": day,
                    "ts_code": f"{day.day:06d}",
                    "industry": "Tech",
                    "score": 3.0,
                    "forward_return": 0.05,
                    "amount_ma20": 0.0,
                },
                {
                    "signal_date": day,
                    "ts_code": f"{day.day + 10:06d}",
                    "industry": "Bank",
                    "score": 1.0,
                    "forward_return": -0.03,
                    "amount_ma20": 100_000_000.0,
                },
            ]
        )

    summary, daily, _ = build_capacity_feasible_summary(
        pd.DataFrame(rows),
        profile_cfg=_profile_cfg(redistribute_clipped_weight=True),
        score_cols=["score"],
        min_days=3,
    )

    day = daily.iloc[0]
    assert day["top_dropped_rows"] == 1
    assert day["selected_replacement_rows"] == 1
    assert day["selection_loss_pct"] < 0
    assert day["top_dropped_invalid_amount_rows"] == 1
    assert day["selection_loss_label"] == "invalid_amount_capacity_loss"

    row = summary.iloc[0]
    assert row["selection_loss_pct"] < 0
    assert row["top_selected_overlap_rate_pct"] == 0.0
    assert row["selection_loss_label"] == "invalid_amount_capacity_loss"


def test_capacity_diagnosis_primary_promotion_mode_exposes_reserve_trapped_alpha():
    rows = []
    for day in pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]):
        rows.extend(
            [
                {
                    "signal_date": day,
                    "ts_code": f"{day.day:06d}",
                    "industry": "Tech",
                    "score": 3.0,
                    "forward_return": 0.05,
                    "amount_ma20": 100_000_000.0,
                    "reserve_candidate": 1,
                },
                {
                    "signal_date": day,
                    "ts_code": f"{day.day + 10:06d}",
                    "industry": "Bank",
                    "score": 1.0,
                    "forward_return": -0.03,
                    "amount_ma20": 100_000_000.0,
                    "reserve_candidate": 0,
                },
            ]
        )

    summary, daily, gate = build_capacity_feasible_summary(
        pd.DataFrame(rows),
        profile_cfg=_profile_cfg(redistribute_clipped_weight=True, target_max_reserve_weight=0.02),
        score_cols=["score"],
        min_days=3,
        primary_promotion_modes=["keep", "score_topn"],
    )

    by_mode = {str(row["primary_promotion_mode"]): row for row in summary.to_dict(orient="records")}
    assert set(by_mode) == {"keep", "score_topn"}
    assert by_mode["keep"]["verdict"] == "capacity_ok_alpha_failed"
    assert by_mode["keep"]["selected_weighted_forward_return_pct"] < 0.0
    assert by_mode["keep"]["selected_replacement_rows"] == 3
    assert by_mode["score_topn"]["verdict"] == "capacity_feasible_alpha_pass"
    assert by_mode["score_topn"]["selected_weighted_forward_return_pct"] > 0.0
    assert gate["pass"] is True
    assert gate["passing_score_modes"] == ["score:score_topn"]

    keep_daily = daily[daily["primary_promotion_mode"].eq("keep")]
    promoted_daily = daily[daily["primary_promotion_mode"].eq("score_topn")]
    assert keep_daily["selected_replacement_rows"].sum() == 3
    assert promoted_daily["selected_replacement_rows"].sum() == 0
