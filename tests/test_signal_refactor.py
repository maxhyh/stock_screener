# -*- coding: utf-8 -*-
"""Signal feature-refactor scoring tests."""

from __future__ import annotations

import math

import pandas as pd

from utils.signal_refactor import _compute_redundancy_weights, add_feature_refactor_columns


def test_add_feature_refactor_columns_prefers_stable_signal():
    df = pd.DataFrame(
        [
            {
                "hybrid_score": 0.72,
                "bias": 34.0,
                "z_score": 3.2,
                "rsi": 91.0,
                "vol_ratio": 0.10,
                "pct_chg": 9.4,
            },
            {
                "hybrid_score": 0.72,
                "bias": -6.0,
                "z_score": -1.1,
                "rsi": 57.0,
                "vol_ratio": 1.2,
                "pct_chg": 1.4,
            },
        ]
    )
    out = add_feature_refactor_columns(
        df,
        bias_col="bias",
        z_col="z_score",
        rsi_col="rsi",
        vol_ratio_col="vol_ratio",
        pct_chg_col="pct_chg",
        base_score_col="hybrid_score",
        blend=0.40,
    )
    assert float(out["stability_score"].min()) >= 0.0
    assert float(out["stability_score"].max()) <= 1.0
    assert float(out["refactor_score"].min()) >= 0.0
    assert float(out["refactor_score"].max()) <= 1.0
    assert float(out.loc[1, "stability_score"]) > float(out.loc[0, "stability_score"])
    assert float(out.loc[1, "refactor_score"]) > float(out.loc[0, "refactor_score"])


def test_add_feature_refactor_columns_handles_missing_inputs():
    df = pd.DataFrame([{"hybrid_score": 0.60}, {"hybrid_score": 0.80}])
    out = add_feature_refactor_columns(
        df,
        bias_col="bias",
        z_col="z_score",
        rsi_col="rsi",
        vol_ratio_col="vol_ratio",
        pct_chg_col="pct_chg",
        base_score_col="hybrid_score",
    )
    for col in ["stability_score", "refactor_score", "feature_redundancy"]:
        assert col in out.columns
        assert out[col].isna().sum() == 0
    assert out["refactor_score"].between(0.0, 1.0).all()


def test_compute_redundancy_weights_stays_normalized():
    feat_df = pd.DataFrame(
        {
            "bias_component": [0.20, 0.30, 0.40, 0.50, 0.60],
            "z_component": [0.19, 0.31, 0.39, 0.49, 0.61],
            "rsi_component": [0.80, 0.20, 0.60, 0.30, 0.50],
            "vol_component": [0.10, 0.90, 0.20, 0.80, 0.30],
            "chg_component": [0.55, 0.45, 0.35, 0.65, 0.25],
        }
    )
    weights = _compute_redundancy_weights(feat_df)
    assert set(weights.keys()) == {
        "bias_component",
        "z_component",
        "rsi_component",
        "vol_component",
        "chg_component",
    }
    assert all(v > 0 for v in weights.values())
    assert math.isclose(sum(weights.values()), 1.0, rel_tol=1e-9, abs_tol=1e-9)
