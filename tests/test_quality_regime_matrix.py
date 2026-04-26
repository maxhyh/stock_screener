# -*- coding: utf-8 -*-
"""quality_regime 局部实验矩阵脚本测试。"""

from __future__ import annotations

import json
import sys

import pandas as pd

import scripts.quant_quality_regime_matrix as qrm


def test_build_recommended_table_prefers_robust_pass_and_positive_ulcer_improvement():
    matrix_df = pd.DataFrame(
        [
            {
                "top_n": 12,
                "holding_days": 8,
                "min_signal_quality": 0.50,
                "ml_quality_blend": 0.80,
                "min_refactor_score": 0.53,
                "risk_window": 8,
                "risk_cut_factor": 0.75,
                "pass_hard_filters": 1,
                "rank_score": 9.0,
                "annual_return_pct": 20.0,
                "excess_annual_return_pct": 10.0,
                "max_drawdown_pct": -6.0,
                "sharpe": 1.8,
                "sortino": 3.0,
                "profit_factor": 2.0,
                "tail_ratio": 1.6,
                "ulcer_index_pct": 2.0,
                "capital_efficiency": 0.30,
            }
        ]
    )
    robust_df = pd.DataFrame(
        [
            {
                "top_n": 12,
                "holding_days": 8,
                "min_signal_quality": 0.50,
                "ml_quality_blend": 0.80,
                "min_refactor_score": 0.53,
                "risk_window": 8,
                "risk_cut_factor": 0.75,
                "pass_robust_hard_filters": 0,
                "robust_score": 8.0,
                "rank_score": 9.0,
                "annual_return_pct": 20.0,
                "excess_annual_return_pct": 10.0,
                "max_drawdown_pct": -6.0,
                "sharpe": 1.8,
                "sortino": 3.0,
                "profit_factor": 2.0,
                "tail_ratio": 1.6,
                "ulcer_index_pct": 2.0,
                "capital_efficiency": 0.30,
            },
            {
                "top_n": 13,
                "holding_days": 8,
                "min_signal_quality": 0.53,
                "ml_quality_blend": 0.82,
                "min_refactor_score": 0.56,
                "risk_window": 10,
                "risk_cut_factor": 0.80,
                "pass_robust_hard_filters": 1,
                "robust_score": 9.5,
                "rank_score": 9.2,
                "annual_return_pct": 22.0,
                "excess_annual_return_pct": 12.0,
                "max_drawdown_pct": -5.0,
                "sharpe": 2.0,
                "sortino": 3.6,
                "profit_factor": 2.4,
                "tail_ratio": 1.8,
                "ulcer_index_pct": 1.5,
                "capital_efficiency": 0.35,
                "oos_excess_total_median": 1.2,
                "oos_mdd_worst": -6.0,
                "oos_pass_rate": 0.75,
            },
        ]
    )

    out = qrm._build_recommended_table(
        matrix_df,
        robust_df,
        baseline={"ulcer_index_pct": 2.5},
        top_k=2,
    )

    assert len(out) == 1
    assert str(out.loc[0, "selection_source"]) == "robust_pass"
    assert int(out.loc[0, "top_n"]) == 13
    assert float(out.loc[0, "improvement_ulcer_index_pct"]) == 1.0


