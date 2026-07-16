# -*- coding: utf-8 -*-
"""State-migration diagnosis tests."""

from __future__ import annotations

import pandas as pd

import scripts.quant_raw_model_state_migration_diagnosis as diag


def test_build_calibration_detail_flags_optimistic_expected_deploy_days(monkeypatch):
    fit = pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-01-01", periods=2),
            "market_regime_exante": ["neutral", "neutral"],
            "deploy_day_all_mean_return_pct": [1.0, 1.2],
            "deploy_day_positive_rate_pct": [60.0, 62.0],
            "deploy_day_left_tail_rate_pct": [20.0, 18.0],
            "x": [1.0, 2.0],
        }
    )
    target = pd.DataFrame(
        {
            "trade_date": pd.date_range("2026-02-01", periods=2),
            "market_regime_exante": ["neutral", "neutral"],
            "deploy_day_all_mean_return_pct": [-2.0, -1.5],
            "deploy_day_positive_rate_pct": [30.0, 35.0],
            "deploy_day_left_tail_rate_pct": [55.0, 50.0],
            "x": [1.0, 2.0],
        }
    )

    monkeypatch.setattr(
        diag,
        "_knn_day_expectation",
        lambda *args, target_col, **kwargs: pd.Series(
            {
                pd.Timestamp("2026-02-01"): {
                    "deploy_day_all_mean_return_pct": 1.0,
                    "deploy_day_positive_rate_pct": 60.0,
                    "deploy_day_left_tail_rate_pct": 20.0,
                }[target_col],
                pd.Timestamp("2026-02-02"): {
                    "deploy_day_all_mean_return_pct": 1.0,
                    "deploy_day_positive_rate_pct": 60.0,
                    "deploy_day_left_tail_rate_pct": 20.0,
                }[target_col],
            }
        ),
    )

    out = diag.build_calibration_detail(fit, target, split="test", neighbor_days=1)

    assert out["expected_deploy_signal"].tolist() == [True, True]
    assert out["actual_positive_day"].tolist() == [False, False]
    assert out["calibration_error_pct"].tolist() == [-3.0, -2.5]


def test_summarize_calibration_reports_deployed_actual_return():
    detail = pd.DataFrame(
        {
            "split": ["test", "test", "test"],
            "expected_return_pct": [1.0, 1.0, -1.0],
            "actual_return_pct": [-2.0, 1.0, -1.0],
            "calibration_error_pct": [-3.0, 0.0, 0.0],
            "expected_deploy_signal": [True, True, False],
            "actual_positive_day": [False, True, False],
        }
    )

    out = diag.summarize_calibration(detail).iloc[0]

    assert out["days"] == 3
    assert out["expected_deploy_days"] == 2
    assert round(float(out["expected_deploy_rate_pct"]), 2) == 66.67
    assert float(out["deployed_actual_return_mean_pct"]) == -0.5


def test_build_state_migration_verdict_detects_optimistic_miscalibration():
    cal = pd.DataFrame(
        {
            "split": ["valid", "test"],
            "expected_return_mean_pct": [1.0, 1.3],
            "actual_return_mean_pct": [1.1, -1.8],
            "calibration_error_mean_pct": [0.1, -3.1],
            "expected_deploy_rate_pct": [100.0, 100.0],
        }
    )
    drift = pd.DataFrame({"split": ["test"], "psi": [0.1], "std_mean_diff": [0.2]})
    regimes = pd.DataFrame(
        {
            "split": ["test"],
            "market_regime_exante": ["neutral"],
            "day_mean_return_pct": [-1.8],
        }
    )

    verdict = diag.build_state_migration_verdict(cal, drift, regimes)

    assert verdict["state_migration_verdict"] == "optimistic_deployability_miscalibration"
    assert verdict["test_calibration_error_mean_pct"] == -3.1


def test_build_state_migration_verdict_detects_state_distribution_shift():
    cal = pd.DataFrame(
        {
            "split": ["valid", "test"],
            "expected_return_mean_pct": [0.5, -0.2],
            "actual_return_mean_pct": [0.2, -0.3],
            "calibration_error_mean_pct": [-0.3, -0.1],
            "expected_deploy_rate_pct": [30.0, 20.0],
        }
    )
    drift = pd.DataFrame({"split": ["test"], "psi": [0.5], "std_mean_diff": [0.2]})

    verdict = diag.build_state_migration_verdict(cal, drift, pd.DataFrame())

    assert verdict["state_migration_verdict"] == "state_distribution_shift"
