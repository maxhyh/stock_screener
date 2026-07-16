# -*- coding: utf-8 -*-
"""Raw ML horizon diagnosis tests."""

from __future__ import annotations

import json

import pandas as pd

import scripts.quant_raw_ml_horizon_diagnosis as diag


def test_attach_open_to_open_returns_uses_next_open_entry_and_horizon_exit():
    raw = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "code": ["000001.SZ", "000001.SZ"],
            "ml_score": [2.0, 1.0],
        }
    )
    bars = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
            "code": ["000001.SZ"] * 4,
            "open": [10.0, 11.0, 12.1, 13.31],
        }
    )

    out = diag.attach_open_to_open_returns(raw, bars, [1])

    assert out.iloc[0]["forward_return_h1"] == (12.1 / 11.0 - 1.0)
    assert out.iloc[1]["forward_return_h1"] == (13.31 / 12.1 - 1.0)


def test_horizon_verdict_detects_non_trained_horizon_match():
    summary = pd.DataFrame(
        [
            {
                "horizon": 1,
                "score_direction": "desc",
                "horizon_alpha_gate_pass": False,
                "rank_ic_mean": -0.1,
                "top_mean_forward_return_pct": -1.0,
                "top_minus_bottom_pct": -2.0,
            },
            {
                "horizon": 3,
                "score_direction": "desc",
                "horizon_alpha_gate_pass": True,
                "rank_ic_mean": 0.1,
                "top_mean_forward_return_pct": 1.0,
                "top_minus_bottom_pct": 2.0,
            },
            {
                "horizon": 1,
                "score_direction": "asc",
                "horizon_alpha_gate_pass": False,
                "rank_ic_mean": -0.1,
                "top_mean_forward_return_pct": -1.0,
                "top_minus_bottom_pct": -2.0,
            },
        ]
    )

    out = diag.build_horizon_verdict(summary, {"label_horizon": 1, "label_mode": "open_to_open"})

    assert out["overall_verdict"] == "horizon_mismatch_possible"
    assert out["desc_pass_horizons"] == "3"


def test_horizon_verdict_detects_score_sign_inversion():
    summary = pd.DataFrame(
        [
            {
                "horizon": 3,
                "score_direction": "desc",
                "horizon_alpha_gate_pass": False,
                "rank_ic_mean": -0.1,
                "top_mean_forward_return_pct": -1.0,
                "top_minus_bottom_pct": -2.0,
            },
            {
                "horizon": 3,
                "score_direction": "asc",
                "horizon_alpha_gate_pass": True,
                "rank_ic_mean": 0.1,
                "top_mean_forward_return_pct": 1.0,
                "top_minus_bottom_pct": 2.0,
            },
        ]
    )

    out = diag.build_horizon_verdict(summary, {"label_horizon": 3, "label_mode": "open_to_open"})

    assert out["overall_verdict"] == "score_sign_inversion_possible"
    assert out["asc_pass_horizons"] == "3"


def test_horizon_verdict_does_not_overstate_short_horizon_inversion_for_profile_horizon():
    summary = pd.DataFrame(
        [
            {
                "horizon": 1,
                "score_direction": "asc",
                "horizon_alpha_gate_pass": True,
                "rank_ic_mean": 0.05,
                "top_mean_forward_return_pct": 0.2,
                "top_minus_bottom_pct": 0.1,
            },
            {
                "horizon": 10,
                "score_direction": "asc",
                "horizon_alpha_gate_pass": False,
                "rank_ic_mean": 0.05,
                "top_mean_forward_return_pct": 0.2,
                "top_minus_bottom_pct": 1.0,
            },
            {
                "horizon": 10,
                "score_direction": "desc",
                "horizon_alpha_gate_pass": False,
                "rank_ic_mean": -0.05,
                "top_mean_forward_return_pct": -1.0,
                "top_minus_bottom_pct": -1.0,
            },
        ]
    )

    out = diag.build_horizon_verdict(
        summary,
        {"label_horizon": 3, "label_mode": "open_to_open"},
        {"profile": "candidate", "profile_holding_days": 10},
    )

    assert out["overall_verdict"] == "raw_ml_alpha_failed_profile_horizons"
    assert out["asc_pass_horizons"] == "1"
    assert out["asc_relevant_horizon_pass"] is False


def test_horizon_verdict_marks_all_horizons_failed():
    summary = pd.DataFrame(
        [
            {
                "horizon": 3,
                "score_direction": "desc",
                "horizon_alpha_gate_pass": False,
                "rank_ic_mean": -0.1,
                "top_mean_forward_return_pct": -1.0,
                "top_minus_bottom_pct": -2.0,
            },
            {
                "horizon": 3,
                "score_direction": "asc",
                "horizon_alpha_gate_pass": False,
                "rank_ic_mean": -0.1,
                "top_mean_forward_return_pct": -1.0,
                "top_minus_bottom_pct": -2.0,
            },
        ]
    )

    out = diag.build_horizon_verdict(summary, {"label_horizon": 3, "label_mode": "open_to_open"})

    assert out["overall_verdict"] == "raw_ml_alpha_failed_all_horizons"


def test_profile_holding_days_metadata_reports_model_profile_mismatch(tmp_path):
    cfg = tmp_path / "profiles.json"
    cfg.write_text(
        json.dumps(
            {
                "profiles": {
                    "candidate": {
                        "holding_days": 10,
                        "top_n": 18,
                        "target_score_col": "target_blend_score",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    summary = pd.DataFrame(
        [
            {
                "horizon": 3,
                "score_direction": "desc",
                "horizon_alpha_gate_pass": True,
                "rank_ic_mean": 0.1,
                "top_mean_forward_return_pct": 1.0,
                "top_minus_bottom_pct": 2.0,
            }
        ]
    )

    profile_meta = diag.load_profile_metadata("candidate", str(cfg))
    out = diag.build_horizon_verdict(
        summary,
        {"label_horizon": 3, "label_mode": "open_to_open"},
        profile_meta,
    )

    assert profile_meta["profile_holding_days"] == 10
    assert profile_meta["profile_target_score_col"] == "target_blend_score"
    assert out["profile_holding_days"] == 10
    assert out["model_profile_horizon_mismatch"] is True
