# -*- coding: utf-8 -*-
"""Raw model residual treatment probe tests."""

from __future__ import annotations

import pandas as pd

import scripts.quant_raw_model_residual_treatment_probe as probe


def test_fold2_absolute_loss_maps_to_weak_market_calibration():
    row = {
        "focus_fold": 2,
        "variant": "candidate",
        "residual_failure_label": "absolute_loss_but_beats_pool",
        "candidate_top_mean_return_pct": -0.95,
        "candidate_top_minus_all_pct": 0.96,
        "candidate_top_minus_bottom_pct": 4.5,
        "candidate_rank_ic_mean": 0.07,
        "failed_exante_regimes": (
            "neutral:top=-3.36,spread=-0.52,days=21,absolute_and_relative_failure;"
            "risk_on:top=-6.31,spread=-0.21,days=5,absolute_and_relative_failure"
        ),
        "top_feature_exposures": "pv_corr_20:-0.301;rs_20d:-0.280;mom_20:-0.273;bias:-0.254",
        "drifted_important_features": "",
    }

    out = probe._fold_treatment(row)

    assert out["treatment_family"] == "weak_market_absolute_return_calibration"
    assert out["primary_failure_mode"] == "relative_rank_defense_not_absolute_alpha"
    assert out["hard_block_reason"] == "top_bucket_absolute_return_negative"
    assert out["absolute_loss_gap_pct"] == 0.95
    assert out["relative_defense_pct"] == 0.96
    assert out["implicated_regimes"] == "neutral,risk_on"
    assert "mom_20" in out["implicated_features"]
    assert "top_mean_return_pct > 0" in out["fold_specific_gate_to_clear"]


def test_fold6_pool_lag_with_pos52w_drift_maps_to_beta_capture_repair():
    row = {
        "focus_fold": 6,
        "variant": "candidate",
        "residual_failure_label": "positive_top_but_pool_and_bottom_lag",
        "candidate_top_mean_return_pct": 1.09,
        "candidate_top_minus_all_pct": -0.24,
        "candidate_top_minus_bottom_pct": -0.83,
        "candidate_rank_ic_mean": 0.06,
        "failed_exante_regimes": (
            "neutral:top=+1.02,spread=-0.30,days=67,positive_top_but_pool_and_bottom_lag;"
            "risk_on:top=-2.55,spread=-0.25,days=5,absolute_and_relative_failure"
        ),
        "top_feature_exposures": "pos_52w_cs:-0.178;pos_52w:-0.178;atr_percent:-0.148",
        "drifted_important_features": "pos_52w:share=9.6,psi=0.64,std=0.73",
    }

    out = probe._fold_treatment(row)

    assert out["treatment_family"] == "beta_capture_pos52w_drift_repair"
    assert out["primary_failure_mode"] == "market_beta_opportunity_capture_gap"
    assert out["hard_block_reason"] == "top_bucket_misses_available_market_opportunity"
    assert out["pool_lag_pct"] == 0.24
    assert out["bottom_lag_pct"] == 0.83
    assert out["implicated_regimes"] == "neutral,risk_on"
    assert out["implicated_features"] == "pos_52w"
    assert "top_minus_all_pct >= 0" in out["fold_specific_gate_to_clear"]


def test_build_treatment_probe_blocks_profile_and_p2():
    residual_summary = pd.DataFrame(
        [
            {
                "focus_fold": 2,
                "variant": "candidate",
                "residual_failure_label": "absolute_loss_but_beats_pool",
                "candidate_top_mean_return_pct": -0.95,
                "candidate_top_minus_all_pct": 0.96,
                "candidate_top_minus_bottom_pct": 4.5,
                "candidate_rank_ic_mean": 0.07,
                "failed_exante_regimes": "neutral:top=-3.36,spread=-0.52,days=21,absolute_and_relative_failure",
                "top_feature_exposures": "mom_20:-0.273",
                "drifted_important_features": "",
            },
            {
                "focus_fold": 6,
                "variant": "candidate",
                "residual_failure_label": "positive_top_but_pool_and_bottom_lag",
                "candidate_top_mean_return_pct": 1.09,
                "candidate_top_minus_all_pct": -0.24,
                "candidate_top_minus_bottom_pct": -0.83,
                "candidate_rank_ic_mean": 0.06,
                "failed_exante_regimes": "neutral:top=+1.02,spread=-0.30,days=67,positive_top_but_pool_and_bottom_lag",
                "top_feature_exposures": "pos_52w:-0.178",
                "drifted_important_features": "pos_52w:share=9.6,psi=0.64,std=0.73",
            },
        ]
    )

    summary, payload = probe.build_treatment_probe(residual_summary)

    assert payload["overall_verdict"] == "residual_treatment_hypotheses_only_no_profile_p2"
    assert payload["allow_profile_build"] is False
    assert payload["allow_p2"] is False
    assert payload["failing_folds"] == "2,6"
    assert summary["treatment_family"].tolist() == [
        "weak_market_absolute_return_calibration",
        "beta_capture_pos52w_drift_repair",
    ]
