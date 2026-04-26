# -*- coding: utf-8 -*-
"""quant_profile_rolling_compare 脚本测试。"""

from __future__ import annotations

import json
import sys

import pandas as pd

import scripts.quant_profile_rolling_compare as rolling


def test_quant_profile_rolling_compare_main_writes_outputs(tmp_path, monkeypatch):
    config_file = tmp_path / "quant_live_profiles.json"
    config_file.write_text(
        json.dumps(
            {
                "default_profile": "quality_regime",
                "profiles": {
                    "quality_regime": {
                        "top_n": 13,
                        "holding_days": 8,
                        "fee_bps": 8.0,
                        "slippage_bps": 5.0,
                        "max_single_pos": 0.04,
                        "use_regime_position": True,
                        "fallback_total_position": 0.60,
                        "exclude_st": True,
                        "exclude_bj9": True,
                        "min_valid_positions": 4,
                        "engine_mode": "hybrid",
                        "benchmark_mode": "hs300",
                        "risk_window": 8,
                        "risk_cut_factor": 0.75,
                        "min_signal_quality": 0.48,
                        "ml_quality_blend": 0.78,
                        "min_refactor_score": 0.56,
                    },
                    "quality_regime_candidate": {
                        "top_n": 15,
                        "holding_days": 8,
                        "fee_bps": 8.0,
                        "slippage_bps": 5.0,
                        "max_single_pos": 0.04,
                        "use_regime_position": True,
                        "fallback_total_position": 0.60,
                        "exclude_st": True,
                        "exclude_bj9": True,
                        "min_valid_positions": 4,
                        "engine_mode": "hybrid",
                        "benchmark_mode": "hs300",
                        "risk_window": 8,
                        "risk_cut_factor": 0.75,
                        "min_signal_quality": 0.48,
                        "ml_quality_blend": 0.76,
                        "min_refactor_score": 0.58,
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_backtest(cfg):
        annual = 20.0 + (2.0 if int(cfg.top_n) == 15 else 0.0)
        return pd.DataFrame([{"x": 1}]), {
            "trade_count": 8,
            "annual_return_pct": annual,
            "excess_annual_return_pct": annual - 6.0,
            "max_drawdown_pct": -4.0,
            "sharpe": 1.5 + annual / 20.0,
            "sortino": 2.0 + annual / 10.0,
            "profit_factor": 1.2 + annual / 20.0,
            "tail_ratio": 1.1 + annual / 40.0,
            "ulcer_index_pct": 1.5,
            "capital_efficiency": 0.20 + annual / 100.0,
            "win_rate_pct": 55.0,
            "beat_rate_pct": 52.0,
            "annual_turnover_pct": 1800.0,
        }

    monkeypatch.setattr(rolling, "backtest_portfolio", fake_backtest)
    monkeypatch.setattr(rolling, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_profile_rolling_compare.py",
            "--config",
            str(config_file),
            "--profiles",
            "quality_regime,quality_regime_candidate",
            "--start",
            "2025-06-01",
            "--end",
            "2026-04-10",
            "--train-months",
            "4",
            "--test-months",
            "2",
            "--step-months",
            "2",
        ],
    )

    rc = rolling.main()

    assert rc == 0
    backtest_dir = tmp_path / "output" / "backtest"
    detail_files = list(backtest_dir.glob("quant_profile_rolling_compare_detail_*.csv"))
    summary_files = list(backtest_dir.glob("quant_profile_rolling_compare_summary_*.csv"))
    assert detail_files
    assert summary_files

    summary = pd.read_csv(summary_files[0])
    assert {"profile", "window_count", "objective_score"} <= set(summary.columns)
    assert len(summary) == 2
    assert summary.iloc[0]["profile"] == "quality_regime_candidate"
