# -*- coding: utf-8 -*-
"""Alpha-to-execution attribution diagnostics tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import scripts.quant_alpha_execution_attribution as attrib


def test_build_attribution_from_daily_recommendations(tmp_path: Path, monkeypatch):
    daily_dir = tmp_path / "output"
    daily_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    exec_dir = tmp_path / "execution"
    exec_dir.mkdir()

    pd.DataFrame(
        [
            {"ts_code": "000001", "industry": "银行"},
            {"ts_code": "000002", "industry": "医药"},
            {"ts_code": "000003", "industry": "电子"},
        ]
    ).to_csv(data_dir / "stock_info.csv", index=False)

    pd.DataFrame(
        [
            {"日期": "2026-01-01", "市场状态": "正常", "排名": 1, "代码": "000001", "ML评分": 0.9, "质量分": 0.8, "重构分": 0.7, "建议持有天数": 1},
            {"日期": "2026-01-01", "市场状态": "正常", "排名": 2, "代码": "000002", "ML评分": 0.5, "质量分": 0.6, "重构分": 0.4, "建议持有天数": 1},
            {"日期": "2026-01-01", "市场状态": "正常", "排名": 3, "代码": "000003", "ML评分": 0.1, "质量分": 0.2, "重构分": 0.3, "建议持有天数": 1},
        ]
    ).to_csv(daily_dir / "daily_20260101.csv", index=False)
    pd.DataFrame(
        [
            {"日期": "2026-01-02", "市场状态": "震荡", "排名": 1, "代码": "000001", "ML评分": 0.8, "质量分": 0.7, "重构分": 0.6, "建议持有天数": 1},
            {"日期": "2026-01-02", "市场状态": "震荡", "排名": 2, "代码": "000002", "ML评分": 0.4, "质量分": 0.5, "重构分": 0.4, "建议持有天数": 1},
            {"日期": "2026-01-02", "市场状态": "震荡", "排名": 3, "代码": "000003", "ML评分": 0.2, "质量分": 0.3, "重构分": 0.2, "建议持有天数": 1},
        ]
    ).to_csv(daily_dir / "daily_20260102.csv", index=False)

    rows = []
    for code, path in {"000001": [10, 11, 12, 13], "000002": [10, 10, 10, 10], "000003": [10, 9, 8, 7]}.items():
        for d, px in zip(pd.date_range("2026-01-01", periods=4, freq="D"), path):
            rows.append({"ts_code": code, "trade_date": d.strftime("%Y%m%d"), "open": px, "close": px, "amount": 100_000_000.0})
    market_file = data_dir / "daily_all_5y.parquet"
    pd.DataFrame(rows).to_parquet(market_file, index=False)

    monkeypatch.setattr(attrib, "DATA_DIR", data_dir)
    monkeypatch.setattr(attrib, "EXEC_DIR", exec_dir)

    out, meta = attrib.build_attribution(
        daily_glob=str(daily_dir / "daily_*.csv"),
        market_file=market_file,
        forward_days=1,
        top_n=3,
    )

    overall = out[out["segment"] == "overall"]
    assert set(overall["stage"]) >= {"raw_ml_top", "quality_gate", "refactor", "optimizer", "pretrade", "p2_fill"}
    raw = overall[overall["stage"] == "raw_ml_top"].iloc[0]
    assert raw["valid_forward_rows"] > 0
    assert raw["rank_ic_mean"] > 0
    assert meta["daily_rows"] == 6
    assert "full-universe" in meta["limitation"]
