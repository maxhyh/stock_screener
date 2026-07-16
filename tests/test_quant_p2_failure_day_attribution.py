# -*- coding: utf-8 -*-
"""P2 failure day attribution tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import scripts.quant_p2_failure_day_attribution as diag


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def test_build_day_attribution_labels_holiday_gap_plus_sell_trap(tmp_path: Path, monkeypatch):
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
                "holiday_gap_target_scale": 1.0,
                "broker_exit_not_tradable_orders": 0,
                "risk_blocked_count": 0,
            }
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
                "broker_exit_not_tradable_orders": 1,
                "blocked_sell_current_weight": 0.01,
                "risk_blocked_count": 1,
            }
        ],
    )
    _write(
        exec_dir / "main_orders_20260206_m1.csv",
        [{"code": "000001", "side": "BUY", "status": "filled", "target_weight": 0.48}],
    )
    _write(
        exec_dir / "candidate_orders_20260206_c1.csv",
        [
            {
                "code": "600415",
                "side": "SELL",
                "status": "blocked",
                "reason": "exit_not_tradable",
                "blocked_current_weight": 0.01,
                "blocked_notional": 1000.0,
                "target_weight": 0.0,
            }
        ],
    )
    _write(
        exec_dir / "candidate_risk_gates_20260206_c1.csv",
        [{"code": "603601", "target_weight": 0.008, "reasons": "entry_not_tradable"}],
    )
    failure = pd.DataFrame(
        [
            {
                "candidate_profile": "candidate",
                "window": 60,
                "signal_date": "2026-01-19",
                "relative_return_gap_pct": -2.0,
            }
        ]
    )
    summary = pd.DataFrame(
        [
            {"profile": "main", "window": 60, "channel": "main"},
            {"profile": "candidate", "window": 60, "channel": "candidate"},
        ]
    )

    out, orders, risks = diag.build_day_attribution(
        failure_detail=failure,
        p2_summary=summary,
        main_profile="main",
        candidate_profiles=["candidate"],
        window=60,
        focus_dates=[],
        worst_n=1,
    )

    assert len(out) == 1
    row = out.iloc[0]
    assert row["day_failure_label"] == "holiday_gap_cash_drag+sell_trap"
    assert row["candidate_blocked_sell_codes"] == "600415"
    assert row["candidate_risk_entry_not_tradable_rows"] == 1
    assert row["target_weight_gap"] == -0.36
    assert set(orders["role"]) == {"main", "candidate"}
    assert risks.iloc[0]["role"] == "candidate"


def test_orders_summary_counts_blocked_sell_weights():
    orders = pd.DataFrame(
        [
            {"code": "A", "side": "SELL", "status": "blocked", "reason": "exit_not_tradable", "blocked_current_weight": 0.02, "blocked_notional": 200.0},
            {"code": "B", "side": "BUY", "status": "blocked", "reason": "entry_not_tradable", "blocked_current_weight": 0.00, "blocked_notional": 0.0},
            {"code": "C", "side": "BUY", "status": "filled", "target_weight": 0.03},
        ]
    )

    out = diag._orders_summary(orders)

    assert out["blocked_orders"] == 2
    assert out["blocked_sell_orders"] == 1
    assert out["blocked_buy_orders"] == 1
    assert out["blocked_sell_current_weight_sum"] == 0.02
    assert out["blocked_sell_codes"] == "A"
