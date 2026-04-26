# -*- coding: utf-8 -*-
"""Walk-forward hard-filter wiring tests."""

from __future__ import annotations

import sys

import pandas as pd

import scripts.quant_walk_forward as qwf


def test_pick_best_params_passes_hard_filter_thresholds(monkeypatch):
    captured = {}

    def fake_backtest_portfolio(cfg):
        return pd.DataFrame(), {
            "annual_return_pct": 10.0,
            "excess_annual_return_pct": 3.0,
            "max_drawdown_pct": -8.0,
            "sharpe": 1.2,
            "sortino": 1.4,
            "win_rate_pct": 55.0,
            "profit_factor": 1.3,
            "tail_ratio": 1.1,
            "capital_efficiency": 0.2,
            "ulcer_index_pct": 4.5,
            "annual_turnover_pct": 2200.0,
        }

    def fake_pass(metrics, **kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(qwf, "backtest_portfolio", fake_backtest_portfolio)
    monkeypatch.setattr(qwf, "_passes_hard_filters", fake_pass)
    monkeypatch.setattr(qwf, "_score", lambda metrics: 42.0)

    chosen, best = qwf._pick_best_params(
        "2026-01-01",
        "2026-01-31",
        combos=[(10, 5, 0.05, False)],
        static_kwargs={},
        min_annual_return_pct=0.0,
        min_excess_annual_pct=0.0,
        min_sharpe=0.0,
        min_sortino=0.0,
        min_win_rate_pct=0.0,
        min_profit_factor=1.0,
        min_tail_ratio=0.95,
        min_capital_efficiency=0.0,
        max_drawdown_limit_pct=-15.0,
        max_ulcer_index_pct=8.0,
        turnover_cap_pct=4500.0,
    )

    assert chosen["top_n"] == 10
    assert chosen["holding_days"] == 5
    assert best["rank_score"] == 42.0
    assert captured["min_annual_return_pct"] == 0.0
    assert captured["max_drawdown_limit_pct"] == -15.0
    assert captured["min_profit_factor"] == 1.0
    assert captured["max_ulcer_index_pct"] == 8.0
    assert captured["turnover_cap_pct"] == 4500.0


def test_main_passes_signal_refactor_args_to_backtest(monkeypatch, tmp_path):
    captured_cfgs = []

    def fake_backtest_portfolio(cfg):
        captured_cfgs.append(cfg)
        return pd.DataFrame(), {
            "trade_count": 1,
            "annual_return_pct": 10.0,
            "excess_annual_return_pct": 3.0,
            "max_drawdown_pct": -8.0,
            "sharpe": 1.0,
            "sortino": 1.3,
            "win_rate_pct": 55.0,
            "beat_rate_pct": 60.0,
            "profit_factor": 1.2,
            "tail_ratio": 1.1,
            "capital_efficiency": 0.2,
            "ulcer_index_pct": 4.0,
            "annual_turnover_pct": 1200.0,
        }

    monkeypatch.setattr(qwf, "backtest_portfolio", fake_backtest_portfolio)
    monkeypatch.setattr(qwf, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(
        qwf,
        "_iter_windows",
        lambda start, end, train_months, test_months, step_months: [
            (
                1,
                pd.Timestamp("2026-01-01"),
                pd.Timestamp("2026-01-31"),
                pd.Timestamp("2026-02-01"),
                pd.Timestamp("2026-02-28"),
            )
        ],
    )
    monkeypatch.setattr(qwf, "_calc_metrics", lambda df, holding_days: {"trade_count": len(df), "annual_return_pct": 0.0, "excess_annual_return_pct": 0.0, "max_drawdown_pct": 0.0, "sharpe": 0.0, "beat_rate_pct": 0.0, "total_return_pct": 0.0})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_walk_forward.py",
            "--start",
            "2026-01-01",
            "--end",
            "2026-03-20",
            "--topn-grid",
            "10",
            "--hold-grid",
            "5",
            "--maxpos-grid",
            "0.05",
            "--no-regime-position",
            "--disable-signal-quality-gate",
            "--min-signal-quality",
            "0.41",
            "--ml-quality-blend",
            "0.79",
            "--max-abs-pct-chg",
            "8.8",
            "--disable-feature-refactor",
            "--stability-blend",
            "0.33",
            "--disable-feature-refactor-gate",
            "--min-refactor-score",
            "0.57",
            "--min-sortino",
            "0.70",
            "--min-profit-factor",
            "1.05",
            "--min-tail-ratio",
            "1.00",
            "--min-capital-efficiency",
            "0.02",
            "--max-ulcer-index-pct",
            "7.50",
        ],
    )

    rc = qwf.main()
    assert rc == 0
    assert len(captured_cfgs) >= 2
    for cfg in captured_cfgs:
        assert cfg.enable_signal_quality_gate is False
        assert cfg.min_signal_quality == 0.41
        assert cfg.ml_quality_blend == 0.79
        assert cfg.max_abs_pct_chg == 8.8
        assert cfg.enable_feature_refactor is False
        assert cfg.stability_blend == 0.33
        assert cfg.enable_feature_refactor_gate is False
        assert cfg.min_refactor_score == 0.57
