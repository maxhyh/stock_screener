# -*- coding: utf-8 -*-
"""Signal quality scoring tests."""

from __future__ import annotations

import pandas as pd

from utils.signal_quality import add_signal_quality_columns


def test_add_signal_quality_columns_prefers_balanced_signal():
    df = pd.DataFrame(
        [
            {
                "ml_score": 0.90,
                "bias": 35.0,
                "z_score": 3.1,
                "rsi": 92.0,
                "vol_ratio": 0.05,
                "pct_chg": 9.6,
            },
            {
                "ml_score": 0.80,
                "bias": -8.0,
                "z_score": -1.2,
                "rsi": 58.0,
                "vol_ratio": 1.1,
                "pct_chg": 1.2,
            },
        ]
    )
    out = add_signal_quality_columns(
        df,
        bias_col="bias",
        z_col="z_score",
        rsi_col="rsi",
        vol_ratio_col="vol_ratio",
        pct_chg_col="pct_chg",
        ml_col="ml_score",
        ml_weight=0.3,
    )
    assert float(out["signal_quality"].min()) >= 0.0
    assert float(out["signal_quality"].max()) <= 1.0
    assert float(out.loc[1, "signal_quality"]) > float(out.loc[0, "signal_quality"])
    assert float(out.loc[1, "hybrid_score"]) > float(out.loc[0, "hybrid_score"])
