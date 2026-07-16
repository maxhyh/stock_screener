# -*- coding: utf-8 -*-
"""Market data unit normalization tests."""

from __future__ import annotations

import pandas as pd

from utils.market_data_units import normalize_amount_volume_units


def test_normalize_amount_volume_units_scales_date_level_spot_units():
    rows = []
    for i in range(600):
        rows.append(
            {
                "trade_date": "20260407",
                "ts_code": f"{i:06d}.SH",
                "close": 10.0,
                "amount": 100_000.0,
                "vol": 10.0,
            }
        )
    for i in range(600):
        rows.append(
            {
                "trade_date": "20260408",
                "ts_code": f"{i:06d}.SH",
                "close": 10.0,
                "amount": 100_000_000.0,
                "vol": 100_000.0,
            }
        )
    df = pd.DataFrame(rows)

    out = normalize_amount_volume_units(df)

    suspect = out[out["trade_date"].eq("20260407")]
    normal = out[out["trade_date"].eq("20260408")]
    assert float(suspect["amount"].iloc[0]) == 100_000_000.0
    assert float(suspect["vol"].iloc[0]) == 100_000.0
    assert float(normal["amount"].iloc[0]) == 100_000_000.0
    assert float(normal["vol"].iloc[0]) == 100_000.0


def test_normalize_amount_volume_units_does_not_scale_sparse_low_amount_names():
    df = pd.DataFrame(
        [
            {"trade_date": "20260407", "amount": 100_000.0, "vol": 10.0, "close": 10.0},
            {"trade_date": "20260407", "amount": 100_000_000.0, "vol": 100_000.0, "close": 10.0},
        ]
    )

    out = normalize_amount_volume_units(df, min_rows=500)

    assert out["amount"].tolist() == df["amount"].tolist()
    assert out["vol"].tolist() == df["vol"].tolist()
