# -*- coding: utf-8 -*-
"""Exposure-adjusted benchmark and excess return tests."""

from __future__ import annotations

import math

import pandas as pd

import scripts.quant_portfolio_backtest as qpb


def test_calc_metrics_uses_exposure_adjusted_benchmark_for_excess():
    trades_df = pd.DataFrame(
        [
            {
                "entry_date": "2026-03-02",
                "exit_date": "2026-03-05",
                "portfolio_ret": 0.03,
                "benchmark_ret_raw": 0.04,
                "benchmark_ret": 0.02,
                "total_exposure": 0.50,
                "equity": 1.03,
            },
            {
                "entry_date": "2026-03-06",
                "exit_date": "2026-03-10",
                "portfolio_ret": -0.01,
                "benchmark_ret_raw": 0.02,
                "benchmark_ret": 0.01,
                "total_exposure": 0.50,
                "equity": 1.0197,
            },
        ]
    )

    metrics = qpb._calc_metrics(trades_df, holding_days=3)

    expected_excess_total = (1.0 + 0.01) * (1.0 - 0.02) - 1.0

    assert math.isclose(metrics["benchmark_total_return_pct"], (1.04 * 1.02 - 1.0) * 100.0, rel_tol=1e-9)
    assert math.isclose(metrics["benchmark_exposure_adj_total_return_pct"], (1.02 * 1.01 - 1.0) * 100.0, rel_tol=1e-9)
    assert math.isclose(metrics["excess_total_return_pct"], expected_excess_total * 100.0, rel_tol=1e-9)
    assert math.isclose(metrics["beat_rate_pct"], 50.0, rel_tol=1e-9)
    assert metrics["profit_factor"] > 0.0
    assert metrics["tail_ratio"] > 0.0
    assert "ulcer_index_pct" in metrics
    assert "capital_efficiency" in metrics
