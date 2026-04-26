# -*- coding: utf-8 -*-
"""P2 shadow 诊断测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import scripts.quant_p2_shadow_diagnosis as diag


def test_select_shadow_rows_keeps_best_combo_per_profile_window():
    df = pd.DataFrame(
        [
            {"profile": "a", "window": 60, "objective_score": 1.0, "nav_return_pct": 2.0, "executed_days": 50, "channel": "c1"},
            {"profile": "a", "window": 60, "objective_score": 3.0, "nav_return_pct": 1.0, "executed_days": 48, "channel": "c2"},
            {"profile": "b", "window": 60, "objective_score": 2.0, "nav_return_pct": 1.0, "executed_days": 52, "channel": "c3"},
        ]
    )

    out = diag._select_shadow_rows(df, ["a", "b"], {60})

    assert len(out) == 2
    assert out[out["profile"] == "a"]["channel"].iloc[0] == "c2"


def test_summarize_adv_risk_counts_adv_hits(tmp_path, monkeypatch):
    exec_dir = tmp_path / "execution"
    exec_dir.mkdir()
    pd.DataFrame(
        [
            {"code": "000001", "reasons": "adv_participation", "participation_pct": 12.5},
            {"code": "000002", "reasons": "industry_weight", "participation_pct": 0.0},
        ]
    ).to_csv(exec_dir / "shadow_risk_gates_20260410_run.csv", index=False)
    pd.DataFrame(
        [
            {"code": "000003", "reasons": "adv_participation", "participation_pct": 25.0},
        ]
    ).to_csv(exec_dir / "shadow_risk_gates_20260411_run.csv", index=False)
    monkeypatch.setattr(diag, "EXEC_DIR", exec_dir)

    out = diag._summarize_adv_risk("shadow")

    assert out["adv_blocked_rows"] == 2.0
    assert out["adv_block_days"] == 2.0
    assert out["adv_participation_mean_pct"] == 18.75
    assert out["adv_participation_max_pct"] == 25.0


def test_summarize_industry_concentration_uses_run_positions(tmp_path, monkeypatch):
    exec_dir = tmp_path / "execution"
    exec_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    parquet_file = data_dir / "daily_all_5y.parquet"

    payload = {
        "last_trade_date": "2026-04-10",
        "nav": 2000.0,
        "positions": {
            "000001.SZ": {"qty": 100, "avg_cost": 10.0},
            "000002.SZ": {"qty": 100, "avg_cost": 5.0},
        },
    }
    (exec_dir / "shadow_run_20260410_x.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20260410", "close": 10.0},
            {"ts_code": "000002.SZ", "trade_date": "20260410", "close": 5.0},
        ]
    ).to_parquet(parquet_file, index=False)

    monkeypatch.setattr(diag, "EXEC_DIR", exec_dir)
    monkeypatch.setattr(diag, "PARQUET_FILE", parquet_file)

    industry_map = {"000001": "银行", "000002": "医药"}
    out = diag._summarize_industry_concentration("shadow", industry_map)

    assert out["industry_days"] == 1.0
    assert round(out["mean_top_industry_weight_pct"], 2) == 66.67
    assert round(out["mean_top_industry_invested_weight_pct"], 2) == 66.67
    assert round(out["mean_top_industry_nav_weight_pct"], 2) == 50.00
    assert round(out["mean_industry_hhi"], 4) == round((2 / 3) ** 2 + (1 / 3) ** 2, 4)
    assert round(out["mean_industry_nav_hhi"], 4) == round(0.5**2 + 0.25**2, 4)


def test_load_summary_frames_supports_multiple_files(tmp_path):
    f1 = tmp_path / "a.csv"
    f2 = tmp_path / "b.csv"
    pd.DataFrame([{"profile": "a", "window": 20, "objective_score": 1.0, "channel": "c1"}]).to_csv(f1, index=False)
    pd.DataFrame([{"profile": "b", "window": 20, "objective_score": 2.0, "channel": "c2"}]).to_csv(f2, index=False)

    df, files = diag._load_summary_frames(f"{f1},{f2}", ["a", "b"])

    assert len(df) == 2
    assert set(df["profile"]) == {"a", "b"}
    assert files == [str(f1.resolve()), str(f2.resolve())]
