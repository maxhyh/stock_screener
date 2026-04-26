# -*- coding: utf-8 -*-
"""Signal refactor compare helpers tests."""

from __future__ import annotations

import pandas as pd

import scripts.quant_signal_refactor_compare as qsrc


def test_add_delta_vs_base_computes_metric_delta():
    df = pd.DataFrame(
        [
            {"variant": "baseline", "annual_return_pct": 10.0, "excess_annual_return_pct": 4.0, "max_drawdown_pct": -8.0, "sharpe": 1.0},
            {"variant": "refactor", "annual_return_pct": 12.5, "excess_annual_return_pct": 6.0, "max_drawdown_pct": -7.0, "sharpe": 1.2},
        ]
    )
    for col in qsrc.DISPLAY_METRICS:
        if col not in df.columns:
            df[col] = 0.0
    out = qsrc._add_delta_vs_base(df, base_variant="baseline")
    row = out[out["variant"] == "refactor"].iloc[0]
    assert row["delta_annual_return_pct"] == 2.5
    assert row["delta_excess_annual_return_pct"] == 2.0


def test_pick_best_variant_prefers_higher_excess_then_sharpe():
    df = pd.DataFrame(
        [
            {"variant": "baseline", "excess_annual_return_pct": 5.0, "sharpe": 1.10, "max_drawdown_pct": -7.0},
            {"variant": "refactor", "excess_annual_return_pct": 5.0, "sharpe": 1.22, "max_drawdown_pct": -8.0},
            {"variant": "refactor_no_gate", "excess_annual_return_pct": 4.5, "sharpe": 1.30, "max_drawdown_pct": -6.0},
        ]
    )
    best = qsrc._pick_best_variant(df)
    assert best == "refactor"
