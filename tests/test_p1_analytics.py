# -*- coding: utf-8 -*-
"""P1 风险归因脚本核心计算测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

import scripts.quant_p1_analytics as p1


def _mock_bars_idx() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2026-03-20"), pd.Timestamp("2026-03-20")],
            "code": ["000001", "000002"],
            "open": [10.0, 20.0],
            "vol": [1_000_000, 2_000_000],
            "amount": [100_000_000, 200_000_000],
        }
    )
    return df.set_index(["trade_date", "code"]).sort_index()


def test_parse_codes_and_weights_respects_total_exposure():
    row = pd.Series(
        {
            "codes": "000001,000002",
            "weights": "0.02,0.03",
            "total_exposure": 0.10,
        }
    )
    codes, weights = p1._parse_codes_and_weights(row)
    assert codes == ["000001", "000002"]
    assert np.isclose(float(weights.sum()), 0.10)
    assert np.isclose(weights[0] / weights[1], 2 / 3)


def test_build_trade_and_position_frames_generates_capacity_metrics():
    trades_df = pd.DataFrame(
        [
            {
                "signal_date": "2026-03-19",
                "entry_date": "2026-03-20",
                "state": "正常",
                "exit_reason": "time_exit",
                "codes": "000001,000002",
                "weights": "0.02,0.03",
                "total_exposure": 0.05,
                "portfolio_ret": 0.01,
                "excess_ret": 0.004,
            }
        ]
    )
    trades_df["signal_date"] = pd.to_datetime(trades_df["signal_date"])
    trades_df["entry_date"] = pd.to_datetime(trades_df["entry_date"])

    diag_df, pos_df = p1._build_trade_and_position_frames(
        trades_df=trades_df,
        bars_idx=_mock_bars_idx(),
        industry_map={"000001": "银行", "000002": "地产"},
        capital_base=1_000_000,
        adv_participation=0.05,
        fee_bps=8.0,
        slippage_bps=5.0,
        stamp_tax_bps=10.0,
    )

    assert len(diag_df) == 1
    assert len(pos_df) == 2
    row = diag_df.iloc[0]
    assert row["position_count"] == 2
    assert row["top_industry"] in {"银行", "地产"}
    assert row["estimated_roundtrip_cost"] > 0
    assert row["max_participation_pct"] > 0
    assert row["trade_capacity_capital"] > 0


def test_build_exposure_summary_contains_total_row():
    diag_df = pd.DataFrame(
        [
            {
                "entry_date": "2026-03-20",
                "state": "正常",
                "total_exposure_pct": 50.0,
                "position_count": 8,
                "portfolio_ret_pct": 1.2,
                "excess_ret_pct": 0.7,
                "weight_hhi": 0.20,
                "top_industry_weight_pct": 32.0,
                "max_participation_pct": 1.5,
            },
            {
                "entry_date": "2026-03-21",
                "state": "震荡",
                "total_exposure_pct": 45.0,
                "position_count": 7,
                "portfolio_ret_pct": -0.6,
                "excess_ret_pct": -0.3,
                "weight_hhi": 0.24,
                "top_industry_weight_pct": 35.0,
                "max_participation_pct": 1.2,
            },
        ]
    )
    out = p1._build_exposure_summary(diag_df)
    assert "__TOTAL__" in set(out["state"])
    total = out[out["state"] == "__TOTAL__"].iloc[0]
    assert total["trades"] == 2
