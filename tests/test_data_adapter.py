# -*- coding: utf-8 -*-
"""数据适配层单位口径测试。"""

from __future__ import annotations

import pandas as pd

import data.data_adapter as data_adapter


def test_convert_tushare_to_mfts_keeps_volume_in_hands(tmp_path, monkeypatch):
    csv_path = tmp_path / "daily.csv"
    out_dir = tmp_path / "out"
    pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260410",
                "open": 10.0,
                "high": 10.2,
                "low": 9.8,
                "close": 10.1,
                "vol": 1234.0,
                "amount": 5678.0,
                "pct_chg": 1.0,
            }
        ]
    ).to_csv(csv_path, index=False)

    monkeypatch.setattr(data_adapter, "DAILY_CSV", str(csv_path))
    monkeypatch.setattr(data_adapter, "OUTPUT_DIR", str(out_dir))

    output_file = data_adapter.convert_tushare_to_mfts_format()
    out = pd.read_parquet(output_file)

    assert float(out.loc[0, "vol"]) == 1234.0
    assert float(out.loc[0, "amount"]) == 5678000.0