def test_build_elimination_table_uses_only_evaluated_robust_pass_rate():
    matrix_df = pd.DataFrame(
        [
            {
                "top_n": 12,
                "min_signal_quality": 0.48,
                "ml_quality_blend": 0.78,
                "min_refactor_score": 0.53,
                "risk_window": 8,
                "risk_cut_factor": 0.75,
                "pass_hard_filters": 0,
                "rank_score": 1.0,
                "excess_annual_return_pct": 1.0,
                "sortino": 0.4,
                "profit_factor": 0.9,
                "tail_ratio": 0.8,
                "ulcer_index_pct": 5.0,
            },
            {
                "top_n": 12,
                "min_signal_quality": 0.50,
                "ml_quality_blend": 0.80,
                "min_refactor_score": 0.53,
                "risk_window": 8,
                "risk_cut_factor": 0.75,
                "pass_hard_filters": 0,
                "rank_score": 1.2,
                "excess_annual_return_pct": 1.2,
                "sortino": 0.5,
                "profit_factor": 0.95,
                "tail_ratio": 0.85,
                "ulcer_index_pct": 5.1,
            },
            {
                "top_n": 13,
                "min_signal_quality": 0.53,
                "ml_quality_blend": 0.82,
                "min_refactor_score": 0.56,
                "risk_window": 10,
                "risk_cut_factor": 0.80,
                "pass_hard_filters": 1,
                "rank_score": 9.5,
                "excess_annual_return_pct": 12.0,
                "sortino": 3.0,
                "profit_factor": 2.0,
                "tail_ratio": 1.8,
                "ulcer_index_pct": 1.5,
            },
        ]
    )
    robust_df = pd.DataFrame(
        [
            {
                "top_n": 13,
                "min_signal_quality": 0.53,
                "ml_quality_blend": 0.82,
                "min_refactor_score": 0.56,
                "risk_window": 10,
                "risk_cut_factor": 0.80,
                "pass_robust_hard_filters": 1,
            }
        ]
    )

    out = qrm._build_elimination_table(
        matrix_df,
        robust_df,
        baseline={
            "excess_annual_return_pct": 5.0,
            "sortino": 1.0,
            "profit_factor": 1.2,
            "tail_ratio": 1.1,
            "ulcer_index_pct": 3.0,
        },
    )

    row = out.loc[out["dimension"] == "TopN"].iloc[0]
    assert float(row["robust_evaluated_share"]) == 0.0
    assert pd.isna(row["robust_pass_share_of_evaluated"])
    assert "no_robust_pass_in_evaluated" not in str(row["reasons"])


