# -*- coding: utf-8 -*-
"""Anti-overfit pipeline helper tests."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

import scripts.quant_anti_overfit_pipeline as pipe


def test_build_stable_table_filters_by_good_ratio_and_windows():
    wf_df = pd.DataFrame(
        [
            {
                "window_id": 1,
                "top_n": 10,
                "holding_days": 5,
                "max_single_pos": 0.05,
                "use_regime_position": 0,
                "test_excess_annual_return_pct": 8.0,
                "test_mdd_pct": -12.0,
                "test_annual_return_pct": 20.0,
                "test_sharpe": 1.2,
                "test_beat_rate_pct": 60.0,
            },
            {
                "window_id": 2,
                "top_n": 10,
                "holding_days": 5,
                "max_single_pos": 0.05,
                "use_regime_position": 0,
                "test_excess_annual_return_pct": 5.0,
                "test_mdd_pct": -14.0,
                "test_annual_return_pct": 16.0,
                "test_sharpe": 1.0,
                "test_beat_rate_pct": 55.0,
            },
            {
                "window_id": 3,
                "top_n": 12,
                "holding_days": 6,
                "max_single_pos": 0.06,
                "use_regime_position": 1,
                "test_excess_annual_return_pct": -3.0,
                "test_mdd_pct": -20.0,
                "test_annual_return_pct": 4.0,
                "test_sharpe": 0.2,
                "test_beat_rate_pct": 40.0,
            },
            {
                "window_id": 4,
                "top_n": 12,
                "holding_days": 6,
                "max_single_pos": 0.06,
                "use_regime_position": 1,
                "test_excess_annual_return_pct": -1.0,
                "test_mdd_pct": -19.0,
                "test_annual_return_pct": 5.0,
                "test_sharpe": 0.3,
                "test_beat_rate_pct": 42.0,
            },
        ]
    )
    stable = pipe._build_stable_table(
        wf_df,
        min_windows=2,
        min_good_ratio=0.5,
        min_test_excess_annual=0.0,
        max_test_mdd=-18.0,
    )
    assert len(stable) == 1
    assert int(stable.iloc[0]["top_n"]) == 10
    assert float(stable.iloc[0]["good_ratio"]) == 1.0


def test_derive_narrow_grid_uses_fallback_when_empty():
    out = pipe._derive_narrow_grid(
        pd.DataFrame(),
        fallback_topn=[8, 10],
        fallback_hold=[5, 6],
        fallback_maxpos=[0.05, 0.06],
        top_k=3,
    )
    assert out["used_fallback"] is True
    assert out["topn_grid"] == [8, 10]
    assert out["hold_grid"] == [5, 6]
    assert out["maxpos_grid"] == [0.05, 0.06]


def test_append_signal_refactor_flags_contains_expected_cli():
    args = SimpleNamespace(
        disable_signal_quality_gate=True,
        min_signal_quality=0.41,
        ml_quality_blend=0.78,
        max_abs_pct_chg=8.9,
        disable_feature_refactor=True,
        stability_blend=0.33,
        disable_feature_refactor_gate=True,
        min_refactor_score=0.57,
    )
    cmd = pipe._append_signal_refactor_flags(["python", "scripts/quant_walk_forward.py"], args)
    text = " ".join(cmd)
    assert "--disable-signal-quality-gate" in text
    assert "--min-signal-quality 0.4100" in text
    assert "--ml-quality-blend 0.7800" in text
    assert "--max-abs-pct-chg 8.9000" in text
    assert "--disable-feature-refactor" in text
    assert "--stability-blend 0.3300" in text
    assert "--disable-feature-refactor-gate" in text
    assert "--min-refactor-score 0.5700" in text


def test_main_forwards_signal_refactor_flags_to_wf_and_opt(monkeypatch, tmp_path):
    wf_file = tmp_path / "quant_walk_forward_windows_20990101_000000.csv"
    pd.DataFrame(
        [
            {
                "window_id": 1,
                "top_n": 10,
                "holding_days": 5,
                "max_single_pos": 0.05,
                "use_regime_position": 0,
                "test_excess_annual_return_pct": 8.0,
                "test_mdd_pct": -10.0,
                "test_annual_return_pct": 15.0,
                "test_sharpe": 1.1,
                "test_beat_rate_pct": 60.0,
            }
        ]
    ).to_csv(wf_file, index=False)

    run_cmds: list[list[str]] = []
    monkeypatch.setattr(pipe, "OUTPUT_BACKTEST_DIR", tmp_path)
    monkeypatch.setattr(pipe, "_run_cmd", lambda cmd: run_cmds.append(list(cmd)))
    monkeypatch.setattr(pipe, "_latest_file", lambda pattern: wf_file)
    monkeypatch.setattr(pipe, "_latest_daily_date_str", lambda: "20260410")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "quant_anti_overfit_pipeline.py",
            "--start",
            "2026-01-01",
            "--end",
            "2026-03-20",
            "--wf-topn-grid",
            "10",
            "--wf-hold-grid",
            "5",
            "--wf-maxpos-grid",
            "0.05",
            "--disable-signal-quality-gate",
            "--min-signal-quality",
            "0.42",
            "--ml-quality-blend",
            "0.76",
            "--max-abs-pct-chg",
            "8.7",
            "--disable-feature-refactor",
            "--stability-blend",
            "0.34",
            "--disable-feature-refactor-gate",
            "--min-refactor-score",
            "0.58",
        ],
    )

    rc = pipe.main()
    assert rc == 0
    assert len(run_cmds) == 2
    wf_cmd = " ".join(run_cmds[0])
    opt_cmd = " ".join(run_cmds[1])
    for text in [wf_cmd, opt_cmd]:
        assert "--disable-signal-quality-gate" in text
        assert "--min-signal-quality 0.4200" in text
        assert "--ml-quality-blend 0.7600" in text
        assert "--max-abs-pct-chg 8.7000" in text
        assert "--disable-feature-refactor" in text
        assert "--stability-blend 0.3400" in text
        assert "--disable-feature-refactor-gate" in text
        assert "--min-refactor-score 0.5800" in text
