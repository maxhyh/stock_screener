# -*- coding: utf-8 -*-
"""P2 smoke failure diagnosis tests."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import scripts.quant_p2_smoke_failure_diagnosis as diag


def _write_ledger(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def test_build_relative_detail_aligns_same_signal_dates(tmp_path: Path, monkeypatch):
    exec_dir = tmp_path / "execution"
    exec_dir.mkdir()
    monkeypatch.setattr(diag, "EXEC_DIR", exec_dir)

    _write_ledger(
        exec_dir / "main_ledger.csv",
        [
            {
                "signal_date": "2026-01-01",
                "trade_date": "2026-01-02",
                "nav_pre": 100.0,
                "nav_post": 101.0,
                "target_weight_sum": 0.50,
                "broker_exit_not_tradable_orders": 0,
            },
            {
                "signal_date": "2026-01-02",
                "trade_date": "2026-01-03",
                "nav_pre": 101.0,
                "nav_post": 102.0,
                "target_weight_sum": 0.50,
                "broker_exit_not_tradable_orders": 0,
            },
        ],
    )
    _write_ledger(
        exec_dir / "candidate_ledger.csv",
        [
            {
                "signal_date": "2026-01-01",
                "trade_date": "2026-01-02",
                "nav_pre": 100.0,
                "nav_post": 99.0,
                "target_weight_sum": 0.40,
                "broker_exit_not_tradable_orders": 1,
            },
            {
                "signal_date": "2026-01-02",
                "trade_date": "2026-01-03",
                "nav_pre": 99.0,
                "nav_post": 99.99,
                "target_weight_sum": 0.40,
                "broker_exit_not_tradable_orders": 0,
            },
        ],
    )
    summary = pd.DataFrame(
        [
            {"profile": "main", "window": 60, "channel": "main"},
            {"profile": "candidate", "window": 60, "channel": "candidate"},
        ]
    )

    out = diag.build_relative_detail(summary, main_profile="main", candidate_profile="candidate", window=60)

    assert len(out) == 2
    assert out["signal_date"].tolist() == ["2026-01-01", "2026-01-02"]
    assert out.iloc[0]["relative_return_gap_pct"] < 0
    assert out.iloc[0]["exit_block_delta"] == 1


def test_build_failure_summary_labels_score_alpha_not_executed_with_exit_blocks(tmp_path: Path, monkeypatch):
    backtest_dir = tmp_path / "backtest"
    exec_dir = tmp_path / "execution"
    backtest_dir.mkdir()
    exec_dir.mkdir()
    monkeypatch.setattr(diag, "BACKTEST_DIR", backtest_dir)
    monkeypatch.setattr(diag, "EXEC_DIR", exec_dir)

    _write_ledger(
        exec_dir / "main_ledger.csv",
        [
            {
                "signal_date": "2026-01-01",
                "trade_date": "2026-01-02",
                "nav_pre": 100.0,
                "nav_post": 101.0,
                "target_weight_sum": 0.50,
                "broker_exit_not_tradable_orders": 0,
                "broker_entry_not_tradable_orders": 0,
            }
        ],
    )
    _write_ledger(
        exec_dir / "candidate_ledger.csv",
        [
            {
                "signal_date": "2026-01-01",
                "trade_date": "2026-01-02",
                "nav_pre": 100.0,
                "nav_post": 98.0,
                "target_weight_sum": 0.40,
                "broker_exit_not_tradable_orders": 2,
                "broker_entry_not_tradable_orders": 0,
            }
        ],
    )
    score_json = backtest_dir / "quant_score_alpha_diagnosis_latest_candidate.json"
    score_json.write_text(
        json.dumps(
            {
                "alpha_quality_gate": {
                    "pass": True,
                    "reasons": [],
                    "evaluated": [
                        {
                            "score_col": "target_weight",
                            "top_days": 10,
                            "top_mean_forward_return_pct": 1.0,
                            "all_mean_forward_return_pct": 0.2,
                            "top_minus_all_pct": 0.8,
                            "top_minus_bottom_pct": 1.3,
                            "rank_ic_mean": 0.1,
                            "pass": True,
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    precheck = pd.DataFrame(
        [
            {
                "profile": "candidate",
                "decision": "skip",
                "reason": "p2_smoke_nav_below_main,p2_smoke_exit_blocks_worse_than_main",
            }
        ]
    )
    summary = pd.DataFrame(
        [
            {
                "profile": "main",
                "window": 60,
                "channel": "main",
                "nav_return_pct": 1.0,
                "max_drawdown_pct": -1.0,
                "target_weight_sum_mean": 0.50,
                "broker_exit_not_tradable_orders": 0,
                "broker_entry_not_tradable_orders": 0,
            },
            {
                "profile": "candidate",
                "window": 60,
                "channel": "candidate",
                "nav_return_pct": -2.0,
                "max_drawdown_pct": -3.0,
                "target_weight_sum_mean": 0.40,
                "broker_exit_not_tradable_orders": 2,
                "broker_entry_not_tradable_orders": 0,
            },
        ]
    )

    out, detail = diag.build_failure_summary(
        summary,
        main_profile="main",
        candidate_profiles=["candidate"],
        window=60,
        precheck_df=precheck,
    )

    assert len(out) == 1
    row = out.iloc[0]
    assert bool(row["score_alpha_gate_pass"]) is True
    assert row["score_alpha_best_col"] == "target_weight"
    assert row["failure_label"] == "sell_trap_or_exit_block"
    assert row["p2_smoke_precheck_decision"] == "skip"
    assert row["broker_exit_block_delta_vs_main"] == 2
    assert len(detail) == 1


def test_build_failure_summary_labels_cash_drag_when_underdeployed(tmp_path: Path, monkeypatch):
    exec_dir = tmp_path / "execution"
    exec_dir.mkdir()
    monkeypatch.setattr(diag, "EXEC_DIR", exec_dir)

    _write_ledger(
        exec_dir / "main_ledger.csv",
        [{"signal_date": "2026-01-01", "trade_date": "2026-01-02", "nav_pre": 100.0, "nav_post": 101.0}],
    )
    _write_ledger(
        exec_dir / "candidate_ledger.csv",
        [{"signal_date": "2026-01-01", "trade_date": "2026-01-02", "nav_pre": 100.0, "nav_post": 99.0}],
    )
    summary = pd.DataFrame(
        [
            {
                "profile": "main",
                "window": 60,
                "channel": "main",
                "nav_return_pct": 1.0,
                "max_drawdown_pct": -1.0,
                "target_weight_sum_mean": 0.50,
            },
            {
                "profile": "candidate",
                "window": 60,
                "channel": "candidate",
                "nav_return_pct": -1.0,
                "max_drawdown_pct": -1.0,
                "target_weight_sum_mean": 0.20,
            },
        ]
    )

    out, _ = diag.build_failure_summary(
        summary,
        main_profile="main",
        candidate_profiles=["candidate"],
        window=60,
        precheck_df=pd.DataFrame(),
    )

    assert out.iloc[0]["failure_label"] == "cash_drag_or_underdeployment"
