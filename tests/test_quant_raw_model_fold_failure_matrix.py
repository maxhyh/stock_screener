# -*- coding: utf-8 -*-
"""Raw model critical-fold failure matrix tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import scripts.quant_raw_model_fold_failure_matrix as matrix


def test_summarize_feature_exposure_reports_consistent_signed_bias():
    exposure = pd.DataFrame(
        [
            {"feature": "bias", "top_minus_all": 2.0},
            {"feature": "bias", "top_minus_all": 1.0},
            {"feature": "rsi", "top_minus_all": -3.0},
            {"feature": "rsi", "top_minus_all": -1.0},
        ]
    )

    out = matrix.summarize_feature_exposure(exposure, max_features=2)

    assert "rsi:-2.000/100%" in out
    assert "bias:+1.500/100%" in out


def test_summarize_drift_importance_filters_low_importance_features():
    imp = pd.DataFrame(
        [
            {"feature": "bias", "importance_share_pct": 5.0, "psi": 0.4, "std_mean_diff": 0.1},
            {"feature": "tiny", "importance_share_pct": 0.5, "psi": 1.0, "std_mean_diff": 1.0},
        ]
    )

    out = matrix.summarize_drift_importance(imp, min_importance_share_pct=2.0)

    assert "bias" in out
    assert "tiny" not in out


def test_build_fold_failure_summary_marks_absolute_failure_with_drift_exposure():
    artifacts = {
        "variant": pd.DataFrame(
            [
                {
                    "fold": 7,
                    "run_label": "seed1",
                    "variant": "candidate",
                    "top_mean_return_pct": -0.5,
                    "top_minus_all_pct": -0.2,
                    "rank_ic_mean": 0.01,
                    "alpha_gate_pass": False,
                    "failure_label": "top_mean_non_positive+top_not_above_pool",
                },
                {
                    "fold": 7,
                    "run_label": "seed2",
                    "variant": "candidate",
                    "top_mean_return_pct": 0.3,
                    "top_minus_all_pct": 0.1,
                    "rank_ic_mean": 0.02,
                    "alpha_gate_pass": True,
                    "failure_label": "pass",
                },
            ]
        ),
        "regime": pd.DataFrame(
            [
                {"fold": 7, "variant": "candidate", "regime_proxy_expost": "broad_up", "alpha_gate_pass": False},
            ]
        ),
        "exante_regime": pd.DataFrame(
            [
                {"fold": 7, "variant": "candidate", "regime_exante": "neutral", "alpha_gate_pass": False},
            ]
        ),
        "exposure": pd.DataFrame(
            [
                {"fold": 7, "variant": "candidate", "feature": "bias", "top_minus_all": 2.0},
            ]
        ),
        "importance": pd.DataFrame(
            [
                {
                    "fold": 7,
                    "variant": "candidate",
                    "feature": "bias",
                    "importance_share_pct": 3.0,
                    "psi": 0.4,
                    "std_mean_diff": 0.1,
                },
            ]
        ),
    }

    out = matrix.build_fold_failure_summary(artifacts, focus_fold=7)
    row = out.iloc[0]

    assert row["failure_matrix_verdict"] == "absolute_failure_with_drifted_exposure"
    assert "top_mean_non_positive:1" in row["failure_reason_counts"]
    assert "broad_up:1" in row["recurring_regime_failures"]
    assert "neutral:1" in row["recurring_exante_regime_failures"]


def test_load_fold_artifacts_reads_related_suffixes(tmp_path):
    prefix = tmp_path / "quant_raw_model_instability_attribution_latest_demo"
    pd.DataFrame(
        [
            {"fold": 7, "variant": "keep", "top_mean_return_pct": 1.0},
            {"fold": 6, "variant": "keep", "top_mean_return_pct": -1.0},
            {"fold": 7, "variant": "drop", "top_mean_return_pct": -1.0},
        ]
    ).to_csv(prefix.with_name(prefix.name + "_variant_summary.csv"), index=False)
    pd.DataFrame(
        [
            {"fold": 7, "variant": "keep", "regime_proxy_expost": "broad_up"},
        ]
    ).to_csv(prefix.with_name(prefix.name + "_regime_summary.csv"), index=False)
    pd.DataFrame(
        [
            {"fold": 7, "variant": "keep", "regime_exante": "neutral"},
        ]
    ).to_csv(prefix.with_name(prefix.name + "_exante_regime_summary.csv"), index=False)

    out = matrix.load_fold_artifacts([prefix], variants=["keep"], focus_fold=7)

    assert out["variant"]["variant"].tolist() == ["keep"]
    assert out["variant"]["run_label"].tolist() == ["demo"]
    assert out["regime"]["regime_proxy_expost"].tolist() == ["broad_up"]
    assert out["exante_regime"]["regime_exante"].tolist() == ["neutral"]


def test_prefix_from_path_strips_known_suffix():
    p = matrix._prefix_from_path(Path("/tmp/x_variant_summary.csv"))

    assert str(p).endswith("/tmp/x")
