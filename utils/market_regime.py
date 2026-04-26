"""市场状态识别与仓位建议。"""

from __future__ import annotations

from typing import Any


def detect_market_regime(
    day_df,
    panic_down_ratio: float = 0.75,
    panic_median_chg: float = -1.50,
    panic_oversold_ratio: float = 0.20,
) -> dict[str, Any]:
    """
    基于横截面数据识别市场状态并给出仓位建议。

    返回:
    {
      "state": "正常|震荡|恐慌",
      "position_range": "60%-80%",
      "single_stock_max": "10%",
      "down_ratio": float,
      "median_chg": float,
      "deep_oversold_ratio": float,
    }
    """
    if day_df is None or len(day_df) == 0:
        return {
            "state": "震荡",
            "position_range": "30%-50%",
            "single_stock_max": "6%",
            "down_ratio": 0.0,
            "median_chg": 0.0,
            "deep_oversold_ratio": 0.0,
        }

    down_ratio = float((day_df["pct_chg"] < 0).mean())
    median_chg = float(day_df["pct_chg"].median())
    deep_oversold_ratio = float(((day_df["bias"] < -10) | (day_df["z_score"] < -2.0)).mean())

    panic = (
        down_ratio >= panic_down_ratio
        and median_chg <= panic_median_chg
        and deep_oversold_ratio >= panic_oversold_ratio
    )

    if panic:
        state = "恐慌"
        position_range = "10%-25%"
        single_stock_max = "3%"
    elif down_ratio >= 0.55 or median_chg <= -0.40 or deep_oversold_ratio >= 0.12:
        state = "震荡"
        position_range = "30%-50%"
        single_stock_max = "6%"
    else:
        state = "正常"
        position_range = "60%-80%"
        single_stock_max = "10%"

    return {
        "state": state,
        "position_range": position_range,
        "single_stock_max": single_stock_max,
        "down_ratio": round(down_ratio, 4),
        "median_chg": round(median_chg, 4),
        "deep_oversold_ratio": round(deep_oversold_ratio, 4),
    }
