# -*- coding: utf-8 -*-
"""P2 halt cluster attribution tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import scripts.quant_p2_halt_cluster_attribution as attr


def test_classify_attribution_labels_major_failure_modes():
    assert attr.classify_attribution({"execution_state": "empty_after_universe_filter"}) == "universe_filter_empty"
    assert attr.classify_attribution({"execution_state": "empty_signal_raw"}) == "empty_signal_raw"
    assert attr.classify_attribution({"broker_exit_not_tradable_orders": 1}) == "sell_trap"
    assert (
        attr.classify_attribution({"execution_state": "executable_pool_halt", "risk_adv_hit": 5, "risk_style_hit": 1})
        == "adv_capacity_collapse"
    )
    assert (
        attr.classify_attribution({"execution_state": "executable_pool_halt", "risk_style_hit": 4, "risk_adv_hit": 1})
        == "style_gate_collapse"
    )
    assert (
        attr.classify_attribution({"execution_state": "executable_pool_halt", "risk_entry_not_tradable_hit": 2})
        == "tradability_collapse"
    )


def test_build_attribution_reads_ledger_and_risk_file(monkeypatch, tmp_path: Path):
    exec_dir = tmp_path / "execution"
    exec_dir.mkdir()
    monkeypatch.setattr(attr, "EXEC_DIR", exec_dir)

    channel = "paper_replay_quality_regime_60_g1_test"
    run_id = "run1"
    summary = pd.DataFrame(
        {
            "profile": ["quality_regime"],
            "window": [60],
            "channel": [channel],
            "objective_score": [1.0],
            "nav_return_pct": [0.0],
            "executed_days": [1],
        }
    )
    ledger = pd.DataFrame(
        {
            "run_id": [run_id],
            "signal_date": ["2026-03-19"],
            "trade_date": ["2026-03-20"],
            "execution_state": ["empty_after_universe_filter"],
            "empty_signal_raw_rows": [10],
            "empty_signal_post_filter_rows": [0],
            "empty_signal_filtered_bj9_rows": [10],
            "empty_signal_filtered_st_rows": [0],
            "risk_input_count": [0],
            "risk_kept_count": [0],
            "risk_blocked_count": [0],
            "broker_entry_not_tradable_orders": [0],
            "broker_exit_not_tradable_orders": [0],
        }
    )
    ledger.to_csv(exec_dir / f"{channel}_ledger.csv", index=False)
    pd.DataFrame({"reasons": ["adv_participation", "style_size"]}).to_csv(
        exec_dir / f"{channel}_risk_gates_20260320_{run_id}.csv",
        index=False,
    )

    out = attr.build_attribution(summary, {"20260319"}, {60})

    assert len(out) == 1
    row = out.iloc[0]
    assert row["attribution_label"] == "universe_filter_empty"
    assert int(row["raw_candidate_count"]) == 10
    assert int(row["filtered_bj9_rows"]) == 10
    assert int(row["risk_adv_hit"]) == 1
