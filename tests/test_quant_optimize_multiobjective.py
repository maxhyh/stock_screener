# -*- coding: utf-8 -*-
"""quant_optimize 多目标评分与约束原因测试。"""

from __future__ import annotations

import sys

import pandas as pd

import scripts.quant_optimize as qo


def test_constraint_fail_reasons_collects_expected_tags():
    metrics = {
        "annual_return_pct": -1.0,
        "excess_annual_return_pct": -0.5,
        "sharpe": -0.1,
        "sortino": -0.3,
        "win_rate_pct": 45.0,
        "profit_factor": 0.8,
        "tail_ratio": 0.7,
        "capital_efficiency": -0.1,
        "max_drawdown_pct": -18.0,
        "ulcer_index_pct": 9.2,
        "annual_turnover_pct": 6000.0,
    }
    robust = {
        "oos_valid_windows": 1,
        "oos_excess_total_median": -0.2,
        "oos_mdd_worst": -20.0,
        "oos_pass_rate": 0.2,
        "oos_valid_window_ratio": 0.3,
    }
    reasons = qo._constraint_fail_reasons(
        metrics,
        robust,
        robust_on=True,
        min_windows=3,
        min_annual_return_pct=0.0,
        min_excess_annual_pct=0.0,
        min_sharpe=0.0,
        min_sortino=0.0,
        min_win_rate_pct=50.0,
        min_profit_factor=1.0,
        min_tail_ratio=0.95,
        min_capital_efficiency=0.0,
        max_drawdown_limit_pct=-15.0,
        max_ulcer_index_pct=8.0,
        turnover_cap_pct=4500.0,
        min_oos_excess_total_median=0.0,
        min_oos_mdd_worst=-15.0,
        min_oos_pass_rate=0.45,
        min_oos_valid_window_ratio=0.60,
    )
    assert "annual_return" in reasons
    assert "excess_annual" in reasons
    assert "sharpe" in reasons
    assert "sortino" in reasons
    assert "win_rate" in reasons
    assert "profit_factor" in reasons
    assert "tail_ratio" in reasons
    assert "capital_efficiency" in reasons
    assert "max_drawdown" in reasons
    assert "ulcer_index" in reasons
    assert "turnover" in reasons
    assert "oos_valid_windows" in reasons
    assert "oos_excess_total_median" in reasons
    assert "oos_mdd_worst" in reasons
    assert "oos_pass_rate" in reasons
    assert "oos_valid_window_ratio" in reasons


def test_compute_multi_objective_score_prefers_better_combo():
    df = pd.DataFrame(
        [
            {
                "annual_return_pct": 20.0,
                "excess_annual_return_pct": 12.0,
                "sharpe": 1.5,
                "sortino": 2.2,
                "calmar": 1.8,
                "win_rate_pct": 58.0,
                "info_ratio": 0.9,
                "profit_factor": 1.9,
                "tail_ratio": 1.4,
                "capital_efficiency": 0.42,
                "max_drawdown_pct": -10.0,
                "ulcer_index_pct": 4.0,
                "annual_turnover_pct": 2500.0,
            },
            {
                "annual_return_pct": 8.0,
                "excess_annual_return_pct": 2.0,
                "sharpe": 0.5,
                "sortino": 0.6,
                "calmar": 0.3,
                "win_rate_pct": 48.0,
                "info_ratio": 0.1,
                "profit_factor": 0.9,
                "tail_ratio": 0.8,
                "capital_efficiency": 0.10,
                "max_drawdown_pct": -20.0,
                "ulcer_index_pct": 11.0,
                "annual_turnover_pct": 5500.0,
            },
        ]
    )
    s = qo._compute_multi_objective_score(
        df,
        robust_on=False,
        w_annual=0.18,
        w_excess_annual=0.28,
        w_sharpe=0.18,
        w_sortino=0.12,
        w_calmar=0.10,
        w_win_rate=0.08,
        w_info=0.06,
        w_profit_factor=0.08,
        w_tail_ratio=0.05,
        w_capital_efficiency=0.06,
        w_mdd=0.18,
        w_ulcer=0.10,
        w_turnover=0.12,
        w_oos_excess=0.20,
        w_oos_pass=0.10,
        w_oos_mdd=0.12,
    )
    assert s.iloc[0] > s.iloc[1]


def test_score_rewards_return_quality_metrics():
    better = {
        "annual_return_pct": 12.0,
        "excess_annual_return_pct": 7.0,
        "sharpe": 1.1,
        "sortino": 1.8,
        "calmar": 1.2,
        "win_rate_pct": 54.0,
        "beat_rate_pct": 57.0,
        "total_return_pct": 18.0,
        "profit_factor": 1.6,
        "tail_ratio": 1.3,
        "capital_efficiency": 0.30,
        "max_drawdown_pct": -9.0,
        "ulcer_index_pct": 3.8,
        "annual_turnover_pct": 2200.0,
    }
    worse = {
        "annual_return_pct": 12.0,
        "excess_annual_return_pct": 7.0,
        "sharpe": 1.1,
        "sortino": 0.9,
        "calmar": 0.6,
        "win_rate_pct": 54.0,
        "beat_rate_pct": 57.0,
        "total_return_pct": 18.0,
        "profit_factor": 1.0,
        "tail_ratio": 0.9,
        "capital_efficiency": 0.18,
        "max_drawdown_pct": -9.0,
        "ulcer_index_pct": 8.5,
        "annual_turnover_pct": 2200.0,
    }
    assert qo._score(better) > qo._score(worse)


