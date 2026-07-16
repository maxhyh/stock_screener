# -*- coding: utf-8 -*-
"""Raw model seed/sample stability report tests."""

from __future__ import annotations

import pandas as pd

import scripts.quant_raw_model_seed_stability_report as report


def test_build_stability_summary_passes_only_when_all_runs_pass():
    details = pd.DataFrame(
        [
            {
                "run_label": "seed1",
                "variant": "rank_norm",
                "variant_model_gate_pass": True,
                "fold_pass_rate_pct": 57.0,
                "critical_fold_pass": True,
                "mean_top_return_pct": 1.0,
                "mean_top_minus_all_pct": 0.2,
                "mean_rank_ic": 0.03,
                "fold7_top_mean_return_pct": 0.4,
                "fold7_top_minus_all_pct": 0.2,
            },
            {
                "run_label": "seed2",
                "variant": "rank_norm",
                "variant_model_gate_pass": True,
                "fold_pass_rate_pct": 71.0,
                "critical_fold_pass": True,
                "mean_top_return_pct": 0.5,
                "mean_top_minus_all_pct": 0.1,
                "mean_rank_ic": 0.02,
                "fold7_top_mean_return_pct": 0.1,
                "fold7_top_minus_all_pct": 0.1,
            },
        ]
    )

    out = report.build_stability_summary(details)

    assert out.iloc[0]["stability_verdict"] == "sample_stability_pass"
    assert out.iloc[0]["pass_run_count"] == 2


def test_build_stability_summary_rejects_critical_fold_unstable():
    details = pd.DataFrame(
        [
            {
                "run_label": "seed1",
                "variant": "drop_drift",
                "variant_model_gate_pass": True,
                "fold_pass_rate_pct": 57.0,
                "critical_fold_pass": True,
                "mean_top_return_pct": 1.0,
                "mean_top_minus_all_pct": 0.2,
                "mean_rank_ic": 0.03,
                "fold7_top_mean_return_pct": 0.4,
                "fold7_top_minus_all_pct": 0.2,
            },
            {
                "run_label": "date_stratified",
                "variant": "drop_drift",
                "variant_model_gate_pass": False,
                "fold_pass_rate_pct": 42.0,
                "critical_fold_pass": False,
                "mean_top_return_pct": 0.7,
                "mean_top_minus_all_pct": -0.2,
                "mean_rank_ic": 0.04,
                "fold7_top_mean_return_pct": -0.5,
                "fold7_top_minus_all_pct": -0.1,
            },
        ]
    )

    out = report.build_stability_summary(details)
    row = out.iloc[0]

    assert row["stability_verdict"] == "critical_fold_unstable"
    assert row["failed_run_labels"] == "date_stratified"


def test_build_stability_summary_marks_insufficient_runs():
    details = pd.DataFrame(
        [
            {
                "run_label": "seed1",
                "variant": "one_run_only",
                "variant_model_gate_pass": True,
                "fold_pass_rate_pct": 71.0,
                "critical_fold_pass": True,
                "mean_top_return_pct": 1.0,
                "mean_top_minus_all_pct": 0.2,
                "mean_rank_ic": 0.03,
                "fold7_top_mean_return_pct": 0.4,
                "fold7_top_minus_all_pct": 0.2,
            }
        ]
    )

    out = report.build_stability_summary(details, min_run_count=2)

    assert out.iloc[0]["stability_verdict"] == "insufficient_runs"


def test_load_run_details_reads_family_summary_and_filters_variants(tmp_path):
    path = tmp_path / "quant_raw_model_instability_attribution_latest_demo_variant_family_summary.csv"
    pd.DataFrame(
        [
            {
                "variant": "keep_me",
                "variant_family_verdict": "variant_model_gate_pass",
                "fold_count": 7,
                "pass_fold_count": 5,
                "fold_pass_rate_pct": 71.4,
                "critical_fold_pass": True,
                "mean_top_return_pct": 1.0,
                "mean_top_minus_all_pct": 0.2,
                "mean_rank_ic": 0.03,
            },
            {
                "variant": "drop_me",
                "variant_family_verdict": "critical_fold_failed",
                "fold_count": 7,
                "pass_fold_count": 2,
                "critical_fold_pass": False,
            },
        ]
    ).to_csv(path, index=False)

    out = report.load_run_details([path], variants=["keep_me"])

    assert out["variant"].tolist() == ["keep_me"]
    assert out.iloc[0]["run_label"] == "demo"
    assert bool(out.iloc[0]["variant_model_gate_pass"]) is True