def test_quality_regime_matrix_main_writes_outputs(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {
                        "top_n": 12,
                        "holding_days": 8,
                        "max_single_pos": 0.04,
                        "use_regime_position": True,
                        "fallback_total_position": 0.60,
                        "exclude_st": True,
                        "exclude_bj9": True,
                        "min_valid_positions": 4,
                        "engine_mode": "hybrid",
                        "benchmark_mode": "hs300",
                        "max_industry_positions": 3,
                        "max_pair_corr": 0.85,
                        "corr_lookback_days": 60,
                        "corr_min_obs": 15,
                        "risk_window": 8,
                        "risk_cut_win_rate": 0.35,
                        "risk_cut_avg_ret": -0.005,
                        "risk_cut_factor": 0.75,
                        "min_signal_quality": 0.40,
                        "ml_quality_blend": 0.80,
                        "max_abs_pct_chg": 8.5,
                        "stability_blend": 0.30,
                        "min_refactor_score": 0.50,
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_backtest(cfg):
        annual = 10.0
        annual += 3.0 if int(cfg.top_n) == 12 else 0.0
        annual -= abs(float(cfg.min_signal_quality) - 0.42) * 20.0
        annual -= abs(float(cfg.ml_quality_blend) - 0.76) * 15.0
        annual -= abs(float(cfg.min_refactor_score) - 0.53) * 20.0
        annual -= abs(int(cfg.risk_window) - 8) * 0.8
        annual -= abs(float(cfg.risk_cut_factor) - 0.75) * 10.0
        return pd.DataFrame([{"x": 1}]), {
            "trade_count": 12,
            "total_return_pct": annual * 1.3,
            "annual_return_pct": annual,
            "max_drawdown_pct": -5.0,
            "sharpe": 1.1 + annual / 20.0,
            "sortino": 1.4 + annual / 10.0,
            "calmar": 1.0 + annual / 10.0,
            "win_rate_pct": 56.0,
            "avg_trade_return_pct": 0.5,
            "avg_win_return_pct": 1.1,
            "avg_loss_return_pct": -0.7,
            "profit_factor": 1.25 + annual / 20.0,
            "payoff_ratio": 1.1,
            "tail_ratio": 1.05 + annual / 40.0,
            "ulcer_index_pct": 2.5,
            "recovery_factor": 1.2,
            "capital_efficiency": 0.15 + annual / 100.0,
            "avg_exposure_pct": 60.0,
            "annual_turnover_pct": 2200.0,
            "trades_per_year": 30.0,
            "benchmark_total_return_pct": 8.0,
            "benchmark_annual_return_pct": 6.0,
            "benchmark_exposure_adj_total_return_pct": 5.0,
            "benchmark_exposure_adj_annual_return_pct": 4.0,
            "excess_total_return_pct": annual * 0.8,
            "excess_annual_return_pct": annual * 0.6,
            "beat_rate_pct": 52.0,
            "info_ratio": 0.6,
            "max_dd_duration_trades": 2,
        }

    def fake_robust(cfg_kwargs, windows, min_trades_per_window=1):
        top_n_bonus = 1.0 if int(cfg_kwargs["top_n"]) == 12 else -1.0
        q_bonus = 0.8 if abs(float(cfg_kwargs["min_signal_quality"]) - 0.42) < 1e-9 else -0.4
        return {
            "oos_windows": len(windows),
            "oos_valid_windows": len(windows),
            "oos_valid_window_ratio": 1.0,
            "oos_excess_annual_mean": 2.0 + top_n_bonus,
            "oos_excess_annual_median": 2.0 + top_n_bonus,
            "oos_excess_annual_p25": 1.5 + top_n_bonus,
            "oos_excess_total_mean": 1.6 + top_n_bonus + q_bonus,
            "oos_excess_total_median": 1.6 + top_n_bonus + q_bonus,
            "oos_excess_total_p25": 1.2 + top_n_bonus,
            "oos_total_mean": 2.5,
            "oos_total_median": 2.4,
            "oos_total_p25": 1.8,
            "oos_annual_mean": 6.0,
            "oos_mdd_worst": -6.0,
            "oos_mdd_std": 1.0,
            "oos_sharpe_mean": 0.8,
            "oos_beat_rate_mean": 55.0,
            "oos_pass_rate": 0.75,
        }

    monkeypatch.setattr(qrm, "backtest_portfolio", fake_backtest)
    monkeypatch.setattr(qrm, "_robust_oos_metrics", fake_robust)
    monkeypatch.setattr(
        qrm,
        "_build_oos_windows",
        lambda start, end, warmup_months, test_months, step_months: [("2025-01-01", "2025-02-28")],
    )
    monkeypatch.setattr(qrm, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_quality_regime_matrix.py",
            "--start",
            "2025-06-01",
            "--end",
            "2026-04-10",
            "--config",
            str(config_file),
            "--topn-grid",
            "11,12",
            "--quality-grid",
            "0.40,0.42",
            "--ml-blend-grid",
            "0.76",
            "--refactor-floor-grid",
            "0.50,0.53",
            "--risk-window-grid",
            "8",
            "--risk-cut-factor-grid",
            "0.75",
            "--top-k-robust",
            "3",
            "--jobs",
            "1",
        ],
    )

    rc = qrm.main()

    assert rc == 0
    backtest_dir = tmp_path / "output" / "backtest"
    matrix_files = list(backtest_dir.glob("quality_regime_matrix_*.csv"))
    shortlist_files = list(backtest_dir.glob("quality_regime_matrix_shortlist_*.csv"))
    json_files = list(backtest_dir.glob("quality_regime_matrix_*.json"))
    assert matrix_files
    assert shortlist_files
    assert json_files

    payload = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert int(payload["best_in_sample"]["top_n"]) == 12
    assert float(payload["best_robust"]["min_signal_quality"]) == 0.42
