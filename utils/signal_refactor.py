# -*- coding: utf-8 -*-
"""Signal feature-refactor helpers (redundancy control + stability score)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _safe_series(df: pd.DataFrame, col: str, default: float) -> pd.Series:
    if col not in df.columns:
        return pd.Series([default] * len(df), index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def _compute_redundancy_weights(feat_df: pd.DataFrame) -> dict[str, float]:
    base = {
        "bias_component": 0.22,
        "z_component": 0.24,
        "rsi_component": 0.18,
        "vol_component": 0.18,
        "chg_component": 0.18,
    }
    if feat_df.empty or len(feat_df) < 20:
        return base

    corr = feat_df.corr().abs().fillna(0.0)
    out: dict[str, float] = {}
    for c in base:
        peers = [x for x in corr.columns if x != c]
        if not peers:
            out[c] = base[c]
            continue
        high = corr.loc[c, peers]
        # use only high-corr part to penalize feature redundancy
        high_pen = float(high[high > 0.85].mean()) if (high > 0.85).any() else 0.0
        out[c] = base[c] * (1.0 - 0.45 * high_pen)
    s = float(sum(out.values()))
    if s <= 1e-9:
        return base
    return {k: float(v / s) for k, v in out.items()}


def add_feature_refactor_columns(
    df: pd.DataFrame,
    *,
    bias_col: str,
    z_col: str,
    rsi_col: str,
    vol_ratio_col: str,
    pct_chg_col: str,
    base_score_col: str = "hybrid_score",
    stability_col: str = "stability_score",
    refactor_col: str = "refactor_score",
    redundancy_col: str = "feature_redundancy",
    blend: float = 0.20,
    max_abs_pct_chg: float = 9.0,
) -> pd.DataFrame:
    out = df.copy()
    bias = _safe_series(out, bias_col, 0.0)
    z_score = _safe_series(out, z_col, 0.0)
    rsi = _safe_series(out, rsi_col, 50.0)
    vol_ratio = _safe_series(out, vol_ratio_col, 1.0)
    pct_chg = _safe_series(out, pct_chg_col, 0.0)
    base = _safe_series(out, base_score_col, 0.0).clip(0.0, 1.0)

    # Components: higher is better
    bias_component = 1.0 - np.clip((np.abs(bias.to_numpy(dtype=float)) - 10.0) / 22.0, 0.0, 1.0)
    z_component = 1.0 - np.clip((np.abs(z_score.to_numpy(dtype=float)) - 1.5) / 2.5, 0.0, 1.0)
    rsi_component = 1.0 - np.clip(np.abs(rsi.to_numpy(dtype=float) - 55.0) / 35.0, 0.0, 1.0)
    vr = vol_ratio.to_numpy(dtype=float)
    vol_component = 1.0 - np.maximum(
        np.clip((0.40 - vr) / 0.40, 0.0, 1.0),
        np.clip((vr - 3.20) / 2.80, 0.0, 1.0),
    )
    cap = max(1.0, float(max_abs_pct_chg))
    chg_component = 1.0 - np.clip(np.abs(pct_chg.to_numpy(dtype=float)) / cap, 0.0, 1.0)

    feat_df = pd.DataFrame(
        {
            "bias_component": bias_component,
            "z_component": z_component,
            "rsi_component": rsi_component,
            "vol_component": vol_component,
            "chg_component": chg_component,
        },
        index=out.index,
    )
    w = _compute_redundancy_weights(feat_df)
    stability = (
        w["bias_component"] * feat_df["bias_component"]
        + w["z_component"] * feat_df["z_component"]
        + w["rsi_component"] * feat_df["rsi_component"]
        + w["vol_component"] * feat_df["vol_component"]
        + w["chg_component"] * feat_df["chg_component"]
    )
    # mild mean-reversion bonus
    boost = np.clip((-z_score.to_numpy(dtype=float) - 0.1) / 2.2, 0.0, 1.0) * 0.08
    stability = np.clip(stability.to_numpy(dtype=float) + boost, 0.0, 1.0)

    blend = min(max(float(blend), 0.0), 1.0)
    refactor = np.clip((1.0 - blend) * base.to_numpy(dtype=float) + blend * stability, 0.0, 1.0)

    out[stability_col] = pd.Series(stability, index=out.index, dtype=float)
    out[refactor_col] = pd.Series(refactor, index=out.index, dtype=float)
    out[redundancy_col] = 1.0 - (
        w["bias_component"] * feat_df["bias_component"]
        + w["z_component"] * feat_df["z_component"]
        + w["rsi_component"] * feat_df["rsi_component"]
        + w["vol_component"] * feat_df["vol_component"]
        + w["chg_component"] * feat_df["chg_component"]
    )
    out[redundancy_col] = pd.to_numeric(out[redundancy_col], errors="coerce").fillna(0.0).clip(0.0, 1.0)
    return out

