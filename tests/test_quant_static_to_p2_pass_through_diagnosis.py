# -*- coding: utf-8 -*-
"""Static capacity alpha to P2 pass-through diagnosis tests."""

from __future__ import annotations

import pandas as pd

import scripts.quant_static_to_p2_pass_through_diagnosis as diag


def _dates(n: int) -> list[str]:
    return pd.date_range("2026-01-01", periods=n, freq="D").strftime("%Y-%m-%d").tolist()


def _capacity_rows(n: int, *, score_col: str = "rank", selected: float = 0.8, spread: float = 0.4) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signal_date": _dates(n),
            "score_col": [score_col] * n,
            "primary_promotion_mode": ["keep"] * n,
            "selected_weighted_forward_return_pct": [selected] * n,
            "selected_minus_pool_pct": [spread] * n,
            "pool_mean_forward_return_pct": [selected - spread] * n,
            "target_weight_sum": [0.36] * n,
            "selection_loss_label": ["none"] * n,
        }
    )


def _p2_rows(n: int, *, relative_gap: float = -0.10, target_gap: float = -0.10) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for i, d in enumerate(_dates(n)):
        holiday = i < 12
        rows.append(
            {
                "signal_date": d,
                "main_profile": "main",
                "candidate_profile": "candidate",
                "window": 60,
                "main_daily_return_pct": 0.40,
                "candidate_daily_return_pct": 0.40 + relative_gap,
                "relative_return_gap_pct": relative_gap,
                "main_target_weight_sum": 0.50,
                "candidate_target_weight_sum": 0.50 + target_gap,
                "target_weight_gap": target_gap,
                "cash_drag_proxy_pct": max(0.0, -target_gap) * 0.40,
                "candidate_holiday_gap_guard": 1 if holiday else 0,
                "candidate_holiday_gap_reason": "signal_to_trade_gap" if holiday else "",
                "candidate_holiday_gap_target_scale": 0.5 if holiday else 1.0,
                "main_broker_entry_blocks": 0,
                "candidate_broker_entry_blocks": 0,
                "main_broker_exit_blocks": 0,
                "candidate_broker_exit_blocks": 0,
                "exit_block_delta": 0,
                "main_blocked_sell_current_weight": 0.0,
                "candidate_blocked_sell_current_weight": 0.0,
                "blocked_sell_weight_gap": 0.0,
            }
        )
    return pd.DataFrame(rows)


def test_build_pass_through_report_labels_holiday_cash_drag_dominance():
    summary, detail, reason = diag.build_pass_through_report(
        capacity_daily=_capacity_rows(20),
        p2_detail=_p2_rows(20),
        profile="candidate",
        main_profile="main",
        window=60,
        score_col="rank",
    )

    row = summary.iloc[0]
    assert row["aligned_days"] == 20
    assert row["static_positive_days"] == 20
    assert row["static_positive_p2_underperform_days"] == 20
    assert row["verdict"] == "holiday_cash_drag_dominant"
    assert detail["pass_through_label"].str.contains("holiday_cash_drag").sum() == 12
    assert reason.iloc[0]["pass_through_label"] == "static_positive_lost_to_holiday_cash_drag"


def test_build_pass_through_report_flags_static_alpha_not_positive():
    summary, detail, reason = diag.build_pass_through_report(
        capacity_daily=_capacity_rows(20, selected=-0.2, spread=-0.1),
        p2_detail=_p2_rows(20, relative_gap=0.05, target_gap=0.0),
        profile="candidate",
        main_profile="main",
        window=60,
        score_col="rank",
    )

    assert summary.iloc[0]["verdict"] == "static_alpha_not_positive"
    assert int(summary.iloc[0]["static_positive_days"]) == 0
    assert not detail.empty
    assert not reason.empty


def test_build_pass_through_report_requires_enough_aligned_days():
    summary, detail, reason = diag.build_pass_through_report(
        capacity_daily=_capacity_rows(2),
        p2_detail=_p2_rows(2),
        profile="candidate",
        main_profile="main",
        window=60,
        score_col="rank",
    )

    assert summary.iloc[0]["verdict"] == "insufficient_sample"
    assert len(detail) == 2
    assert not reason.empty
