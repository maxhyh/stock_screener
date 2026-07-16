# -*- coding: utf-8 -*-
"""Executable-pool bottleneck diagnosis tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import scripts.quant_executable_pool_bottleneck_diagnosis as diag


def test_summarize_risk_rows_counts_single_and_overlap_reasons():
    risk_df = pd.DataFrame(
        {
            "code": ["000001", "000002", "000003", "000004"],
            "target_weight": [0.02, 0.03, 0.04, 0.05],
            "reasons": [
                "adv_participation",
                "style_size_exposure,style_beta_exposure",
                "adv_participation,style_size_exposure",
                "entry_not_tradable",
            ],
        }
    )

    out = diag.summarize_risk_rows(risk_df)

    assert out["risk_file_rows"] == 4
    assert out["risk_adv_hit_rows"] == 2
    assert out["risk_style_hit_rows"] == 2
    assert out["risk_tradability_hit_rows"] == 1
    assert out["risk_adv_only_rows"] == 1
    assert out["risk_style_only_rows"] == 1
    assert out["risk_tradability_only_rows"] == 1
    assert out["risk_multi_reason_rows"] == 1
    assert out["risk_recoverable_without_adv_style_rows"] == 3
    assert out["risk_style_size_hit_rows"] == 2
    assert out["risk_style_beta_hit_rows"] == 1


def test_build_diagnosis_joins_ledger_risk_and_daily_files(tmp_path: Path, monkeypatch):
    exec_dir = tmp_path / "execution"
    daily_root = tmp_path / "daily_profiles"
    exec_dir.mkdir()
    (daily_root / "candidate").mkdir(parents=True)
    monkeypatch.setattr(diag, "EXEC_DIR", exec_dir)
    monkeypatch.setattr(diag, "DAILY_PROFILE_DIR", daily_root)

    channel = "paper_replay_candidate_10_g1_test"
    run_id = "run123"
    pd.DataFrame(
        [
            {
                "signal_date": "2026-04-03",
                "trade_date": "2026-04-07",
                "run_id": run_id,
                "execution_state": "executable_pool_halt",
                "executable_pool_halt": 1,
                "executable_pool_input_count": 2,
                "executable_pool_kept_count": 0,
                "executable_pool_blocked_count": 4,
                "target_weight_sum": 0.0,
                "broker_exit_not_tradable_orders": 0,
            }
        ]
    ).to_csv(exec_dir / f"{channel}_ledger.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        {
            "code": ["000001", "000002", "000003"],
            "target_weight": [0.02, 0.03, 0.04],
            "reasons": ["adv_participation", "style_size_exposure", "adv_participation,style_size_exposure"],
        }
    ).to_csv(exec_dir / f"{channel}_risk_gates_20260407_{run_id}.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        {
            "代码": ["000001", "000002", "000003", "000004"],
            "target_weight": [0.02, 0.03, 0.00, 0.00],
            "reserve_candidate": [0, 0, 1, 1],
            "constraint_reason": ["ok", "ok", "zero_weight", "reserve_weight_clip"],
            "participation_pct": [1.0, 2.0, 0.0, 0.0],
        }
    ).to_csv(daily_root / "candidate" / "daily_20260403.csv", index=False, encoding="utf-8-sig")
    summary = pd.DataFrame(
        [
            {
                "profile": "candidate",
                "window": 10,
                "channel": channel,
                "objective_score": 1.0,
                "nav_return_pct": 0.0,
                "executed_days": 10,
            }
        ]
    )

    out = diag.build_diagnosis(summary, {"20260403", "20260407"}, {10})

    assert len(out) == 1
    row = out.iloc[0]
    assert int(row["daily_rows"]) == 4
    assert int(row["daily_reserve_rows"]) == 2
    assert float(row["daily_target_weight_sum"]) == 0.05
    assert int(row["daily_reserve_weight_clip_rows"]) == 1
    assert int(row["risk_adv_hit_rows"]) == 2
    assert int(row["risk_style_hit_rows"]) == 2
    assert int(row["risk_recoverable_without_adv_style_rows"]) == 3
    assert row["bottleneck_label"] == "adv_style_overlap_collapse"
