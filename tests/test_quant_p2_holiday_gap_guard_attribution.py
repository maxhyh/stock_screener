# -*- coding: utf-8 -*-
"""Holiday-gap guard attribution tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import scripts.quant_p2_holiday_gap_guard_attribution as diag


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def test_build_holiday_gap_attribution_labels_cash_drag_plus_sell_trap(tmp_path: Path, monkeypatch):
    exec_dir = tmp_path / "execution"
    exec_dir.mkdir()
    monkeypatch.setattr(diag, "EXEC_DIR", exec_dir)

    _write(
        exec_dir / "main_ledger.csv",
        [
            {
                "run_id": "m1",
                "signal_date": "2026-01-19",
                "trade_date": "2026-02-06",
                "nav_pre": 100.0,
                "nav_post": 101.0,
                "target_weight_sum": 0.48,
                "holiday_gap_guard": 0,
                "broker_exit_not_tradable_orders": 0,
                "blocked_sell_current_weight": 0.0,
            },
            {
                "run_id": "m2",
                "signal_date": "2026-01-20",
                "trade_date": "2026-02-09",
                "nav_pre": 101.0,
                "nav_post": 102.0,
                "target_weight_sum": 0.48,
                "holiday_gap_guard": 0,
                "broker_exit_not_tradable_orders": 0,
            },
        ],
    )
    _write(
        exec_dir / "candidate_ledger.csv",
        [
            {
                "run_id": "c1",
                "signal_date": "2026-01-19",
                "trade_date": "2026-02-06",
                "nav_pre": 100.0,
                "nav_post": 99.0,
                "target_weight_sum": 0.12,
                "holiday_gap_guard": 1,
                "holiday_gap_reason": "signal_to_trade_gap+post_trade_gap",
                "holiday_gap_target_scale": 0.3,
                "holiday_gap_signal_trade_gap_days": 7,
                "holiday_gap_post_trade_gap_days": 4,
                "broker_exit_not_tradable_orders": 1,
                "blocked_sell_current_weight": 0.02,
            },
            {
                "run_id": "c2",
                "signal_date": "2026-01-20",
                "trade_date": "2026-02-09",
                "nav_pre": 99.0,
                "nav_post": 100.0,
                "target_weight_sum": 0.45,
                "holiday_gap_guard": 0,
                "broker_exit_not_tradable_orders": 0,
            },
        ],
    )
    _write(
        exec_dir / "candidate_orders_20260206_c1.csv",
        [
            {
                "code": "600415",
                "side": "SELL",
                "status": "blocked",
                "reason": "exit_not_tradable",
                "blocked_current_weight": 0.02,
                "blocked_notional": 2000.0,
            }
        ],
    )
    _write(
        exec_dir / "candidate_risk_gates_20260206_c1.csv",
        [{"code": "603601", "target_weight": 0.008, "reasons": "entry_not_tradable"}],
    )
    summary = pd.DataFrame(
        [
            {"profile": "main", "window": 60, "channel": "main", "nav_return_pct": 2.0, "max_drawdown_pct": -1.0},
            {
                "profile": "candidate",
                "window": 60,
                "channel": "candidate",
                "nav_return_pct": 0.0,
                "max_drawdown_pct": -2.0,
            },
        ]
    )

    detail, reason, window = diag.build_holiday_gap_attribution(
        summary,
        main_profile="main",
        candidate_profiles=["candidate"],
        windows=[60],
    )

    assert len(detail) == 2
    guard_row = detail[detail["candidate_holiday_gap_guard"].eq(1)].iloc[0]
    assert guard_row["day_guard_label"] == "holiday_gap_cash_drag+sell_trap"
    assert round(float(guard_row["cash_drag_proxy_pct"]), 4) == 0.36
    assert guard_row["candidate_blocked_sell_orders"] == 1
    assert guard_row["candidate_risk_entry_not_tradable_rows"] == 1
    assert not reason.empty
    assert reason[reason["candidate_holiday_gap_reason"].eq("signal_to_trade_gap+post_trade_gap")].iloc[0][
        "guard_reason_verdict"
    ] == "insufficient_sample"
    assert int(window.iloc[0]["guard_days"]) == 1


def test_reason_summary_classifies_false_positive_and_effective_protection():
    rows: list[dict[str, object]] = []
    for i in range(3):
        rows.append(
            {
                "candidate_profile": "false_positive",
                "main_profile": "main",
                "window": 60,
                "candidate_holiday_gap_reason": "signal_to_trade_gap",
                "candidate_holiday_gap_guard": 1,
                "relative_return_gap_pct": -0.4,
                "candidate_daily_return_pct": -0.2,
                "target_weight_gap": -0.10,
                "cash_drag_proxy_pct": 0.15,
                "candidate_broker_exit_not_tradable_orders": 1,
                "main_broker_exit_not_tradable_orders": 0,
                "exit_block_delta": 1,
                "candidate_blocked_sell_current_weight": 0.02,
            }
        )
        rows.append(
            {
                "candidate_profile": "false_positive",
                "main_profile": "main",
                "window": 60,
                "candidate_holiday_gap_reason": "no_guard",
                "candidate_holiday_gap_guard": 0,
                "relative_return_gap_pct": 0.1,
                "candidate_daily_return_pct": -0.5,
                "target_weight_gap": 0.0,
                "cash_drag_proxy_pct": 0.0,
                "candidate_broker_exit_not_tradable_orders": 0,
                "main_broker_exit_not_tradable_orders": 0,
                "exit_block_delta": 0,
                "candidate_blocked_sell_current_weight": 0.0,
            }
        )
        rows.append(
            {
                "candidate_profile": "effective",
                "main_profile": "main",
                "window": 60,
                "candidate_holiday_gap_reason": "post_trade_gap",
                "candidate_holiday_gap_guard": 1,
                "relative_return_gap_pct": 0.2,
                "candidate_daily_return_pct": -0.1,
                "target_weight_gap": -0.03,
                "cash_drag_proxy_pct": 0.0,
                "candidate_broker_exit_not_tradable_orders": 0,
                "main_broker_exit_not_tradable_orders": 0,
                "exit_block_delta": 0,
                "candidate_blocked_sell_current_weight": 0.0,
            }
        )
        rows.append(
            {
                "candidate_profile": "effective",
                "main_profile": "main",
                "window": 60,
                "candidate_holiday_gap_reason": "no_guard",
                "candidate_holiday_gap_guard": 0,
                "relative_return_gap_pct": -0.1,
                "candidate_daily_return_pct": -1.0,
                "target_weight_gap": 0.0,
                "cash_drag_proxy_pct": 0.0,
                "candidate_broker_exit_not_tradable_orders": 1,
                "main_broker_exit_not_tradable_orders": 0,
                "exit_block_delta": 1,
                "candidate_blocked_sell_current_weight": 0.01,
            }
        )
    detail = pd.DataFrame(rows)

    summary = diag.build_reason_summary(detail, min_sample_days=3, cash_drag_threshold=0.05)
    verdicts = {
        (str(r["candidate_profile"]), str(r["candidate_holiday_gap_reason"])): str(r["guard_reason_verdict"])
        for _, r in summary.iterrows()
    }

    assert verdicts[("false_positive", "signal_to_trade_gap")] == "false_positive_cash_drag"
    assert verdicts[("effective", "post_trade_gap")] == "effective_protection"
    assert verdicts[("effective", "no_guard")] == "baseline_no_guard"


def test_missing_artifacts_are_marked_without_breaking(tmp_path: Path, monkeypatch):
    exec_dir = tmp_path / "execution"
    exec_dir.mkdir()
    monkeypatch.setattr(diag, "EXEC_DIR", exec_dir)
    _write(
        exec_dir / "main_ledger.csv",
        [{"run_id": "m1", "signal_date": "2026-01-19", "trade_date": "2026-01-20", "nav_pre": 100, "nav_post": 100}],
    )
    _write(
        exec_dir / "candidate_ledger.csv",
        [
            {
                "run_id": "c1",
                "signal_date": "2026-01-19",
                "trade_date": "2026-01-20",
                "nav_pre": 100,
                "nav_post": 100,
                "holiday_gap_guard": 1,
                "holiday_gap_reason": "post_trade_gap",
            }
        ],
    )
    summary = pd.DataFrame(
        [
            {"profile": "main", "window": 60, "channel": "main"},
            {"profile": "candidate", "window": 60, "channel": "candidate"},
        ]
    )

    detail = diag.build_day_detail(
        summary,
        main_profile="main",
        candidate_profiles=["candidate"],
        windows=[60],
    )

    assert len(detail) == 1
    assert bool(detail.iloc[0]["candidate_orders_artifact_missing"])
    assert bool(detail.iloc[0]["candidate_risk_artifact_missing"])
