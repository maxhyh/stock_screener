# -*- coding: utf-8 -*-
"""Signal quality helpers used by research, backtest and execution layers."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _safe_series(df: pd.DataFrame, col: str, default: float) -> pd.Series:
    if col not in df.columns:
        return pd.Series([default] * len(df), index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def compute_signal_quality_score(
    bias: pd.Series,
    z_score: pd.Series,
    rsi: pd.Series,
    vol_ratio: pd.Series,
    pct_chg: pd.Series,
    *,
    max_abs_pct_chg: float = 9.0,
) -> pd.Series:
    """
    Compute a 0~1 quality score based on same-day signal features only.

    Design goal:
    - penalize "too hot / too stretched / too illiquid" candidates
    - keep score definition simple and stable to reduce overfitting risk
    """
    cap = max(1.0, float(max_abs_pct_chg))

    chg_pen = np.clip(np.abs(pct_chg.to_numpy(dtype=float)) / cap, 0.0, 1.0)
    rsi_pen = np.clip((rsi.to_numpy(dtype=float) - 78.0) / 18.0, 0.0, 1.0)
    bias_pen = np.clip((np.abs(bias.to_numpy(dtype=float)) - 18.0) / 20.0, 0.0, 1.0)

    vr = vol_ratio.to_numpy(dtype=float)
    vol_low_pen = np.clip((0.35 - vr) / 0.35, 0.0, 1.0)
    vol_high_pen = np.clip((vr - 3.5) / 2.5, 0.0, 1.0)
    vol_pen = np.maximum(vol_low_pen, vol_high_pen)

    z_arr = z_score.to_numpy(dtype=float)
    z_extreme_pen = np.clip((np.abs(z_arr) - 2.8) / 2.0, 0.0, 1.0)

    # Mild oversold (not knife-catch) gets small positive bump.
    z_reversion_boost = np.clip((-z_arr - 0.2) / 2.0, 0.0, 1.0) * 0.10

    penalty = (
        0.30 * chg_pen
        + 0.25 * rsi_pen
        + 0.20 * bias_pen
        + 0.15 * vol_pen
        + 0.10 * z_extreme_pen
    )
    quality = np.clip(1.0 - penalty + z_reversion_boost, 0.0, 1.0)
    return pd.Series(quality, index=bias.index, dtype=float)


def add_signal_quality_columns(
    df: pd.DataFrame,
    *,
    bias_col: str,
    z_col: str,
    rsi_col: str,
    vol_ratio_col: str,
    pct_chg_col: str,
    max_abs_pct_chg: float = 9.0,
    quality_col: str = "signal_quality",
    score_col: str = "hybrid_score",
    ml_col: str = "ml_score",
    ml_weight: float = 0.85,
) -> pd.DataFrame:
    out = df.copy()
    bias = _safe_series(out, bias_col, 0.0)
    z_score = _safe_series(out, z_col, 0.0)
    rsi = _safe_series(out, rsi_col, 50.0)
    vol_ratio = _safe_series(out, vol_ratio_col, 1.0)
    pct_chg = _safe_series(out, pct_chg_col, 0.0)
    ml = _safe_series(out, ml_col, 0.0)

    out[quality_col] = compute_signal_quality_score(
        bias=bias,
        z_score=z_score,
        rsi=rsi,
        vol_ratio=vol_ratio,
        pct_chg=pct_chg,
        max_abs_pct_chg=max_abs_pct_chg,
    )
    w = min(max(float(ml_weight), 0.0), 1.0)
    ml_rank = ml.rank(pct=True, method="average")
    out[score_col] = w * ml_rank + (1.0 - w) * out[quality_col]
    return out

