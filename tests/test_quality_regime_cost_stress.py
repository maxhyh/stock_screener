# -*- coding: utf-8 -*-
"""quality_regime 成本压力测试脚本测试。"""

from __future__ import annotations

import json
import sys

import pandas as pd

import scripts.quant_quality_regime_cost_stress as stress


def test_quality_regime_cost_stress_main_writes_outputs(tmp_path, monkeypatch):
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
                        "max_industry_positions": 3,
                        "corr_lookback_days": 60,
                        "max_pair_corr": 0.85,
                        "corr_min_obs": 15,
                        "risk_window": 8,
                        "risk_cut_win_rate": 0.35,
                        "risk_cut_avg_ret": -0.005,
                        "risk_cut_factor": 0.75,
                        "min_signal_quality": 0.48,
                        "ml_quality_blend": 0.78,
                        "max_abs_pct_chg": 8.5,
                        "stability_blend": 0.30,
                        "min_refactor_score": 0.56,
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_backtest(cfg):
        total_cost = float(cfg.fee_bps) + float(cfg.slippage_bps)
        annual = 26.0 - total_cost * 0.3
        return pd.DataFrame([{"x": 1}]), {
            "trade_count": 20,
            "annual_return_pct": annual,
            "excess_annual_return_pct": annual - 8.0,
            "max_drawdown_pct": -5.0 - total_cost * 0.02,
            "sharpe": 2.4 - total_cost * 0.01,
            "sortino": 6.2 - total_cost * 0.02,
            "profit_factor": 3.7 - total_cost * 0.01,
            "tail_ratio": 3.2 - total_cost * 0.01,
            "ulcer_index_pct": 1.1 + total_cost * 0.01,
            "capital_efficiency": 0.70 - total_cost * 0.005,
        }

    monkeypatch.setattr(stress, "backtest_portfolio", fake_backtest)
    monkeypatch.setattr(stress, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_quality_regime_cost_stress.py",
            "--start",
            "2025-06-01",
            "--end",
            "2026-04-10",
            "--config",
            str(config_file),
            "--fee-grid",
            "8,10",
            "--slippage-grid",
            "5,7",
        ],
    )

    rc = stress.main()

    assert rc == 0
    backtest_dir = tmp_path / "output" / "backtest"
    csv_files = list(backtest_dir.glob("quality_regime_cost_stress_*.csv"))
    json_files = list(backtest_dir.glob("quality_regime_cost_stress_*.json"))
    assert csv_files
    assert json_files

    out = pd.read_csv(csv_files[0])
    assert {"fee_bps", "slippage_bps", "delta_annual_return_pct", "delta_sharpe"} <= set(out.columns)
    assert len(out) == 4
