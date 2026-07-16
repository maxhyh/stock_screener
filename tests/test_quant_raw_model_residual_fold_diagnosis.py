# -*- coding: utf-8 -*-
"""Raw model residual fold diagnosis tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import scripts.quant_raw_model_residual_fold_diagnosis as diag


def test_residual_failure_label_separates_absolute_and_relative_failures():
    assert (
        diag.residual_failure_label(
            {
                "top_mean_return_pct": -0.9,
                "top_minus_all_pct": 1.0,
                "top_minus_bottom_pct": 4.0,
                "rank_ic_mean": 0.1,
                "alpha_gate_pass": False,
            }
        )
        == "absolute_loss_but_beats_pool"
    )
    assert (
        diag.residual_failure_label(
            {
                "top_mean_return_pct": 1.0,
                "top_minus_all_pct": -0.2,
                "top_minus_bottom_pct": -0.5,
                "rank_ic_mean": 0.1,
                "alpha_gate_pass": False,
            }
        )
        == "positive_top_but_pool_and_bottom_lag"
    )
    assert diag.residual_failure_label({"alpha_gate_pass": True}) == "fold_passed"


def test_summarize_exante_failures_orders_by_severity():
    exante = pd.DataFrame(
        [
            {
                "fold": 2,
                "variant": "candidate",
                "regime_exante": "neutral",
                "days": 20,
                "top_mean_return_pct": -3.0,
                "top_minus_all_pct": -1.0,
                "top_minus_bottom_pct": 2.0,
                "rank_ic_mean": 0.1,
                "alpha_gate_pass": False,
                "failure_label": "top_mean_non_positive+top_not_above_pool",
            },
            {
                "fold": 2,
                "variant": "candidate",
                "regime_exante": "risk_off",
                "days": 5,
                "top_mean_return_pct": 1.0,
                "top_minus_all_pct": 0.5,
                "top_minus_bottom_pct": 1.0,
                "rank_ic_mean": 0.1,
                "alpha_gate_pass": True,
                "failure_label": "pass",
            },
        ]
    )

    text, detail = diag._summarize_exante_failures(exante, fold=2, variant="candidate")

    assert text.startswith("neutral:")
    assert detail["regime_exante"].tolist() == ["neutral"]
    assert detail["residual_failure_label"].tolist() == ["absolute_and_relative_failure"]


def test_build_residual_diagnosis_reads_artifact_family(tmp_path: Path):
    prefix = tmp_path / "quant_raw_model_instability_attribution_latest_demo"
    pd.DataFrame(
        [
            {
                "fold": 2,
                "variant": "baseline",
                "test_start": "2024-05-01",
                "test_end": "2024-08-31",
                "top_mean_return_pct": -2.0,
                "all_mean_return_pct": -1.0,
                "top_minus_all_pct": -1.0,
                "top_minus_bottom_pct": -1.0,
                "rank_ic_mean": 0.0,
                "alpha_gate_pass": False,
                "failure_label": "fail",
            },
            {
                "fold": 2,
                "variant": "candidate",
                "test_start": "2024-05-01",
                "test_end": "2024-08-31",
                "top_mean_return_pct": -0.5,
                "all_mean_return_pct": -2.0,
                "top_minus_all_pct": 1.5,
                "top_minus_bottom_pct": 2.0,
                "rank_ic_mean": 0.1,
                "alpha_gate_pass": False,
                "failure_label": "top_mean_non_positive",
            },
        ]
    ).to_csv(prefix.with_name(prefix.name + "_variant_summary.csv"), index=False)
    pd.DataFrame(
        [
            {
                "fold": 2,
                "variant": "candidate",
                "regime_exante": "neutral",
                "days": 10,
                "top_mean_return_pct": -0.5,
                "top_minus_all_pct": 1.5,
                "top_minus_bottom_pct": 2.0,
                "rank_ic_mean": 0.1,
                "alpha_gate_pass": False,
                "failure_label": "top_mean_non_positive",
            }
        ]
    ).to_csv(prefix.with_name(prefix.name + "_exante_regime_summary.csv"), index=False)
    pd.DataFrame(
        [
            {"fold": 2, "variant": "candidate", "regime_proxy_expost": "broad_down", "alpha_gate_pass": False}
        ]
    ).to_csv(prefix.with_name(prefix.name + "_regime_summary.csv"), index=False)
    pd.DataFrame(
        [
            {"fold": 2, "variant": "candidate", "feature": "bias", "top_minus_all": 3.0}
        ]
    ).to_csv(prefix.with_name(prefix.name + "_selected_feature_exposure.csv"), index=False)
    pd.DataFrame(
        [
            {
                "fold": 2,
                "variant": "candidate",
                "feature": "bias",
                "importance_share_pct": 3.0,
                "psi": 0.4,
                "std_mean_diff": 0.1,
            }
        ]
    ).to_csv(prefix.with_name(prefix.name + "_feature_importance_drift.csv"), index=False)

    summary, detail, payload = diag.build_residual_diagnosis(
        prefix=prefix,
        variant="candidate",
        baseline_variant="baseline",
        focus_folds=[2],
    )

    row = summary.iloc[0]
    assert row["residual_failure_label"] == "absolute_loss_but_beats_pool"
    assert row["delta_top_vs_baseline_pct"] == 1.5
    assert "neutral:" in row["failed_exante_regimes"]
    assert "bias:+3.000" in row["top_feature_exposures"]
    assert payload["overall_verdict"] == "residual_folds_explained_model_not_deployable"
    assert detail["focus_fold"].tolist() == [2]
