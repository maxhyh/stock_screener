"""Market data unit normalization helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd


def normalize_amount_volume_units(
    df: pd.DataFrame,
    *,
    date_col: str = "trade_date",
    amount_col: str = "amount",
    vol_col: str = "vol",
    min_rows: int = 500,
    low_amount_threshold: float = 10_000_000.0,
    low_amount_share_threshold: float = 0.80,
) -> pd.DataFrame:
    """Normalize mixed A-share amount/volume units without mutating the input.

    The project expects ``amount`` in RMB and ``vol`` in hands. Some upstream
    batch interfaces can mix date-level units where most rows on a date are
    ``amount`` in thousand RMB and ``vol`` in ten-thousand hands. Such dates
    look like a full-market liquidity collapse and can create false ADV blocks.
    We detect only broad date-level unit shifts; sparse low-turnover names are
    left untouched.
    """
    if df is None or df.empty or date_col not in df.columns or amount_col not in df.columns:
        return df.copy() if df is not None else pd.DataFrame()

    out = df.copy()
    amount = pd.to_numeric(out[amount_col], errors="coerce")
    valid = amount.replace([np.inf, -np.inf], np.nan).gt(0)
    if int(valid.sum()) <= 0:
        return out

    date_key = out[date_col].astype(str)
    by_date = pd.DataFrame({"date": date_key, "amount": amount, "valid": valid})
    stats = by_date[by_date["valid"]].groupby("date", dropna=False)["amount"].agg(["count", "median"])
    low_share = by_date[by_date["valid"]].assign(low=by_date.loc[by_date["valid"], "amount"] < low_amount_threshold).groupby(
        "date", dropna=False
    )["low"].mean()
    stats["low_share"] = low_share
    suspect_dates = set(
        stats[
            (stats["count"] >= int(min_rows))
            & (stats["median"] < float(low_amount_threshold))
            & (stats["low_share"] >= float(low_amount_share_threshold))
        ].index.astype(str)
    )
    if not suspect_dates:
        return out

    mask = date_key.isin(suspect_dates)
    out.loc[mask, amount_col] = pd.to_numeric(out.loc[mask, amount_col], errors="coerce") * 1000.0
    if vol_col in out.columns:
        vol = pd.to_numeric(out.loc[mask, vol_col], errors="coerce")
        valid_vol_idx = vol[vol.notna()].index
        out.loc[valid_vol_idx, vol_col] = vol.loc[valid_vol_idx] * 10000.0
    return out