def test_build_paper_recommendations_fallback_when_no_pass():
    res = pd.DataFrame(
        [
            {
                "rank": 1,
                "pass_hard_filters": 0,
                "top_n": 10,
                "holding_days": 3,
                "max_single_pos": 0.06,
                "use_regime_position": 0,
                "objective_score": 12.3,
                "rank_score": 2.2,
                "annual_return_pct": 5.0,
                "excess_annual_return_pct": 1.0,
                "max_drawdown_pct": -18.0,
                "sharpe": 0.4,
                "win_rate_pct": 49.0,
                "annual_turnover_pct": 5000.0,
                "constraint_fail_reasons": "sharpe,max_drawdown",
            }
        ]
    )
    rec = qo._build_paper_recommendations(res, robust_on=False, top_k=3)
    assert len(rec) == 1
    assert rec.iloc[0]["selection_mode"] == "fallback_by_objective_score"


def test_passes_hard_filters_checks_quality_constraints():
    metrics = {
        "annual_return_pct": 12.0,
        "excess_annual_return_pct": 5.0,
        "sharpe": 1.0,
        "sortino": 1.3,
        "win_rate_pct": 53.0,
        "profit_factor": 1.4,
        "tail_ratio": 1.2,
        "capital_efficiency": 0.2,
        "max_drawdown_pct": -9.0,
        "ulcer_index_pct": 4.5,
        "annual_turnover_pct": 2100.0,
    }
    assert qo._passes_hard_filters(
        metrics,
        min_annual_return_pct=0.0,
        min_excess_annual_pct=0.0,
        min_sharpe=0.0,
        min_sortino=0.0,
        min_win_rate_pct=50.0,
        min_profit_factor=1.1,
        min_tail_ratio=1.0,
        min_capital_efficiency=0.0,
        max_drawdown_limit_pct=-15.0,
        max_ulcer_index_pct=8.0,
        turnover_cap_pct=4500.0,
    )
    assert not qo._passes_hard_filters(
        {**metrics, "profit_factor": 0.95, "ulcer_index_pct": 9.5},
        min_annual_return_pct=0.0,
        min_excess_annual_pct=0.0,
        min_sharpe=0.0,
        min_sortino=0.0,
        min_win_rate_pct=50.0,
        min_profit_factor=1.1,
        min_tail_ratio=1.0,
        min_capital_efficiency=0.0,
        max_drawdown_limit_pct=-15.0,
        max_ulcer_index_pct=8.0,
        turnover_cap_pct=4500.0,
    )


def test_main_passes_signal_refactor_args_to_backtest(monkeypatch, tmp_path):
    captured_cfgs = []

    def fake_backtest_portfolio(cfg):
        captured_cfgs.append(cfg)
        return pd.DataFrame(), {
            "trade_count": 1,
            "total_return_pct": 5.0,
            "annual_return_pct": 8.0,
            "max_drawdown_pct": -6.0,
            "sharpe": 1.1,
            "sortino": 1.4,
            "calmar": 0.9,
            "win_rate_pct": 55.0,
            "benchmark_annual_return_pct": 2.0,
            "excess_annual_return_pct": 6.0,
            "beat_rate_pct": 60.0,
            "info_ratio": 0.9,
            "profit_factor": 1.3,
            "tail_ratio": 1.2,
            "capital_efficiency": 0.24,
            "ulcer_index_pct": 3.8,
            "avg_exposure_pct": 50.0,
            "annual_turnover_pct": 1200.0,
            "trades_per_year": 30.0,
        }

    monkeypatch.setattr(qo, "backtest_portfolio", fake_backtest_portfolio)
    monkeypatch.setattr(qo, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_optimize.py",
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
            "--robust-mode",
            "off",
            "--disable-signal-quality-gate",
            "--min-signal-quality",
            "0.43",
            "--ml-quality-blend",
            "0.74",
            "--max-abs-pct-chg",
            "8.6",
            "--disable-feature-refactor",
            "--stability-blend",
            "0.31",
            "--disable-feature-refactor-gate",
            "--min-refactor-score",
            "0.56",
            "--min-sortino",
            "0.7",
            "--min-profit-factor",
            "1.05",
            "--min-tail-ratio",
            "1.01",
            "--min-capital-efficiency",
            "0.02",
            "--max-ulcer-index-pct",
            "7.5",
        ],
    )

    rc = qo.main()
    assert rc == 0
    assert len(captured_cfgs) >= 2
    for cfg in captured_cfgs:
        assert cfg.enable_signal_quality_gate is False
        assert cfg.min_signal_quality == 0.43
        assert cfg.ml_quality_blend == 0.74
        assert cfg.max_abs_pct_chg == 8.6
        assert cfg.enable_feature_refactor is False
        assert cfg.stability_blend == 0.31
        assert cfg.enable_feature_refactor_gate is False
        assert cfg.min_refactor_score == 0.56
