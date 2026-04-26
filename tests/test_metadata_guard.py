# -*- coding: utf-8 -*-
"""元数据健康度门禁测试。"""

from __future__ import annotations

import os
import time

import pandas as pd

from utils.metadata_guard import evaluate_metadata_guard, load_metadata_health


def test_load_metadata_health_reads_coverage_and_age(tmp_path):
    meta_file = tmp_path / "stock_info.csv"
    pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ"],
            "name": ["平安银行", "万科A"],
            "industry": ["银行", ""],
        }
    ).to_csv(meta_file, index=False, encoding="utf-8")
    now = time.time()
    os.utime(meta_file, (now, now))

    info = load_metadata_health(tmp_path)

    assert info["ok"] is True
    assert info["rows"] == 2
    assert info["industry_nonempty"] == 1
    assert abs(float(info["coverage_pct"]) - 50.0) < 1e-9
    assert float(info["age_days"]) < 1.0


def test_evaluate_metadata_guard_blocks_low_coverage_and_stale():
    info = {
        "ok": True,
        "file": "mock.csv",
        "rows": 2,
        "industry_nonempty": 1,
        "coverage_pct": 50.0,
        "age_days": 5.0,
    }

    out = evaluate_metadata_guard(info, min_coverage_pct=80.0, max_age_days=3.0)

    assert out["passed"] is False
    assert out["coverage_ok"] is False
    assert out["freshness_ok"] is False
    assert out["reason"] == "industry_coverage_low,metadata_stale"
