# -*- coding: utf-8 -*-
"""回测-执行一致性报告计算测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import scripts.quant_exec_consistency_report as qec


def test_build_consistency_computes_gap_and_rates():
    expected = pd.DataFrame(
        {
            "trade_date": ["2026-04-09"],
            "expected_trade_count": [1],
            "expected_ret_pct": [1.0],
            "expected_excess_ret_pct": [0.5],
            "expected_exposure_pct": [60.0],
        }
    )
    actual = pd.DataFrame(
        {
            "run_id": ["r1"],
            "trade_date": ["2026-04-09"],
            "nav_pre": [1_000_000.0],
            "nav_post": [1_008_000.0],
            "filled_orders": [8],
            "partial_orders": [1],
            "blocked_orders": [1],
            "rejected_orders": [0],
            "turnover": [500_000.0],
            "risk_input_count": [10],
            "risk_blocked_count": [2],
        }
    )
    out = qec._build_consistency(
        expected,
        actual,
        fee_bps=8.0,
        slippage_bps=5.0,
        stamp_tax_bps=10.0,
        broker="paper",
    )
    assert len(out) == 1
    row = out.iloc[0]
    assert abs(float(row["actual_ret_pct"]) - 0.8) < 1e-9
    assert abs(float(row["ret_gap_pct"]) - (-0.2)) < 1e-9
    assert float(row["order_fill_rate_pct"]) == 90.0
    assert float(row["order_block_rate_pct"]) == 10.0
    assert float(row["risk_block_rate_pct"]) == 20.0
    assert "primary_gap_driver" in out.columns
    assert "primary_gap_driver_detail" in out.columns


def test_build_summary_handles_matched_rows():
    df = pd.DataFrame(
        {
            "matched_backtest": [1, 1],
            "expected_ret_pct": [1.0, -0.5],
            "actual_ret_pct": [0.8, -0.4],
            "ret_gap_pct": [-0.2, 0.1],
            "order_fill_rate_pct": [90.0, 95.0],
            "order_block_rate_pct": [10.0, 5.0],
            "risk_block_rate_pct": [20.0, 10.0],
            "est_cost_pct": [0.03, 0.02],
            "unexplained_gap_pct": [-0.05, 0.04],
        }
    )
    summary = qec._build_summary(
        df,
        "paper",
        Path("t.csv"),
        Path("l.csv"),
        max_ret_gap_mae_pct=2.0,
        min_match_coverage_pct=60.0,
        max_order_block_rate_pct=35.0,
        max_risk_block_rate_pct=35.0,
        min_matched_rows=1,
    )
    assert summary["matched_rows"] == 2
    assert "ret_gap_mean_pct" in summary
    assert "consistency_pass" in summary
    assert "checks" in summary


def test_dedupe_actual_by_trade_date_keeps_latest_run():
    df = pd.DataFrame(
        {
            "run_id": ["r1", "r2", "r3"],
            "trade_date": ["2026-04-09", "2026-04-09", "2026-04-10"],
            "nav_pre": [100.0, 100.0, 100.0],
            "nav_post": [101.0, 99.0, 100.5],
        }
    )
    out = qec._dedupe_actual_by_trade_date(df)
    assert len(out) == 2
    day_0409 = out[out["trade_date"] == "2026-04-09"]
    assert len(day_0409) == 1
    assert str(day_0409.iloc[0]["run_id"]) == "r2"


def test_resolve_latest_trades_file_auto_select_prefers_higher_overlap(monkeypatch, tmp_path):
    f1 = tmp_path / "quant_trades_20260101_000001.csv"
    f2 = tmp_path / "quant_trades_20260102_000001.csv"
    f1.write_text("x", encoding="utf-8")
    f2.write_text("x", encoding="utf-8")
    ledger = tmp_path / "paper_ledger.csv"
    ledger.write_text("trade_date\n2026-04-01\n", encoding="utf-8")

    monkeypatch.setattr(qec, "get_output_dirs", lambda _out: {"backtest": tmp_path, "base": tmp_path})
    monkeypatch.setattr(qec, "list_dual", lambda _pats, _b, _a: [f1, f2])
    monkeypatch.setattr(qec, "_load_ledger_trade_dates", lambda _lf: {"2026-04-01", "2026-04-02"})

    def _fake_score(fp, _ledger_dates):
        if fp == f1:
            return {
                "intersect_count": 1.0,
                "ledger_coverage_pct": 50.0,
                "expected_rows": 10.0,
                "expected_date_count": 10.0,
            }
        return {
            "intersect_count": 2.0,
            "ledger_coverage_pct": 100.0,
            "expected_rows": 8.0,
            "expected_date_count": 8.0,
        }

    monkeypatch.setattr(qec, "_score_trades_overlap", _fake_score)

    picked, meta = qec._resolve_latest_trades_file(
        explicit=None,
        ledger_file=ledger,
        auto_select=True,
    )
    assert picked == f2
    assert meta["mode"] == "auto_select"
    assert int(meta["intersect_count"]) == 2


def test_resolve_latest_trades_file_auto_select_no_overlap_falls_back_latest(monkeypatch, tmp_path):
    f1 = tmp_path / "quant_trades_20260101_000001.csv"
    f2 = tmp_path / "quant_trades_20260102_000001.csv"
    f1.write_text("x", encoding="utf-8")
    f2.write_text("x", encoding="utf-8")
    ledger = tmp_path / "paper_ledger.csv"
    ledger.write_text("trade_date\n2026-04-01\n", encoding="utf-8")

    monkeypatch.setattr(qec, "get_output_dirs", lambda _out: {"backtest": tmp_path, "base": tmp_path})
    monkeypatch.setattr(qec, "list_dual", lambda _pats, _b, _a: [f1, f2])
    monkeypatch.setattr(qec, "_load_ledger_trade_dates", lambda _lf: {"2026-04-01"})
    monkeypatch.setattr(
        qec,
        "_score_trades_overlap",
        lambda _fp, _ledger_dates: {
            "intersect_count": 0.0,
            "ledger_coverage_pct": 0.0,
            "expected_rows": 99.0,
            "expected_date_count": 99.0,
        },
    )

    picked, meta = qec._resolve_latest_trades_file(
        explicit=None,
        ledger_file=ledger,
        auto_select=True,
    )
    assert picked == f2
    assert meta["mode"] == "auto_select_no_overlap"
    assert int(meta["intersect_count"]) == 0


def test_load_expected_supports_legacy_trades_without_excess_ret(tmp_path):
    trades_file = tmp_path / "quant_trades_legacy.csv"
    trades_file.write_text(
        "signal_date,entry_date,exit_date,portfolio_ret,total_exposure\n"
        "2026-03-01,2026-03-02,2026-03-03,0.01,0.6\n"
        "2026-03-02,2026-03-03,2026-03-04,-0.02,0.5\n",
        encoding="utf-8",
    )
    out = qec._load_expected(trades_file)
    assert len(out) == 2
    assert "expected_ret_pct" in out.columns
    assert "expected_excess_ret_pct" in out.columns
    assert out["expected_excess_ret_pct"].isna().all()


def test_build_style_gap_attribution_returns_layers():
    df = pd.DataFrame(
        {
            "matched_backtest": [1, 1, 1, 0],
            "expected_ret_pct": [1.0, 0.8, -0.3, 0.0],
            "actual_ret_pct": [0.7, 0.6, -0.1, 0.0],
            "ret_gap_pct": [-0.3, -0.2, 0.2, 0.0],
            "order_block_rate_pct": [10.0, 20.0, 5.0, 0.0],
            "risk_block_rate_pct": [15.0, 25.0, 6.0, 0.0],
            "risk_input_count": [10, 10, 8, 7],
            "risk_style_limits_hit": [0, 1, 3, 2],
            "risk_style_size_limits_hit": [0, 1, 2, 1],
            "risk_style_beta_limits_hit": [0, 0, 0, 1],
            "risk_style_momentum_limits_hit": [0, 0, 1, 0],
            "risk_style_vol_limits_hit": [0, 0, 0, 0],
        }
    )
    out = qec._build_style_gap_attribution(df)
    assert not out.empty
    assert set(out["layer_type"].astype(str)) >= {"style_hit_bucket", "style_driver"}
    assert "ret_gap_mae_pct" in out.columns


def test_build_tick_replay_outputs_detail_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(qec, "OUTPUT_DIR", tmp_path)
    (tmp_path / "execution").mkdir(parents=True, exist_ok=True)

    trades = tmp_path / "quant_trades.csv"
    trades.write_text(
        "entry_date,codes,weights,portfolio_ret\n"
        "2026-04-10,000001,1.0,0.01\n",
        encoding="utf-8",
    )

    orders = pd.DataFrame(
        {
            "run_id": ["r1", "r1"],
            "signal_date": ["2026-04-09", "2026-04-09"],
            "trade_date": ["2026-04-10", "2026-04-10"],
            "code": ["000001", "000002"],
            "side": ["BUY", "BUY"],
            "rank": [1, 2],
            "requested_qty": [1000, 1000],
            "filled_qty": [1000, 0],
            "status": ["filled", "blocked"],
            "reason": ["ok", "entry_not_tradable"],
        }
    )
    orders.to_csv(tmp_path / "execution" / "paper_orders_20260410_r1.csv", index=False, encoding="utf-8-sig")

    report = pd.DataFrame(
        {
            "run_id": ["r1"],
            "trade_date": ["2026-04-10"],
            "matched_backtest": [1],
            "expected_ret_pct": [1.0],
            "actual_ret_pct": [0.7],
            "ret_gap_pct": [-0.3],
            "risk_style_limits_hit": [1],
            "risk_block_rate_pct": [20.0],
            "order_block_rate_pct": [10.0],
        }
    )

    detail, layer, summary = qec._build_tick_replay(report_df=report, trades_file=trades, broker="paper")
    assert len(detail) == 2
    assert int(detail["expected_in_backtest"].sum()) == 1
    assert not layer.empty
    assert int(summary["rows"]) == 2
